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
from typing import Any, Dict, List, Optional

try:
    import gurobipy as gp
    from gurobipy import GRB
    _GUROBI_AVAILABLE = True
except ImportError:
    _GUROBI_AVAILABLE = False

from .data_schema import ProblemData
from .model_sets import ModelSets
from .parameter_builder import DerivedParams
from .constraints.assignment import add_assignment_constraints
from .constraints.charging import add_charging_constraints, add_soc_constraints
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

    # § 7.5 系統受電: site_id -> [kW, ...]
    grid_import_kw: Dict[str, List[float]] = field(default_factory=dict)

    # § 7.5 PV: site_id -> [kW, ...]
    pv_used_kw: Dict[str, List[float]] = field(default_factory=dict)

    # § 7.5 ピーク需要: site_id -> kW
    peak_demand_kw: Dict[str, float] = field(default_factory=dict)

    # 目的関数内訳 (§13.1.1)
    obj_breakdown: Dict[str, float] = field(default_factory=dict)

    # 未割当タスク
    unserved_tasks: List[str] = field(default_factory=list)

    # infeasible 原因 (IIS など)
    infeasibility_info: str = ""


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
    if not _GUROBI_AVAILABLE:
        raise RuntimeError("Gurobi が利用できません。gurobipy をインストールしてください。")

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
    vars["x_assign"] = model.addVars(K_ALL, R, vtype=GRB.BINARY, name="x_assign")

    # u_vehicle[k]: 車両 k を使用するなら 1
    vars["u_vehicle"] = model.addVars(K_ALL, vtype=GRB.BINARY, name="u_vehicle")

    # ===== §7.3 充電関連変数 (BEV のみ) =====
    if flags.get("charging", True) and K_BEV and C:
        # z_charge[k, c, t]: 充電器利用バイナリ
        vars["z_charge"] = model.addVars(K_BEV, C, T, vtype=GRB.BINARY, name="z_charge")

        # p_charge[k, c, t]: 充電電力 [kW]
        vars["p_charge"] = model.addVars(K_BEV, C, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_charge")

    # ===== §7.4 SOC 変数 =====
    if flags.get("soc", True) and K_BEV:
        # soc[k, t]: t = 0 ... num_periods
        vars["soc"] = model.addVars(
            K_BEV, range(len(T) + 1), lb=0.0, vtype=GRB.CONTINUOUS, name="soc"
        )

    # ===== §7.4.2 劣化変数 (BEV) =====
    if flags.get("battery_degradation", False) and K_BEV:
        vars["deg"] = model.addVars(K_BEV, T, lb=0.0, vtype=GRB.CONTINUOUS, name="deg")

    # ===== §7.5 系統・PV 変数 (地点単位) =====
    if flags.get("energy_balance", True) and I_CHARGE:
        vars["p_grid_import"] = model.addVars(
            I_CHARGE, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_grid_import"
        )
        vars["peak_demand"] = model.addVars(
            I_CHARGE, lb=0.0, vtype=GRB.CONTINUOUS, name="peak_demand"
        )

    if flags.get("pv_grid", False) and data.enable_pv and I_CHARGE:
        vars["p_pv_used"]   = model.addVars(I_CHARGE, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_pv_used")
        vars["p_pv_curtail"] = model.addVars(I_CHARGE, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_pv_curtail")

    # ===== §7.3.4 V2G 変数 =====
    if flags.get("v2g", False) and data.enable_v2g and K_BEV and C:
        vars["p_discharge"]  = model.addVars(K_BEV, C, T, lb=0.0, vtype=GRB.CONTINUOUS, name="p_discharge")
        vars["z_discharge"]  = model.addVars(K_BEV, T, vtype=GRB.BINARY, name="z_discharge")

    # ===== §7.6 緩和変数 =====
    if data.allow_partial_service:
        vars["slack_cover"] = model.addVars(R, lb=0.0, vtype=GRB.CONTINUOUS, name="slack_cover")

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

    if flags.get("soc", True) and "soc" in vars:
        add_soc_constraints(model, data, ms, dp, vars)

    if flags.get("charger_capacity", True) and "z_charge" in vars:
        add_charger_capacity_constraints(model, data, ms, dp, vars)

    if flags.get("energy_balance", True) and "p_grid_import" in vars:
        add_energy_balance_constraints(model, data, ms, dp, vars)
        if flags.get("demand_charge", False):
            add_demand_charge_constraints(model, data, ms, dp, vars)

    if flags.get("pv_grid", False):
        add_pv_grid_constraints(model, data, ms, dp, vars)

    if flags.get("battery_degradation", False):
        add_battery_degradation_constraints(model, data, ms, dp, vars)

    if flags.get("v2g", False):
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
                result.infeasibility_info = f"IIS constraints: {iis_constrs[:20]}"
            except Exception as e:
                result.infeasibility_info = str(e)
        return result

    result.objective_value = float(model.ObjVal)
    try:
        result.mip_gap = float(model.MIPGap)
    except Exception:
        pass

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
    p_pv   = vars.get("p_pv_used")
    peak   = vars.get("peak_demand")
    slack_cover = vars.get("slack_cover")

    # --- 割当 ---
    if x is not None:
        for k in K_ALL:
            assigned = [r for r in R if x[k, r].X > 0.5]
            if assigned:
                result.assignment[k] = assigned

    # --- 未割当 ---
    if x is not None:
        for r_id in R:
            total = sum(x[k, r_id].X for k in K_ALL)
            if total < 0.5:
                result.unserved_tasks.append(r_id)

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
                series = [int(round(z[k, c, t].X)) for t in T]
                if any(v > 0 for v in series):
                    sched[c] = series
            if sched:
                result.charge_schedule[k] = sched

    if p is not None:
        for k in K_BEV:
            pwr: Dict[str, List[float]] = {}
            for c in C:
                series = [round(float(p[k, c, t].X), 4) for t in T]
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

    # --- PV ---
    if p_pv is not None:
        for site_id in I_CHARGE:
            try:
                result.pv_used_kw[site_id] = [
                    round(float(p_pv[site_id, t].X), 4) for t in T
                ]
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
