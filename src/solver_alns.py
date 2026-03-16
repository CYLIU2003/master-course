"""
solver_alns.py — ALNS (Adaptive Large Neighbourhood Search) ソルバー

新 src/ データ構造 (ProblemData / ModelSets / DerivedParams) に対応。

研究計画に沿った二段構え:
  外側: ALNS で便割当 (x) を探索
  内側: LP で充電量 / SOC / PV / 買電を最適化

agent.md §5.3 — ALNS は内側 LP を Gurobi で解く。Gurobi 無し時は scipy fallback。
"""
from __future__ import annotations

import copy
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .data_schema import ProblemData
from .milp_model import MILPResult
from .model_sets import ModelSets
from .parameter_builder import DerivedParams, get_grid_price

_GUROBI_AVAILABLE = False
try:
    import gurobipy as gp
    from gurobipy import GRB
    _GUROBI_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# ALNS パラメータ
# ---------------------------------------------------------------------------

@dataclass
class ALNSParams:
    """ALNS ハイパーパラメータ"""
    max_iterations: int = 500
    max_no_improve: int = 100
    init_temp: float = 1000.0
    cooling_rate: float = 0.995
    destroy_ratio_min: float = 0.1
    destroy_ratio_max: float = 0.4
    segment_length: int = 50
    score_best: float = 10.0
    score_better: float = 5.0
    score_accept: float = 2.0
    score_reject: float = 0.0
    decay_factor: float = 0.8
    seed: int = 42


# ---------------------------------------------------------------------------
# 便割当解の表現
# ---------------------------------------------------------------------------

class AssignmentSolution:
    """便割当解: task_id -> vehicle_id"""

    def __init__(self, assignment: Dict[str, str]):
        self.assignment = dict(assignment)

    def copy(self) -> "AssignmentSolution":
        return AssignmentSolution(dict(self.assignment))

    def get_tasks_for_vehicle(self, vehicle_id: str) -> List[str]:
        return [r for r, v in self.assignment.items() if v == vehicle_id]


# ---------------------------------------------------------------------------
# 破壊オペレータ
# ---------------------------------------------------------------------------

def destroy_random(
    sol: AssignmentSolution,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    ratio: float,
    rng: random.Random,
) -> Tuple[AssignmentSolution, List[str]]:
    """ランダムにタスクを未割当にする"""
    new_sol = sol.copy()
    tasks = list(new_sol.assignment.keys())
    n_remove = max(1, int(len(tasks) * ratio))
    removed = rng.sample(tasks, min(n_remove, len(tasks)))
    for r in removed:
        del new_sol.assignment[r]
    return new_sol, removed


