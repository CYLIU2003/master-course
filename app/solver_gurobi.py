"""
solver_gurobi.py — Gurobi (MILP) ソルバー

既存の solve_ebus_gurobi.py の定式化を ProblemConfig ベースで再実装。
ステージ別実行にも対応。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .model_core import (
    ChargerSpec,
    ProblemConfig,
    SolveResult,
    precompute_helpers,
)

# Gurobi が無い環境用のフォールバック
_GUROBI_AVAILABLE = False
try:
    import gurobipy as gp
    from gurobipy import GRB
    _GUROBI_AVAILABLE = True
except ImportError:
    pass


VALID_STAGES = [
    "assignment_only",
    "assignment_plus_soc",
    "assignment_soc_charging",
    "full_with_pv",
]


def is_gurobi_available() -> bool:
    return _GUROBI_AVAILABLE


def _stage_flags(stage: str) -> Dict[str, bool]:
    return {
        "assignment": True,
        "soc": stage in {
            "assignment_plus_soc",
            "assignment_soc_charging",
            "full_with_pv",
        },
        "charging": stage in {
            "assignment_soc_charging",
            "full_with_pv",
        },
        "pv": stage == "full_with_pv",
    }


def _charger_lookup(
    chargers: List[ChargerSpec],
) -> Dict[str, Dict[str, ChargerSpec]]:
    """depot -> charger_type -> ChargerSpec"""
    lookup: Dict[str, Dict[str, ChargerSpec]] = {}
    for c in chargers:
        lookup.setdefault(c.depot, {})[c.charger_type] = c
    return lookup


def solve_gurobi(
    cfg: ProblemConfig,
    stage: str = "full_with_pv",
    time_limit_sec: float = 300.0,
    mip_gap: float = 0.01,
    verbose: bool = False,
) -> SolveResult:
    """
    Gurobi で MILP を解く。

    Parameters
    ----------
    cfg : ProblemConfig
        問題設定
    stage : str
        解くステージ (assignment_only, assignment_plus_soc,
                       assignment_soc_charging, full_with_pv)
    time_limit_sec : float
        ソルバー制限時間 [秒]
    mip_gap : float
        MIP ギャップ閾値
    verbose : bool
        Gurobi ログ出力

    Returns
    -------
    SolveResult
    """
    if not _GUROBI_AVAILABLE:
        return SolveResult(
            solver_name="gurobi",
            status="UNAVAILABLE",
            objective_value=None,
        )

    if stage not in VALID_STAGES:
        raise ValueError(f"Invalid stage: {stage}. Must be one of {VALID_STAGES}")

    # 補助パラメータが未計算なら計算
    if not cfg.trip_active:
        cfg = precompute_helpers(cfg)

    flags = _stage_flags(stage)
    T = list(range(cfg.num_periods))
    B = [b.bus_id for b in cfg.buses]
    R = [tr.trip_id for tr in cfg.trips]
    C = cfg.depots
    S = cfg.charger_types
    delta_h = cfg.delta_h
    charge_eff = cfg.charge_efficiency
    charger_lut = _charger_lookup(cfg.chargers)

    bus_lut = {b.bus_id: b for b in cfg.buses}
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}

    t_start = time.perf_counter()

    model = gp.Model(f"ebus_{stage}")
    model.Params.OutputFlag = 1 if verbose else 0
    model.Params.TimeLimit = time_limit_sec
    model.Params.MIPGap = mip_gap

    # ===== 変数 =====
    x = model.addVars(B, R, vtype=GRB.BINARY, name="x")

    soc = None
    if flags["soc"]:
        soc = model.addVars(
            B, range(cfg.num_periods + 1), lb=0.0,
            vtype=GRB.CONTINUOUS, name="soc",
        )

    y = None
    e = None
    if flags["charging"]:
        y = model.addVars(B, C, S, T, vtype=GRB.BINARY, name="y")
        e = model.addVars(B, C, S, T, lb=0.0, vtype=GRB.CONTINUOUS, name="e")

    pv_use = None
    grid_buy = None
    if flags["pv"]:
        pv_use = model.addVars(T, lb=0.0, vtype=GRB.CONTINUOUS, name="pv_use")
        grid_buy = model.addVars(T, lb=0.0, vtype=GRB.CONTINUOUS, name="grid_buy")
    elif flags["charging"]:
        grid_buy = model.addVars(T, lb=0.0, vtype=GRB.CONTINUOUS, name="grid_buy")

    # デマンドチャージ変数
    peak_demand = None
    if cfg.enable_demand_charge and flags["charging"]:
        peak_demand = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="peak_demand")

    # ===== 目的関数 =====
    if (flags["pv"] or flags["charging"]) and grid_buy is not None:
        prices = cfg.grid_price_yen_per_kwh
        obj = gp.quicksum(prices[t] * grid_buy[t] for t in T)
        if peak_demand is not None and cfg.contract_power_kw:
            # デマンドチャージペナルティ（簡易）
            obj += 1000.0 * peak_demand
        model.setObjective(obj, GRB.MINIMIZE)
    else:
        model.setObjective(0.0, GRB.MINIMIZE)

    # ===== 制約 =====
    # (1) 便の一意割当
    for r in R:
        model.addConstr(
            gp.quicksum(x[b, r] for b in B) == 1,
            name=f"assign_once[{r}]",
        )

    # (2) 重複便禁止
    for b in B:
        for r1, r2 in cfg.overlap_pairs:
            model.addConstr(
                x[b, r1] + x[b, r2] <= 1,
                name=f"overlap[{b},{r1},{r2}]",
            )

    # (3-6) SOC 関連
    if flags["soc"] and soc is not None:
        for b in B:
            bp = bus_lut[b]
            model.addConstr(
                soc[b, 0] == bp.soc_init_kwh,
                name=f"soc_init[{b}]",
            )
            for tt in range(cfg.num_periods + 1):
                model.addConstr(soc[b, tt] >= bp.soc_min_kwh, name=f"soc_lb[{b},{tt}]")
                model.addConstr(soc[b, tt] <= bp.soc_max_kwh, name=f"soc_ub[{b},{tt}]")

        # SOC 推移
        for b in B:
            for t in T:
                trip_use = gp.quicksum(
                    cfg.trip_energy_at_time[r][t] * x[b, r] for r in R
                )
                charge_in = 0.0
                if flags["charging"] and e is not None:
                    charge_in = gp.quicksum(
                        charge_eff * e[b, c, s, t] for c in C for s in S
                    )
                model.addConstr(
                    soc[b, t + 1] == soc[b, t] - trip_use + charge_in,
                    name=f"soc_balance[{b},{t}]",
                )

        # 終端 SOC 条件（オプション）
        if cfg.enable_terminal_soc and cfg.terminal_soc_kwh is not None:
            for b in B:
                model.addConstr(
                    soc[b, cfg.num_periods] >= cfg.terminal_soc_kwh,
                    name=f"terminal_soc[{b}]",
                )

    # (7-11) 充電関連
    if flags["charging"] and y is not None and e is not None:
        for b in B:
            for c in C:
                for s in S:
                    if c in charger_lut and s in charger_lut[c]:
                        power_kw = charger_lut[c][s].power_kw
                        max_e = power_kw * delta_h
                    else:
                        max_e = 0.0
                    for t in T:
                        model.addConstr(
                            e[b, c, s, t] <= max_e * y[b, c, s, t],
                            name=f"charge_link[{b},{c},{s},{t}]",
                        )

        # 充電器台数上限
        for c in C:
            for s in S:
                count = charger_lut.get(c, {}).get(s, None)
                if count is None:
                    cnt = 0
                else:
                    cnt = count.count
                for t in T:
                    model.addConstr(
                        gp.quicksum(y[b, c, s, t] for b in B) <= cnt,
                        name=f"charger_count[{c},{s},{t}]",
                    )

        # 同時多拠点充電禁止
        for b in B:
            for t in T:
                model.addConstr(
                    gp.quicksum(y[b, c, s, t] for c in C for s in S) <= 1,
                    name=f"one_charge_action[{b},{t}]",
                )

        # 運行中充電禁止
        for b in B:
            for t in T:
                run_expr = gp.quicksum(
                    cfg.trip_active[r][t] * x[b, r] for r in R
                )
                model.addConstr(
                    run_expr + gp.quicksum(y[b, c, s, t] for c in C for s in S) <= 1,
                    name=f"no_run_and_charge[{b},{t}]",
                )

        # 位置整合
        for b in B:
            for c in C:
                for s in S:
                    for t in T:
                        allowed = 1
                        if b in cfg.bus_can_charge_at and c in cfg.bus_can_charge_at[b]:
                            allowed = cfg.bus_can_charge_at[b][c][t]
                        model.addConstr(
                            y[b, c, s, t] <= allowed,
                            name=f"charge_allowed[{b},{c},{s},{t}]",
                        )

        # 電力収支
        for t in T:
            total_charge = gp.quicksum(
                e[b, c, s, t] for b in B for c in C for s in S
            )
            if flags["pv"] and pv_use is not None and grid_buy is not None:
                pv_cap = cfg.pv_gen_kwh[t] if t < len(cfg.pv_gen_kwh) else 0.0
                model.addConstr(pv_use[t] <= pv_cap, name=f"pv_cap[{t}]")
                model.addConstr(
                    total_charge == pv_use[t] + grid_buy[t],
                    name=f"power_balance[{t}]",
                )
            elif grid_buy is not None:
                model.addConstr(
                    total_charge == grid_buy[t],
                    name=f"power_balance_no_pv[{t}]",
                )

        # デマンドチャージ制約
        if peak_demand is not None and cfg.contract_power_kw and grid_buy is not None:
            for t in T:
                model.addConstr(
                    grid_buy[t] / delta_h <= peak_demand,
                    name=f"peak_track[{t}]",
                )
            model.addConstr(
                peak_demand <= cfg.contract_power_kw,
                name="contract_power_limit",
            )

    # ===== 求解 =====
    model.optimize()

    elapsed = time.perf_counter() - t_start

    # ===== 結果抽出 =====
    status_map = {
        1: "LOADED", 2: "OPTIMAL", 3: "INFEASIBLE", 4: "INF_OR_UNBD",
        5: "UNBOUNDED", 9: "TIME_LIMIT", 13: "SUBOPTIMAL",
    }
    status_text = status_map.get(model.Status, f"OTHER_{model.Status}")

    result = SolveResult(
        solver_name="gurobi",
        status=status_text,
        solve_time_sec=elapsed,
    )

    if model.SolCount == 0:
        return result

    result.objective_value = float(model.ObjVal)

    # 便割当
    for b in B:
        assigned = []
        for r in R:
            if x[b, r].X > 0.5:
                assigned.append(r)
        if assigned:
            result.assignment[b] = assigned

    # SOC
    if soc is not None:
        for b in B:
            result.soc_series[b] = [
                round(float(soc[b, t].X), 4)
                for t in range(cfg.num_periods + 1)
            ]

    # 充電スケジュール
    if y is not None:
        for b in B:
            sched: Dict[str, List[int]] = {}
            for c in C:
                for s in S:
                    key = f"{c}|{s}"
                    series = [int(round(y[b, c, s, t].X)) for t in T]
                    if any(series):
                        sched[key] = series
            if sched:
                result.charge_schedule[b] = sched

    if e is not None:
        for b in B:
            en: Dict[str, List[float]] = {}
            for c in C:
                for s in S:
                    key = f"{c}|{s}"
                    series = [round(float(e[b, c, s, t].X), 4) for t in T]
                    if any(abs(v) > 1e-9 for v in series):
                        en[key] = series
            if en:
                result.charge_energy[b] = en

    # PV / 買電
    if pv_use is not None:
        result.pv_use = {t: round(float(pv_use[t].X), 4) for t in T}
    if grid_buy is not None:
        result.grid_buy = {t: round(float(grid_buy[t].X), 4) for t in T}

    # KPI 計算
    _compute_kpis(cfg, result)

    return result


def _compute_kpis(cfg: ProblemConfig, result: SolveResult) -> None:
    """結果から KPI を計算"""
    prices = cfg.grid_price_yen_per_kwh

    # 買電コスト・量
    total_cost = 0.0
    total_grid = 0.0
    for t, val in result.grid_buy.items():
        total_grid += val
        if t < len(prices):
            total_cost += prices[t] * val
    result.total_grid_cost_yen = round(total_cost, 2)
    result.total_grid_kwh = round(total_grid, 4)

    # PV 利用量
    total_pv = sum(result.pv_use.values())
    result.total_pv_kwh = round(total_pv, 4)

    # 最低 SOC
    min_soc = float("inf")
    for b, series in result.soc_series.items():
        for v in series:
            if v < min_soc:
                min_soc = v
    result.min_soc_kwh = round(min_soc, 4) if min_soc < float("inf") else 0.0

    # 最大同時充電台数
    max_sim = 0
    if result.charge_schedule:
        for t in range(cfg.num_periods):
            cnt = 0
            for b, sched in result.charge_schedule.items():
                for key, series in sched.items():
                    if t < len(series) and series[t] > 0:
                        cnt += 1
            max_sim = max(max_sim, cnt)
    result.max_simultaneous_chargers = max_sim
