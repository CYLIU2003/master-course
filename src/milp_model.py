"""
milp_model.py — Gurobi MILP モデル生成

仕様書 §14.3, §7, §15 担当:
  1. Gurobi Model を生成
  2. 決定変数を追加 (§7)
  3. 制約を追加 (§10) — constraints/ の各モジュールを呼び出す
  4. 目的関数を設定 (§9)

変数命名規則 (§15):
  x_assign[k, r]    : 割当バイナリ
  y_follow[k,r1,r2] : タスク接続バイナリ
  u_vehicle[k]      : 車両使用バイナリ
  z_charge[k, c, t] : 充電器利用バイナリ
  p_charge[k, c, t] : 充電電力 [kW]
  soc[k, t]         : SOC [kWh]
  p_grid_import[i,t]: 系統受電電力 [kW]
  p_pv_used[i, t]   : PV 自家消費 [kW]
  peak_demand[i]    : ピーク需要 [kW]
  slack_cover[r]    : 需要未充足緩和
  slack_soc[k, t]   : SOC 違反緩和
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .gurobi_runtime import (
    configure_gurobipy_sys_path as _configure_gurobipy_sys_path,
    ensure_gurobi as _ensure_gurobi,
)

from .data_schema import ProblemData
from .model_sets import ModelSets
from .parameter_builder import DerivedParams
from .constraints.assignment import add_assignment_constraints
from .constraints.charging import add_charging_constraints, add_soc_constraints, add_ice_fuel_constraints
from .constraints.charger_capacity import add_charger_capacity_constraints
from .constraints.energy_balance import (
    add_energy_balance_constraints,
    add_demand_charge_constraints,
)
from .constraints.pv_grid import add_pv_grid_constraints
from .constraints.battery_degradation import add_battery_degradation_constraints
from .constraints.optional_v2g import add_v2g_constraints
from .constraints.duty_assignment import add_duty_assignment_constraints
from .objective import build_objective
from .refuel_schedule import compute_refuel_schedule_l


@dataclass
class MILPResult:
    """MILP 求解結果 (仕様書 §13.1)"""

    status: str                          # "OPTIMAL", "INFEASIBLE", etc.
    objective_value: Optional[float] = None
    solve_time_sec: float = 0.0
    mip_gap: Optional[float] = None

    # § 7.1.1 割当: vehicle_id -> [task_id, ...]
    assignment: Dict[str, List[str]] = field(default_factory=dict)

    # § 7.4.1 SOC 系列: vehicle_id -> [soc_t0, ..., soc_T]
    soc_series: Dict[str, List[float]] = field(default_factory=dict)

    # § 7.3.1 充電フラグ: vehicle_id -> charger_id -> [0/1, ...]
    charge_schedule: Dict[str, Dict[str, List[int]]] = field(default_factory=dict)

    # § 7.3.2 充電電力: vehicle_id -> charger_id -> [kW, ...]
    charge_power_kw: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)

    # ICE 補給量: vehicle_id -> [L per slot]
    refuel_schedule_l: Dict[str, List[float]] = field(default_factory=dict)

    # § 7.5 系統受電: site_id -> [kW, ...]
    grid_import_kw: Dict[str, List[float]] = field(default_factory=dict)

    # § 7.5 系統売電: site_id -> [kW, ...]
    grid_export_kw: Dict[str, List[float]] = field(default_factory=dict)

    # § 7.5 PV: site_id -> [kW, ...]
    pv_used_kw: Dict[str, List[float]] = field(default_factory=dict)

    # § 7.5 PV自家消費量合計 [kWh/day]: site_id -> kWh
    # ALNS の pv_to_bus_kwh と対称になるよう計算する。
    pv_to_bus_kwh: Dict[str, float] = field(default_factory=dict)

    # § 7.5 ピーク需要: site_id -> kW
    peak_demand_kw: Dict[str, float] = field(default_factory=dict)
    
    # Detailed energy flow breakdown (Phase 2.3)
    # Per-slot energy flow [kWh]: (depot_id, slot_idx) -> kWh
    grid_to_bus_kwh_by_slot: Dict[Tuple[str, int], float] = field(default_factory=dict)
    pv_to_bus_kwh_by_slot: Dict[Tuple[str, int], float] = field(default_factory=dict)
    bess_to_bus_kwh_by_slot: Dict[Tuple[str, int], float] = field(default_factory=dict)
    grid_to_bess_kwh_by_slot: Dict[Tuple[str, int], float] = field(default_factory=dict)
    pv_to_bess_kwh_by_slot: Dict[Tuple[str, int], float] = field(default_factory=dict)
    pv_curtailed_kwh_by_slot: Dict[Tuple[str, int], float] = field(default_factory=dict)
    
    # BESS SOC series: (depot_id, slot_idx) -> kWh
    bess_soc_kwh_by_slot: Dict[Tuple[str, int], float] = field(default_factory=dict)

    # 目的関数内訳 (§13.1.1)
    obj_breakdown: Dict[str, float] = field(default_factory=dict)

    # 未割当タスク
    unserved_tasks: List[str] = field(default_factory=list)

    # infeasible 原因 (IIS など)
    infeasibility_info: str = ""

    # SOC モデリング仮定の注記（論文引用用）
    soc_modeling_note: str = (
        "SOC energy is event-based (end-of-trip lump-sum). "
        "Real-world mid-trip SOC may be lower than reported. "
        "See thesis §10.5 for details."
    )


def pre_solve_check(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
) -> List[str]:
    """
    MILP 求解前に数理的に不可能な条件を早期検出する。

    Returns
    -------
    warnings : List[str]
        問題が見つかった場合の警告文リスト。空なら問題なし。
    """
    warnings: List[str] = []

    K_ALL = ms.K_ALL
    K_BEV = ms.K_BEV
    R     = ms.R
    C     = ms.C
    T     = ms.T
    delta_h = data.delta_t_hour  # [hour/slot]

    # ─── 1. カバー不可能タスクの検出 ───────────────────────────────────
    # demand_cover=True かつ allow_partial_service=False なのに
    # いずれの車両にも割り当て不可能なタスクがあれば即 INFEASIBLE
    if not data.allow_partial_service:
        uncoverable: List[str] = []
        for r in R:
            task = dp.task_lut.get(r)
            if task is None or not getattr(task, "demand_cover", True):
                continue
            feasible_vehicles = [
                k for k in K_ALL
                if r in ms.vehicle_task_feasible.get(k, set())
            ]
            if not feasible_vehicles:
                uncoverable.append(r)
        if uncoverable:
            warnings.append(
                f"[INFEASIBLE] カバー不可能タスク {len(uncoverable)} 件 "
                f"(担当可能車両ゼロ, allow_partial_service=False): "
                f"{uncoverable[:10]}{'...' if len(uncoverable) > 10 else ''}"
            )

    # ─── 2. BEV ごとの SOC エネルギー収支チェック ────────────────────────
    for k in K_BEV:
        veh = dp.vehicle_lut.get(k)
        if veh is None:
            continue

        cap = veh.battery_capacity if veh.battery_capacity is not None else 200.0
        soc_min   = veh.soc_min   if veh.soc_min   is not None else 0.0
        soc_max   = veh.soc_max   if veh.soc_max   is not None else cap
        soc_init  = veh.soc_init  if veh.soc_init  is not None else cap * 0.8
        soc_end   = getattr(veh, "soc_target_end", None)
        eff       = getattr(veh, "charge_efficiency", 1.0) or 1.0

        # (a) soc_target_end が soc_max を超えている
        if soc_end is not None and soc_end > soc_max + 1e-6:
            warnings.append(
                f"[INFEASIBLE] 車両 {k}: soc_target_end={soc_end:.1f} kWh > "
                f"soc_max={soc_max:.1f} kWh — 物理的に到達不能"
            )

        # (b) 最大充電量でも soc_target_end に届かない
        # (1 スロットも走行せず充電のみで最大充電した場合の上限)
        if soc_end is not None and C:
            compat_chargers = ms.vehicle_charger_feasible.get(k, set())
            max_charge_kw = sum(
                min(
                    dp.charger_lut[c].power_max_kw,
                    veh.charge_power_max if veh.charge_power_max else dp.charger_lut[c].power_max_kw,
                )
                for c in compat_chargers
                if c in dp.charger_lut
            )
            # 同時に 1 台しか充電できないので実効最大電力 = compat 内の最大 1 基
            max_single_kw = max(
                (
                    min(
                        dp.charger_lut[c].power_max_kw,
                        veh.charge_power_max if veh.charge_power_max else dp.charger_lut[c].power_max_kw,
                    )
                    for c in compat_chargers
                    if c in dp.charger_lut
                ),
                default=0.0,
            )
            max_chargeable_kwh = eff * max_single_kw * delta_h * len(T)
            theoretical_max_soc = min(soc_max, soc_init + max_chargeable_kwh)
            if soc_end > theoretical_max_soc + 1e-6:
                warnings.append(
                    f"[INFEASIBLE] 車両 {k}: soc_target_end={soc_end:.1f} kWh, "
                    f"理論最大 SOC={theoretical_max_soc:.1f} kWh "
                    f"(soc_init={soc_init:.1f}, max_charge_kW={max_single_kw:.1f}, "
                    f"slots={len(T)}, eff={eff:.2f}) — 充電のみでは届かない"
                )

        # (c) soc_min が soc_init より高い (開始時点で既に制約違反)
        if soc_min > soc_init + 1e-6 and not data.use_soft_soc_constraint:
            warnings.append(
                f"[INFEASIBLE] 車両 {k}: soc_min={soc_min:.1f} kWh > "
                f"soc_init={soc_init:.1f} kWh — 初期 SOC が最小制約を既に下回っている"
            )

    # ─── 3. 全体の充電器容量 vs BEV 必要充電量 ────────────────────────────
    # 「必要充電量」= 全トリップの走行エネルギー合計 + 全BEV の soc_target_end 合計
    #                 - 全BEV の soc_init 合計
    # （各車両の feasible タスク全量を合計する旧実装は70倍の過大見積もりになるため廃止）
    if K_BEV and C:
        # 全タスクの BEV 走行エネルギー合計（全トリップはいずれかの BEV が担当する）
        total_all_task_kwh = sum(dp.task_energy_bev.get(r, 0.0) for r in R)

        total_soc_init  = 0.0
        total_soc_end   = 0.0
        for k in K_BEV:
            veh = dp.vehicle_lut.get(k)
            if veh is None:
                continue
            cap      = veh.battery_capacity if veh.battery_capacity is not None else 200.0
            soc_i    = veh.soc_init if veh.soc_init is not None else cap * 0.8
            soc_e    = getattr(veh, "soc_target_end", None)
            total_soc_init += soc_i
            total_soc_end  += soc_e if soc_e is not None else 0.0

        # 必要充電量 = トリップ消費 + 終端SOC目標 - 初期SOC
        total_energy_deficit = max(0.0, total_all_task_kwh + total_soc_end - total_soc_init)

        # 全充電器の理論最大供給量（グリッド上限・サイト上限も考慮）
        # サイトごとに: min(充電器合計kW, grid_import_limit_kw) × 時間
        from collections import defaultdict
        chargers_by_site: dict = defaultdict(list)
        for c in C:
            charger = dp.charger_lut.get(c)
            if charger:
                chargers_by_site[charger.site_id].append(charger)
        max_supply_kwh = 0.0
        for site_id, site_chargers in chargers_by_site.items():
            site = dp.site_lut.get(site_id)
            grid_limit_kw = site.grid_import_limit_kw if site else 9999.0
            charger_total_kw = sum(c.power_max_kw for c in site_chargers)
            effective_kw = min(charger_total_kw, grid_limit_kw)
            max_supply_kwh += effective_kw * delta_h * len(T)

        if total_energy_deficit > max_supply_kwh * 1.05:  # 5% マージン
            warnings.append(
                f"[WARNING] 全 BEV 必要充電量合計={total_energy_deficit:.0f} kWh > "
                f"全充電器最大供給量={max_supply_kwh:.0f} kWh — 充電容量不足の可能性\n"
                f"  (内訳: 走行消費={total_all_task_kwh:.0f}, SOC終端目標={total_soc_end:.0f}, "
                f"SOC初期値={total_soc_init:.0f})"
            )

    # ─── 4. SOC 安全マージンチェック（イベントベース計上リスク）──────────────
    for k in K_BEV:
        veh = dp.vehicle_lut.get(k)
        if veh is None:
            continue
        soc_min = veh.soc_min if veh.soc_min is not None else 0.0
        max_trip_kwh = max(
            (dp.task_energy_bev.get(r, 0.0)
             for r in ms.vehicle_task_feasible.get(k, set())),
            default=0.0,
        )
        recommended_margin = max_trip_kwh * 0.5
        if soc_min < recommended_margin - 1e-6:
            warnings.append(
                f"[WARNING] 車両 {k}: soc_min={soc_min:.1f} kWh < "
                f"推奨安全マージン {recommended_margin:.1f} kWh "
                f"(最大単一トリップ {max_trip_kwh:.1f} kWh × 50%)。"
                f"イベントベースSOC計上により実運用でsoc_lb違反リスクあり。"
            )

    return warnings


def build_milp_model(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    flags: Optional[Dict[str, bool]] = None,
) -> tuple[Any, Dict[str, Any]]:
    """
    Gurobi Model と変数辞書を生成して返す。

    Parameters
    ----------
    data  : ProblemData
    ms    : ModelSets
    dp    : DerivedParams
    flags : 制約 ON/OFF フラグ (None の場合は全 ON)

    Returns
    -------
    (model, vars_dict)
    """
    # Re-try import at solve-time in case DLL paths were configured after module load
    gp, GRB = _ensure_gurobi()

    if flags is None:
        flags = {
            "assignment": True,
            "soc": True,
            "charging": True,
            "charger_capacity": True,
            "energy_balance": True,
            "pv_grid": data.enable_pv,
            "battery_degradation": data.enable_battery_degradation,
            "v2g": data.enable_v2g,
            "demand_charge": data.enable_demand_charge,
            "duty_assignment": data.duty_assignment_enabled,
        }

    model = gp.Model("ebus_milp")
    # IgnoreNames=0: 制約名を保持することで IIS 診断を可能にする。
    # 255 文字超の名前は Gurobi 側で自動截断されるため問題ない。
    model.Params.IgnoreNames = 0

    K_ALL = ms.K_ALL
    K_BEV = ms.K_BEV
    K_ICE = ms.K_ICE
    R     = ms.R
    T     = ms.T
    C     = ms.C
    I_CHARGE = ms.I_CHARGE

    vars: Dict[str, Any] = {}

    # ===== §7.1 割当変数 =====
    # x_assign[k, r]: 車両 k がタスク r を担当するなら 1
    # feasible な組み合わせのみ変数を作成してモデル規模を削減する。
    x_index = [
        (k, r)
        for k in K_ALL
        for r in ms.vehicle_task_feasible.get(k, set())
    ]
    vars["x_assign"] = model.addVars(x_index, vtype=GRB.BINARY, name="x_assign")

    # y_follow[k, r1, r2]: 車両 k が r1 の直後に r2 を担当するなら 1
    follow_index = []
    for k in K_ALL:
        feasible_tasks = ms.vehicle_task_feasible.get(k, set())
        for r1 in feasible_tasks:
            for r2, can in dp.can_follow.get(r1, {}).items():
                if not can or r2 == r1:
                    continue
                if r2 not in feasible_tasks:
                    continue
                follow_index.append((k, r1, r2))
    if follow_index:
        vars["y_follow"] = model.addVars(follow_index, vtype=GRB.BINARY, name="y_follow")

    # u_vehicle[k]: 車両 k を使用するなら 1
    vars["u_vehicle"] = model.addVars(K_ALL, vtype=GRB.BINARY, name="u_vehicle")

    # ===== §7.3 充電関連変数 (BEV のみ) =====
    if flags.get("charging", True) and K_BEV and C:
        charge_index = [
            (k, c, t)
            for k in K_BEV
            for c in ms.vehicle_charger_feasible.get(k, set())
            if c in C
            for t in T
        ]
        # z_charge[k, c, t]: 充電器利用バイナリ
        vars["z_charge"] = model.addVars(charge_index, vtype=GRB.BINARY, name="z_charge")

        # p_charge[k, c, t]: 充電電力 [kW]
        vars["p_charge"] = model.addVars(charge_index, lb=0.0, vtype=GRB.CONTINUOUS, name="p_charge")

    # ===== §7.4 SOC 変数 =====
    if flags.get("soc", True) and K_BEV:
        # soc[k, t]: t = 0 ... num_periods
        vars["soc"] = model.addVars(
            K_BEV, range(len(T) + 1), lb=0.0, vtype=GRB.CONTINUOUS, name="soc"
        )

    # ===== ICE 燃料残量変数 =====
    if K_ICE:
        vars["fuel"] = model.addVars(
            K_ICE, range(len(T) + 1), lb=0.0, vtype=GRB.CONTINUOUS, name="fuel"
        )

    # ===== §7.4.2 劣化変数 (BEV) =====
    if flags.get("battery_degradation", False) and K_BEV:
        vars["deg"] = model.addVars(K_BEV, T, lb=0.0, vtype=GRB.CONTINUOUS, name="deg")

    # ===== §7.5 系統・PV 変数 (地点単位) =====
    if flags.get("energy_balance", True) and I_CHARGE:
        vars["p_grid_import"] = model.addVars(
            I_CHARGE, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_grid_import"
        )
        vars["p_grid_export"] = model.addVars(
            I_CHARGE, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_grid_export"
        )
        vars["peak_demand"] = model.addVars(
            I_CHARGE, lb=0.0, vtype=GRB.CONTINUOUS, name="peak_demand"
        )

    if flags.get("pv_grid", False) and data.enable_pv and I_CHARGE:
        vars["p_pv_used"]   = model.addVars(I_CHARGE, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_pv_used")
        vars["p_pv_curtail"] = model.addVars(I_CHARGE, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_pv_curtail")

    # ===== §7.3.4 V2G 変数 =====
    if flags.get("v2g", False) and data.enable_v2g and K_BEV and C:
        discharge_index = [
            (k, c, t)
            for k in K_BEV
            for c in ms.vehicle_charger_feasible.get(k, set())
            if c in C
            for t in T
        ]
        vars["p_discharge"]  = model.addVars(discharge_index, lb=0.0, vtype=GRB.CONTINUOUS, name="p_discharge")
        vars["z_discharge"]  = model.addVars(K_BEV, T, vtype=GRB.BINARY, name="z_discharge")

    # ===== §7.6 緩和変数 =====
    if data.allow_partial_service:
        vars["slack_cover"] = model.addVars(R, vtype=GRB.BINARY, name="slack_cover")

    if data.use_soft_soc_constraint and K_BEV:
        vars["slack_soc"] = model.addVars(
            K_BEV, range(len(T) + 1), lb=0.0, vtype=GRB.CONTINUOUS, name="slack_soc"
        )

    model.update()

    # ===== 制約追加 =====
    if flags.get("assignment", True):
        add_assignment_constraints(model, data, ms, dp, vars)

    if flags.get("charging", True) and "z_charge" in vars:
        add_charging_constraints(model, data, ms, dp, vars)

    if flags.get("soc", True) and "soc" in vars and "p_charge" in vars:
        add_soc_constraints(model, data, ms, dp, vars)

    if "fuel" in vars:
        add_ice_fuel_constraints(model, data, ms, dp, vars)

    if flags.get("charger_capacity", True) and "z_charge" in vars:
        add_charger_capacity_constraints(model, data, ms, dp, vars)

    if flags.get("energy_balance", True) and "p_grid_import" in vars and "p_charge" in vars:
        add_energy_balance_constraints(model, data, ms, dp, vars)
        if flags.get("demand_charge", False):
            add_demand_charge_constraints(model, data, ms, dp, vars)

    if flags.get("pv_grid", False):
        add_pv_grid_constraints(model, data, ms, dp, vars)

    if flags.get("battery_degradation", False) and "deg" in vars and "p_charge" in vars:
        add_battery_degradation_constraints(model, data, ms, dp, vars)

    if flags.get("v2g", False) and "p_discharge" in vars and "z_discharge" in vars and "p_charge" in vars:
        add_v2g_constraints(model, data, ms, dp, vars)

    # ===== §6 行路制約 (duty assignment) =====
    if flags.get("duty_assignment", False) and data.duty_assignment_enabled and data.duty_list:
        add_duty_assignment_constraints(model, data, ms, dp, vars)

    # ===== SOC 閾値自動充電制約 =====
    if flags.get("soc_threshold", False) and "soc" in vars and "z_charge" in vars:
        from .constraints.soc_threshold_charging import add_soc_threshold_charging_constraints
        trigger_ratio = getattr(data, "_soc_trigger_ratio", 0.20)
        resume_ratio = getattr(data, "_soc_resume_ratio", 0.40)
        add_soc_threshold_charging_constraints(
            model, data, ms, dp, vars,
            trigger_ratio=trigger_ratio,
            resume_ratio=resume_ratio,
        )

    # ===== 目的関数設定 =====
    build_objective(model, data, ms, dp, vars)

    return model, vars


def extract_result(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
    solve_time: float,
) -> MILPResult:
    """
    Gurobi 求解後の結果を MILPResult に変換して返す。
    """
    status_map = {
        1: "LOADED", 2: "OPTIMAL", 3: "INFEASIBLE", 4: "INF_OR_UNBD",
        5: "UNBOUNDED", 9: "TIME_LIMIT", 13: "SUBOPTIMAL",
    }
    status_text = status_map.get(model.Status, f"STATUS_{model.Status}")

    result = MILPResult(status=status_text, solve_time_sec=solve_time)

    if model.SolCount == 0:
        # infeasible 時は IIS 情報を記録
        if model.Status == 3:
            try:
                model.computeIIS()
                iis_constrs = [c.ConstrName for c in model.getConstrs() if c.IISConstr]
                total = len(iis_constrs)

                # 制約名プレフィックスでグループ化 (名前が "prefix[...]" の形式を仮定)
                from collections import defaultdict
                groups: dict = defaultdict(list)
                for cname in iis_constrs:
                    prefix = cname.split("[")[0] if "[" in cname else cname
                    groups[prefix].append(cname)

                lines = [f"IIS: {total} 件の制約が矛盾 (IgnoreNames=0)"]
                for prefix, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                    sample = members[0]
                    lines.append(f"  {prefix}: {len(members):>6} 件  例: {sample}")

                # IIS に含まれる変数上下限も確認
                try:
                    iis_lb_vars = [v.VarName for v in model.getVars() if v.IISLB]
                    iis_ub_vars = [v.VarName for v in model.getVars() if v.IISUB]
                    if iis_lb_vars:
                        lines.append(f"  [LB violated] {len(iis_lb_vars)} vars: {iis_lb_vars[:5]}")
                    if iis_ub_vars:
                        lines.append(f"  [UB violated] {len(iis_ub_vars)} vars: {iis_ub_vars[:5]}")
                except Exception:
                    pass

                result.infeasibility_info = "\n".join(lines)
            except Exception as e:
                result.infeasibility_info = str(e)
        return result

    result.objective_value = float(model.ObjVal)
    try:
        result.mip_gap = float(model.MIPGap)
    except Exception:
        pass
    obj_terms = vars.get("obj_terms") or {}
    if isinstance(obj_terms, dict):
        for name, expr in obj_terms.items():
            try:
                result.obj_breakdown[str(name)] = round(float(expr.getValue()), 6)
            except Exception:
                try:
                    result.obj_breakdown[str(name)] = round(float(expr), 6)
                except Exception:
                    continue

    T     = ms.T
    K_ALL = ms.K_ALL
    K_BEV = ms.K_BEV
    R     = ms.R
    C     = ms.C
    I_CHARGE = ms.I_CHARGE

    x = vars.get("x_assign")
    soc = vars.get("soc")
    z   = vars.get("z_charge")
    p   = vars.get("p_charge")
    p_grid = vars.get("p_grid_import")
    p_grid_export = vars.get("p_grid_export")
    p_pv   = vars.get("p_pv_used")
    peak   = vars.get("peak_demand")
    slack_cover = vars.get("slack_cover")

    # --- 割当 ---
    if x is not None:
        for k in K_ALL:
            assigned = [r for r in R if (k, r) in x and x[k, r].X > 0.5]
            if assigned:
                result.assignment[k] = assigned

    # --- 未割当 ---
    if x is not None:
        for r_id in R:
            total = sum(x[k, r_id].X for k in K_ALL if (k, r_id) in x)
            if total < 0.5:
                result.unserved_tasks.append(r_id)

    # --- ICE 補給スケジュール (全モード共通推定) ---
    result.refuel_schedule_l = compute_refuel_schedule_l(data, ms, dp, result.assignment)

    # --- SOC ---
    if soc is not None:
        for k in K_BEV:
            result.soc_series[k] = [
                round(float(soc[k, t].X), 4) for t in range(len(T) + 1)
            ]

    # --- 充電スケジュール ---
    if z is not None:
        for k in K_BEV:
            sched: Dict[str, List[int]] = {}
            for c in C:
                series = [int(round(z[k, c, t].X)) if (k, c, t) in z else 0 for t in T]
                if any(v > 0 for v in series):
                    sched[c] = series
            if sched:
                result.charge_schedule[k] = sched

    if p is not None:
        for k in K_BEV:
            pwr: Dict[str, List[float]] = {}
            for c in C:
                series = [round(float(p[k, c, t].X), 4) if (k, c, t) in p else 0.0 for t in T]
                if any(abs(v) > 1e-9 for v in series):
                    pwr[c] = series
            if pwr:
                result.charge_power_kw[k] = pwr

    # --- 系統受電 ---
    if p_grid is not None:
        for site_id in I_CHARGE:
            result.grid_import_kw[site_id] = [
                round(float(p_grid[site_id, t].X), 4) for t in T
            ]

    if p_grid_export is not None:
        for site_id in I_CHARGE:
            result.grid_export_kw[site_id] = [
                round(float(p_grid_export[site_id, t].X), 4) for t in T
            ]

    # --- PV ---
    if p_pv is not None:
        for site_id in I_CHARGE:
            try:
                result.pv_used_kw[site_id] = [
                    round(float(p_pv[site_id, t].X), 4) for t in T
                ]
            except Exception:
                pass

    # --- PV自家消費量合計 (kWh換算) ---
    # ALNS evaluator.py の pv_to_bus_kwh と単位・定義を合わせる
    if p_pv is not None:
        delta_h = data.delta_t_hour
        for site_id in I_CHARGE:
            try:
                result.pv_to_bus_kwh[site_id] = round(
                    sum(float(p_pv[site_id, t].X) * delta_h for t in T), 4
                )
            except Exception:
                pass

    # --- ピーク需要 ---
    if peak is not None:
        for site_id in I_CHARGE:
            try:
                result.peak_demand_kw[site_id] = round(float(peak[site_id].X), 4)
            except Exception:
                pass

    return result