def destroy_worst(
    sol: AssignmentSolution,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    ratio: float,
    rng: random.Random,
) -> Tuple[AssignmentSolution, List[str]]:
    """消費電力量の大きいタスクを優先的に除去"""
    new_sol = sol.copy()
    tasks_sorted = sorted(
        new_sol.assignment.keys(),
        key=lambda r: dp.task_energy_bev.get(r, 0.0),
        reverse=True,
    )
    n_remove = max(1, int(len(tasks_sorted) * ratio))
    removed = tasks_sorted[:n_remove]
    # ランダム性を少し追加
    if len(removed) > 1 and len(tasks_sorted) > len(removed):
        extra = rng.sample(
            [t for t in tasks_sorted if t not in removed],
            min(max(1, n_remove // 3), len(tasks_sorted) - len(removed)),
        )
        removed = removed[:max(1, len(removed) - len(extra))] + extra
    for r in removed:
        if r in new_sol.assignment:
            del new_sol.assignment[r]
    return new_sol, removed


def destroy_related(
    sol: AssignmentSolution,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    ratio: float,
    rng: random.Random,
) -> Tuple[AssignmentSolution, List[str]]:
    """同じ車両に割り当てられたタスクをまとめて除去"""
    new_sol = sol.copy()
    target_v = rng.choice(ms.K_ALL)
    v_tasks = new_sol.get_tasks_for_vehicle(target_v)
    if not v_tasks:
        return destroy_random(sol, data, ms, dp, ratio, rng)
    n_remove = max(1, int(len(list(new_sol.assignment.keys())) * ratio))
    removed = v_tasks[:n_remove]
    for r in removed:
        if r in new_sol.assignment:
            del new_sol.assignment[r]
    return new_sol, removed


# ---------------------------------------------------------------------------
# 修復オペレータ
# ---------------------------------------------------------------------------

def repair_greedy(
    sol: AssignmentSolution,
    removed: List[str],
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    rng: random.Random,
) -> AssignmentSolution:
    """貪欲法: 各未割当タスクをオーバーラップしない最も負荷の少ない車両に割当"""
    new_sol = sol.copy()
    removed_sorted = sorted(removed, key=lambda r: dp.task_lut[r].start_time_idx)

    for r in removed_sorted:
        task = dp.task_lut[r]
        best_v = None
        best_load = float("inf")

        for v_id in ms.K_ALL:
            # 車種チェック
            rvt = (task.required_vehicle_type or "").upper()
            veh = dp.vehicle_lut[v_id]
            if rvt and rvt != veh.vehicle_type:
                continue

            # 互換チェック
            if ms.vehicle_task_feasible.get(v_id) and task.task_id not in ms.vehicle_task_feasible[v_id]:
                continue

            # オーバーラップチェック
            conflict = False
            for assigned_r in new_sol.get_tasks_for_vehicle(v_id):
                at = dp.task_lut[assigned_r]
                if not (at.end_time_idx < task.start_time_idx or task.end_time_idx < at.start_time_idx):
                    conflict = True
                    break
            if conflict:
                continue

            load = sum(dp.task_energy_bev.get(ar, 0.0) for ar in new_sol.get_tasks_for_vehicle(v_id))
            if load < best_load:
                best_load = load
                best_v = v_id

        if best_v is not None:
            new_sol.assignment[r] = best_v
        else:
            new_sol.assignment[r] = rng.choice(ms.K_ALL)

    return new_sol


def repair_random(
    sol: AssignmentSolution,
    removed: List[str],
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    rng: random.Random,
) -> AssignmentSolution:
    """ランダム修復: オーバーラップしない候補からランダム選択"""
    new_sol = sol.copy()

    for r in removed:
        task = dp.task_lut[r]
        candidates = []
        for v_id in ms.K_ALL:
            rvt = (task.required_vehicle_type or "").upper()
            veh = dp.vehicle_lut[v_id]
            if rvt and rvt != veh.vehicle_type:
                continue
            conflict = False
            for assigned_r in new_sol.get_tasks_for_vehicle(v_id):
                at = dp.task_lut[assigned_r]
                if not (at.end_time_idx < task.start_time_idx or task.end_time_idx < at.start_time_idx):
                    conflict = True
                    break
            if not conflict:
                candidates.append(v_id)

        if candidates:
            new_sol.assignment[r] = rng.choice(candidates)
        else:
            new_sol.assignment[r] = rng.choice(ms.K_ALL)

    return new_sol


# ---------------------------------------------------------------------------
# 内側 LP/MILP (充電・PV・買電配分の最適化)
# ---------------------------------------------------------------------------

def evaluate_assignment(
    sol: AssignmentSolution,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    与えられたタスク割当のもとで、充電量・PV・買電を LP/MILP で最適化し、
    目的関数値（総コスト）を返す。

    実行不能は (inf, None)。
    """
    if _GUROBI_AVAILABLE:
        return _evaluate_with_gurobi(sol, data, ms, dp)
    else:
        return _evaluate_heuristic(sol, data, ms, dp)


def _evaluate_with_gurobi(
    sol: AssignmentSolution,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Gurobi で内側 LP を解く"""
    T = ms.T
    K_BEV = ms.K_BEV
    K_ALL = ms.K_ALL
    C = ms.C
    I_CHARGE = ms.I_CHARGE
    delta_h = data.delta_t_hour

    model = gp.Model("alns_inner")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = 30.0
    model.Params.Seed = 42 # P0: params スコープ外エラーの修正

    # ---------- 変数 ----------
    # SOC: BEV のみ, t=0..num_periods
    soc = model.addVars(K_BEV, range(data.num_periods + 1), lb=0.0, name="soc")

    # 充電バイナリ / 電力
    z_charge = model.addVars(K_BEV, C, T, vtype=GRB.BINARY, name="z_charge")
    p_charge = model.addVars(K_BEV, C, T, lb=0.0, name="p_charge")

    # 系統受電・PV
    p_grid = model.addVars(I_CHARGE, T, lb=0.0, name="p_grid")
    p_pv = None
    if data.enable_pv:
        p_pv = model.addVars(I_CHARGE, T, lb=0.0, name="p_pv")

    # ピーク需要
    peak = model.addVars(I_CHARGE, lb=0.0, name="peak")

    # ---------- 目的関数 ----------
    obj = gp.LinExpr()

    # 電力量料金
    for site_id in I_CHARGE:
        for t in T:
            price = get_grid_price(dp, site_id, t)
            obj += price * p_grid[site_id, t] * delta_h

    # 車両使用固定費
    for k in K_ALL:
        veh = dp.vehicle_lut[k]
        tasks_for_k = sol.get_tasks_for_vehicle(k)
        if tasks_for_k:
            obj += veh.fixed_use_cost

    # デマンド料金
    if data.enable_demand_charge:
        demand_rate = data.demand_charge_rate_per_kw # P0: demand_rate のハードコード修正
        for site_id in I_CHARGE:
            obj += demand_rate * peak[site_id]

    model.setObjective(obj, GRB.MINIMIZE)

    # ---------- 制約 ----------

    # SOC 初期値 / 上下限
    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        soc_init = veh.soc_init or 0.0
        soc_min = veh.soc_min or 0.0
        soc_max = veh.soc_max or (veh.battery_capacity or 999)
        model.addConstr(soc[k, 0] == soc_init, name=f"soc_init_{k}")
        for tt in range(data.num_periods + 1):
            model.addConstr(soc[k, tt] >= soc_min, name=f"soc_lb_{k}_{tt}")
            model.addConstr(soc[k, tt] <= soc_max, name=f"soc_ub_{k}_{tt}")

    # SOC 推移 (割当固定)
    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        eff = veh.charge_efficiency
        assigned_tasks = sol.get_tasks_for_vehicle(k)
        for t in T:
            # 走行消費
            drive_kwh = sum(
                dp.task_energy_per_slot.get(r, [0.0] * data.num_periods)[t]
                for r in assigned_tasks
            )
            # 充電
            charge_in = gp.quicksum(eff * p_charge[k, c, t] * delta_h for c in C)
            model.addConstr(
                soc[k, t + 1] == soc[k, t] - drive_kwh + charge_in,
                name=f"soc_trans_{k}_{t}",
            )

    # 充電電力上限 (Big-M)
    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        for c in C:
            charger = dp.charger_lut.get(c)
            if not charger:
                continue
            max_kw = min(charger.power_max_kw, veh.charge_power_max or 9999)
            for t in T:
                model.addConstr(
                    p_charge[k, c, t] <= max_kw * z_charge[k, c, t],
                    name=f"charge_ub_{k}_{c}_{t}",
                )

    # 充電器同時使用上限 (1 基 = 1 台)
    for c in C:
        for t in T:
            model.addConstr(
                gp.quicksum(z_charge[k, c, t] for k in K_BEV) <= 1,
                name=f"charger_cap_{c}_{t}",
            )

    # 各車両は同時に 1 充電器のみ
    for k in K_BEV:
        for t in T:
            model.addConstr(
                gp.quicksum(z_charge[k, c, t] for c in C) <= 1,
                name=f"one_charger_{k}_{t}",
            )

    # 運行中は充電禁止
    for k in K_BEV:
        assigned_tasks = sol.get_tasks_for_vehicle(k)
        for t in T:
            is_running = any(
                dp.task_active.get(r, [0] * data.num_periods)[t] > 0
                for r in assigned_tasks
            )
            if is_running:
                model.addConstr(
                    gp.quicksum(z_charge[k, c, t] for c in C) == 0,
                    name=f"no_charge_running_{k}_{t}",
                )

    # 電力収支: 各充電拠点
    for site_id in I_CHARGE:
        site_chargers = ms.C_at_site.get(site_id, [])
        for t in T:
            total_charge_kw = gp.quicksum(
                p_charge[k, c, t]
                for k in K_BEV
                for c in site_chargers
            )
            if data.enable_pv and p_pv is not None:
                from .parameter_builder import get_pv_gen as _gpv
                pv_cap = _gpv(dp, site_id, t)
                model.addConstr(p_pv[site_id, t] <= pv_cap,
                                name=f"pv_cap_{site_id}_{t}")
                model.addConstr(
                    total_charge_kw == p_pv[site_id, t] + p_grid[site_id, t],
                    name=f"power_bal_{site_id}_{t}",
                )
            else:
                model.addConstr(
                    total_charge_kw == p_grid[site_id, t],
                    name=f"power_bal_{site_id}_{t}",
                )

            # ピーク需要
            model.addConstr(
                peak[site_id] >= p_grid[site_id, t],
                name=f"peak_{site_id}_{t}",
            )

    # 系統受電上限
    for site_id in I_CHARGE:
        site = dp.site_lut.get(site_id)
        if site and site.grid_import_limit_kw < 9000:
            for t in T:
                model.addConstr(
                    p_grid[site_id, t] <= site.grid_import_limit_kw,
                    name=f"grid_lim_{site_id}_{t}",
                )

    model.optimize()

    if model.SolCount == 0:
        return float("inf"), None

    # ---------- 結果抽出 ----------
    details: Dict[str, Any] = {
        "objective": float(model.ObjVal),
    }

    # SOC 系列
    details["soc_series"] = {}
    for k in K_BEV:
        details["soc_series"][k] = [
            round(float(soc[k, t].X), 4) for t in range(data.num_periods + 1)
        ]

    # 系統受電
    details["grid_import_kw"] = {}
    for site_id in I_CHARGE:
        details["grid_import_kw"][site_id] = [
            round(float(p_grid[site_id, t].X), 4) for t in T
        ]

    # PV
    details["pv_used_kw"] = {}
    if p_pv is not None:
        for site_id in I_CHARGE:
            details["pv_used_kw"][site_id] = [
                round(float(p_pv[site_id, t].X), 4) for t in T
            ]

    # ピーク需要
    details["peak_demand_kw"] = {}
    for site_id in I_CHARGE:
        details["peak_demand_kw"][site_id] = round(float(peak[site_id].X), 4)

    # 充電スケジュール / 電力
    details["charge_schedule"] = {}
    details["charge_power_kw"] = {}
    for k in K_BEV:
        sched: Dict[str, List[int]] = {}
        power: Dict[str, List[float]] = {}
        for c in C:
            s_arr = [int(round(z_charge[k, c, t].X)) for t in T]
            p_arr = [round(float(p_charge[k, c, t].X), 4) for t in T]
            if any(s_arr):
                sched[c] = s_arr
            if any(abs(v) > 1e-9 for v in p_arr):
                power[c] = p_arr
        if sched:
            details["charge_schedule"][k] = sched
        if power:
            details["charge_power_kw"][k] = power

    return float(model.ObjVal), details


def _evaluate_heuristic(
    sol: AssignmentSolution,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """ソルバー無し環境用の簡易推定 (SOC シミュレーション + 買電コスト)"""
    T = ms.T
    K_BEV = ms.K_BEV
    delta_h = data.delta_t_hour

    total_cost = 0.0
    soc_series: Dict[str, List[float]] = {}

    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        soc_init = veh.soc_init or 0.0
        soc_min = veh.soc_min or 0.0
        soc = soc_init
        soc_arr = [soc]
        assigned = sol.get_tasks_for_vehicle(k)
        needed = 0.0

        for t in T:
            drive = sum(
                dp.task_energy_per_slot.get(r, [0.0] * data.num_periods)[t]
                for r in assigned
            )
            soc -= drive
            if soc < soc_min:
                shortfall = soc_min - soc + 10.0
                charge_kwh = shortfall / (veh.charge_efficiency or 0.95)
                needed += charge_kwh
                soc = soc_min + 10.0
            soc_arr.append(round(soc, 4))

        soc_series[k] = soc_arr

    # 車両使用固定費
    for k in ms.K_ALL:
        veh = dp.vehicle_lut[k]
        if sol.get_tasks_for_vehicle(k):
            total_cost += veh.fixed_use_cost

    # 簡易電力コスト
    for site_id in ms.I_CHARGE:
        for t in T:
            price = get_grid_price(dp, site_id, t)
            # 全充電必要量を均等分配 (概算)

    # 概算: 全タスクの消費量 × 平均料金
    total_energy = sum(dp.task_energy_bev.get(r, 0.0) for r in list(sol.assignment.keys()))
    avg_price = 25.0
    if ms.I_CHARGE and T:
        prices = [get_grid_price(dp, ms.I_CHARGE[0], t) for t in T]
        avg_price = sum(prices) / len(prices) if prices else 25.0
    total_cost += total_energy * avg_price

    details = {
        "objective": round(total_cost, 2),
        "soc_series": soc_series,
    }
    return total_cost, details


# ---------------------------------------------------------------------------
# 初期解生成
# ---------------------------------------------------------------------------

def generate_initial_solution(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    rng: random.Random,
) -> AssignmentSolution:
    """貪欲法で初期解を生成: タスク→車両"""
    assignment: Dict[str, str] = {}
    sorted_tasks = sorted(data.tasks, key=lambda t: t.start_time_idx)

    for task in sorted_tasks:
        candidates = []
        for v_id in ms.K_ALL:
            rvt = (task.required_vehicle_type or "").upper()
            veh = dp.vehicle_lut[v_id]
            if rvt and rvt != veh.vehicle_type:
                continue
            if ms.vehicle_task_feasible.get(v_id) and task.task_id not in ms.vehicle_task_feasible[v_id]:
                continue

            conflict = False
            for assigned_r, assigned_v in assignment.items():
                if assigned_v != v_id:
                    continue
                at = dp.task_lut[assigned_r]
                if not (at.end_time_idx < task.start_time_idx or task.end_time_idx < at.start_time_idx):
                    conflict = True
                    break
            if not conflict:
                candidates.append(v_id)

        if candidates:
            loads = [
                (sum(dp.task_energy_bev.get(r, 0.0) for r, v in assignment.items() if v == c), c)
                for c in candidates
            ]
            loads.sort()
            assignment[task.task_id] = loads[0][1]
        else:
            assignment[task.task_id] = rng.choice(ms.K_ALL)

    return AssignmentSolution(assignment)


# ---------------------------------------------------------------------------
# AssignmentSolution → MILPResult 変換
# ---------------------------------------------------------------------------

def _to_milp_result(
    sol: AssignmentSolution,
    details: Optional[Dict[str, Any]],
    ms: ModelSets,
    dp: DerivedParams,
    solve_time: float,
    iteration_log: List[Dict[str, Any]],
) -> MILPResult:
    """ALNS 結果を MILPResult に変換"""
    cost = details["objective"] if details else float("inf")
    status = "FEASIBLE" if cost < float("inf") else "INFEASIBLE"

    result = MILPResult(
        status=status,
        objective_value=round(cost, 2) if cost < float("inf") else None,
        solve_time_sec=round(solve_time, 3),
    )

    # 割当 (vehicle_id -> [task_id, ...])
    for v_id in ms.K_ALL:
        tasks = sol.get_tasks_for_vehicle(v_id)
        if tasks:
            result.assignment[v_id] = tasks

    # 未割当タスク
    assigned = set(sol.assignment.keys())
    for r in ms.R:
        if r not in assigned:
            result.unserved_tasks.append(r)

    if details:
        result.soc_series = details.get("soc_series", {})
        result.charge_schedule = details.get("charge_schedule", {})
        result.charge_power_kw = details.get("charge_power_kw", {})
        result.grid_import_kw = details.get("grid_import_kw", {})
        result.pv_used_kw = details.get("pv_used_kw", {})
        result.peak_demand_kw = details.get("peak_demand_kw", {})

    return result


# ---------------------------------------------------------------------------
# ALNS メインループ
# ---------------------------------------------------------------------------

def solve_alns(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    params: Optional[ALNSParams] = None,
    callback: Optional[Callable[[int, float, float], None]] = None,
) -> MILPResult:
    """
    ALNS で解く。

    Parameters
    ----------
    data    : ProblemData
    ms      : ModelSets
    dp      : DerivedParams
    params  : ALNSParams (省略時はデフォルト)
    callback: Optional[(iteration, current_cost, best_cost) -> None]

    Returns
    -------
    MILPResult
    """
    if params is None:
        params = ALNSParams()

    random.seed(params.seed)
    rng = random.Random(params.seed)
    t_start = time.perf_counter()

    # オペレータ登録
    destroy_ops = [destroy_random, destroy_worst, destroy_related]
    repair_ops = [repair_greedy, repair_random]

    n_destroy = len(destroy_ops)
    n_repair = len(repair_ops)
    weights_d = [1.0] * n_destroy
    weights_r = [1.0] * n_repair
    scores_d = [0.0] * n_destroy
    scores_r = [0.0] * n_repair
    usage_d = [0] * n_destroy
    usage_r = [0] * n_repair

    # 初期解
    current_sol = generate_initial_solution(data, ms, dp, rng)
    current_cost, current_details = evaluate_assignment(current_sol, data, ms, dp)
    best_sol = current_sol.copy()
    best_cost = current_cost
    best_details = current_details

    temp = params.init_temp
    no_improve_count = 0
    iteration_log: List[Dict[str, Any]] = []

    for iteration in range(1, params.max_iterations + 1):
        ratio = rng.uniform(params.destroy_ratio_min, params.destroy_ratio_max)

        # ルーレットでオペレータ選択
        d_idx = _roulette_select(weights_d, rng)
        r_idx = _roulette_select(weights_r, rng)

        # 破壊
        partial_sol, removed = destroy_ops[d_idx](
            current_sol, data, ms, dp, ratio, rng
        )

        # 修復
        new_sol = repair_ops[r_idx](
            partial_sol, removed, data, ms, dp, rng
        )

        # 評価
        new_cost, new_details = evaluate_assignment(new_sol, data, ms, dp)

        # 受理判定 (SA)
        accepted = False
        score_type = "reject"

        if new_cost < best_cost:
            best_sol = new_sol.copy()
            best_cost = new_cost
            best_details = new_details
            current_sol = new_sol
            current_cost = new_cost
            accepted = True
            score_type = "best"
            no_improve_count = 0
        elif new_cost < current_cost:
            current_sol = new_sol
            current_cost = new_cost
            accepted = True
            score_type = "better"
            no_improve_count = 0
        else:
            delta = new_cost - current_cost
            if temp > 0 and delta < float("inf"):
                prob = math.exp(-delta / max(temp, 1e-10))
                if rng.random() < prob:
                    current_sol = new_sol
                    current_cost = new_cost
                    accepted = True
                    score_type = "accept"
            no_improve_count += 1

        # スコア更新
        score_map = {
            "best": params.score_best,
            "better": params.score_better,
            "accept": params.score_accept,
            "reject": params.score_reject,
        }
        scores_d[d_idx] += score_map[score_type]
        scores_r[r_idx] += score_map[score_type]
        usage_d[d_idx] += 1
        usage_r[r_idx] += 1

        # セグメント更新
        if iteration % params.segment_length == 0:
            for i in range(n_destroy):
                if usage_d[i] > 0:
                    weights_d[i] = (
                        params.decay_factor * weights_d[i]
                        + (1 - params.decay_factor) * scores_d[i] / usage_d[i]
                    )
                scores_d[i] = 0.0
                usage_d[i] = 0
            for i in range(n_repair):
                if usage_r[i] > 0:
                    weights_r[i] = (
                        params.decay_factor * weights_r[i]
                        + (1 - params.decay_factor) * scores_r[i] / usage_r[i]
                    )
                scores_r[i] = 0.0
                usage_r[i] = 0

        # 温度減衰
        temp *= params.cooling_rate

        # ログ
        log_entry = {
            "iteration": iteration,
            "current_cost": round(current_cost, 2) if current_cost < float("inf") else None,
            "best_cost": round(best_cost, 2) if best_cost < float("inf") else None,
            "temperature": round(temp, 2),
            "accepted": accepted,
            "destroy_op": d_idx,
            "repair_op": r_idx,
        }
        iteration_log.append(log_entry)

        if callback:
            callback(iteration, current_cost, best_cost)

        # 早期終了
        if no_improve_count >= params.max_no_improve:
            break

    elapsed = time.perf_counter() - t_start

    return _to_milp_result(best_sol, best_details, ms, dp, elapsed, iteration_log)


def _roulette_select(weights: List[float], rng: random.Random) -> int:
    """重み付きルーレット選択"""
    total = sum(max(w, 0.01) for w in weights)
    r = rng.uniform(0, total)
    cum = 0.0
    for i, w in enumerate(weights):
        cum += max(w, 0.01)
        if cum >= r:
            return i
    return len(weights) - 1
