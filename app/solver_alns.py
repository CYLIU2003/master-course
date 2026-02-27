"""
solver_alns.py — ALNS (Adaptive Large Neighbourhood Search) ソルバー

研究計画に沿った二段構え:
- 外側: ALNS で便割当 (x) を探索
- 内側: LP で充電量 / SOC / PV / 買電を最適化

Gurobi が無い環境でも内側を簡易 LP (scipy) で代替可能。
"""
from __future__ import annotations

import copy
import math
import random
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .model_core import (
    ProblemConfig,
    SolveResult,
    precompute_helpers,
)

# scipy は ALNS 内側 LP のフォールバック用
_SCIPY_AVAILABLE = False
try:
    from scipy.optimize import linprog
    _SCIPY_AVAILABLE = True
except ImportError:
    pass

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

class ALNSParams:
    """ALNS ハイパーパラメータ"""

    def __init__(
        self,
        max_iterations: int = 500,
        max_no_improve: int = 100,
        init_temp: float = 1000.0,
        cooling_rate: float = 0.995,
        destroy_ratio_min: float = 0.1,
        destroy_ratio_max: float = 0.4,
        segment_length: int = 50,
        score_best: float = 10.0,
        score_better: float = 5.0,
        score_accept: float = 2.0,
        score_reject: float = 0.0,
        decay_factor: float = 0.8,
        seed: int = 42,
    ):
        self.max_iterations = max_iterations
        self.max_no_improve = max_no_improve
        self.init_temp = init_temp
        self.cooling_rate = cooling_rate
        self.destroy_ratio_min = destroy_ratio_min
        self.destroy_ratio_max = destroy_ratio_max
        self.segment_length = segment_length
        self.score_best = score_best
        self.score_better = score_better
        self.score_accept = score_accept
        self.score_reject = score_reject
        self.decay_factor = decay_factor
        self.seed = seed


# ---------------------------------------------------------------------------
# 便割当解の表現
# ---------------------------------------------------------------------------

class AssignmentSolution:
    """便割当解: trip_id -> bus_id"""

    def __init__(self, assignment: Dict[str, str]):
        self.assignment = dict(assignment)  # trip_id -> bus_id

    def copy(self) -> "AssignmentSolution":
        return AssignmentSolution(dict(self.assignment))

    def get_trips_for_bus(self, bus_id: str) -> List[str]:
        return [r for r, b in self.assignment.items() if b == bus_id]


# ---------------------------------------------------------------------------
# 破壊オペレータ
# ---------------------------------------------------------------------------

def destroy_random(
    sol: AssignmentSolution,
    cfg: ProblemConfig,
    ratio: float,
    rng: random.Random,
) -> Tuple[AssignmentSolution, List[str]]:
    """ランダムに便を未割当にする"""
    new_sol = sol.copy()
    trips = list(new_sol.assignment.keys())
    n_remove = max(1, int(len(trips) * ratio))
    removed = rng.sample(trips, min(n_remove, len(trips)))
    for r in removed:
        del new_sol.assignment[r]
    return new_sol, removed


def destroy_worst(
    sol: AssignmentSolution,
    cfg: ProblemConfig,
    ratio: float,
    rng: random.Random,
) -> Tuple[AssignmentSolution, List[str]]:
    """消費電力量の大きい便を優先的に除去"""
    new_sol = sol.copy()
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}
    trips_sorted = sorted(
        new_sol.assignment.keys(),
        key=lambda r: trip_lut[r].energy_kwh,
        reverse=True,
    )
    n_remove = max(1, int(len(trips_sorted) * ratio))
    removed = trips_sorted[:n_remove]
    # 少しランダム性を加える
    if len(removed) > 1:
        extra = rng.sample(
            [t for t in trips_sorted if t not in removed],
            min(max(1, n_remove // 3), len(trips_sorted) - len(removed)),
        ) if len(trips_sorted) > len(removed) else []
        removed = removed[:max(1, len(removed) - len(extra))] + extra
    for r in removed:
        if r in new_sol.assignment:
            del new_sol.assignment[r]
    return new_sol, removed


def destroy_related(
    sol: AssignmentSolution,
    cfg: ProblemConfig,
    ratio: float,
    rng: random.Random,
) -> Tuple[AssignmentSolution, List[str]]:
    """同じバスに割り当てられた便をまとめて除去"""
    new_sol = sol.copy()
    buses = [b.bus_id for b in cfg.buses]
    target_bus = rng.choice(buses)
    bus_trips = new_sol.get_trips_for_bus(target_bus)
    if not bus_trips:
        # フォールバック: ランダム
        return destroy_random(sol, cfg, ratio, rng)
    n_remove = max(1, int(len(list(new_sol.assignment.keys())) * ratio))
    removed = bus_trips[:n_remove]
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
    cfg: ProblemConfig,
    rng: random.Random,
) -> AssignmentSolution:
    """貪欲法: 各未割当便をオーバーラップしない最も負荷の少ないバスに割り当て"""
    new_sol = sol.copy()
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}
    bus_ids = [b.bus_id for b in cfg.buses]

    # 便を開始時刻順にソート
    removed_sorted = sorted(removed, key=lambda r: trip_lut[r].start_t)

    for r in removed_sorted:
        tr = trip_lut[r]
        best_bus = None
        best_load = float("inf")

        for b_id in bus_ids:
            # オーバーラップチェック
            conflict = False
            for assigned_r in new_sol.get_trips_for_bus(b_id):
                at = trip_lut[assigned_r]
                if not (tr.end_t < at.start_t or at.end_t < tr.start_t):
                    conflict = True
                    break
            if conflict:
                continue

            # そのバスの現在の負荷
            load = sum(
                trip_lut[ar].energy_kwh
                for ar in new_sol.get_trips_for_bus(b_id)
            )
            if load < best_load:
                best_load = load
                best_bus = b_id

        if best_bus is not None:
            new_sol.assignment[r] = best_bus
        else:
            # 割り当て先がない場合、ランダム選択（実行不能を許容）
            new_sol.assignment[r] = rng.choice(bus_ids)

    return new_sol


def repair_random(
    sol: AssignmentSolution,
    removed: List[str],
    cfg: ProblemConfig,
    rng: random.Random,
) -> AssignmentSolution:
    """ランダム修復: オーバーラップしない候補からランダム選択"""
    new_sol = sol.copy()
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}
    bus_ids = [b.bus_id for b in cfg.buses]

    for r in removed:
        tr = trip_lut[r]
        candidates = []
        for b_id in bus_ids:
            conflict = False
            for assigned_r in new_sol.get_trips_for_bus(b_id):
                at = trip_lut[assigned_r]
                if not (tr.end_t < at.start_t or at.end_t < tr.start_t):
                    conflict = True
                    break
            if not conflict:
                candidates.append(b_id)

        if candidates:
            new_sol.assignment[r] = rng.choice(candidates)
        else:
            new_sol.assignment[r] = rng.choice(bus_ids)

    return new_sol


# ---------------------------------------------------------------------------
# 内側 LP/MILP (充電・PV・買電配分の最適化)
# ---------------------------------------------------------------------------

def evaluate_assignment(
    sol: AssignmentSolution,
    cfg: ProblemConfig,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    与えられた便割当のもとで、充電量・PV・買電をLP/MILPで最適化し、
    目的関数値（総コスト）を返す。

    実行不能の場合は (inf, None) を返す。
    """
    if _GUROBI_AVAILABLE:
        return _evaluate_with_gurobi(sol, cfg)
    elif _SCIPY_AVAILABLE:
        return _evaluate_with_scipy(sol, cfg)
    else:
        return _evaluate_heuristic(sol, cfg)


def _evaluate_with_gurobi(
    sol: AssignmentSolution,
    cfg: ProblemConfig,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Gurobi で内側 LP を解く"""
    T = list(range(cfg.num_periods))
    B = [b.bus_id for b in cfg.buses]
    R = [tr.trip_id for tr in cfg.trips]
    C = cfg.depots
    S = cfg.charger_types
    delta_h = cfg.delta_h
    charge_eff = cfg.charge_efficiency

    bus_lut = {b.bus_id: b for b in cfg.buses}
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}

    from .solver_gurobi import _charger_lookup
    charger_lut = _charger_lookup(cfg.chargers)

    model = gp.Model("alns_inner")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = 30.0

    # 変数
    soc = model.addVars(B, range(cfg.num_periods + 1), lb=0.0, name="soc")
    y = model.addVars(B, C, S, T, vtype=GRB.BINARY, name="y")
    e = model.addVars(B, C, S, T, lb=0.0, name="e")

    if cfg.enable_pv:
        pv_use = model.addVars(T, lb=0.0, name="pv_use")
        grid_buy = model.addVars(T, lb=0.0, name="grid_buy")
    else:
        pv_use = None
        grid_buy = model.addVars(T, lb=0.0, name="grid_buy")

    # 目的関数
    prices = cfg.grid_price_yen_per_kwh
    model.setObjective(
        gp.quicksum(prices[t] * grid_buy[t] for t in T),
        GRB.MINIMIZE,
    )

    # SOC 制約
    for b in B:
        bp = bus_lut[b]
        model.addConstr(soc[b, 0] == bp.soc_init_kwh)
        for tt in range(cfg.num_periods + 1):
            model.addConstr(soc[b, tt] >= bp.soc_min_kwh)
            model.addConstr(soc[b, tt] <= bp.soc_max_kwh)

    # SOC 推移（x は固定）
    for b in B:
        for t in T:
            drive = sum(
                cfg.trip_energy_at_time[r][t]
                for r in R
                if sol.assignment.get(r) == b
            )
            charge_in = gp.quicksum(charge_eff * e[b, c, s, t] for c in C for s in S)
            model.addConstr(soc[b, t + 1] == soc[b, t] - drive + charge_in)

    # 充電系制約
    for b in B:
        for c in C:
            for s in S:
                power_kw = charger_lut.get(c, {}).get(s, None)
                max_e = (power_kw.power_kw * delta_h) if power_kw else 0.0
                for t in T:
                    model.addConstr(e[b, c, s, t] <= max_e * y[b, c, s, t])

    for c in C:
        for s in S:
            cnt_spec = charger_lut.get(c, {}).get(s, None)
            cnt = cnt_spec.count if cnt_spec else 0
            for t in T:
                model.addConstr(gp.quicksum(y[b, c, s, t] for b in B) <= cnt)

    for b in B:
        for t in T:
            model.addConstr(
                gp.quicksum(y[b, c, s, t] for c in C for s in S) <= 1
            )

    # 運行中充電禁止
    for b in B:
        for t in T:
            running = sum(
                cfg.trip_active[r][t]
                for r in R
                if sol.assignment.get(r) == b
            )
            if running > 0:
                model.addConstr(
                    gp.quicksum(y[b, c, s, t] for c in C for s in S) == 0
                )

    # 電力収支
    for t in T:
        total_charge = gp.quicksum(e[b, c, s, t] for b in B for c in C for s in S)
        if cfg.enable_pv and pv_use is not None:
            pv_cap = cfg.pv_gen_kwh[t] if t < len(cfg.pv_gen_kwh) else 0.0
            model.addConstr(pv_use[t] <= pv_cap)
            model.addConstr(total_charge == pv_use[t] + grid_buy[t])
        else:
            model.addConstr(total_charge == grid_buy[t])

    model.optimize()

    if model.SolCount == 0:
        return float("inf"), None

    details = {
        "objective": float(model.ObjVal),
        "soc": {
            b: [round(float(soc[b, t].X), 4) for t in range(cfg.num_periods + 1)]
            for b in B
        },
        "grid_buy": {t: round(float(grid_buy[t].X), 4) for t in T},
        "pv_use": (
            {t: round(float(pv_use[t].X), 4) for t in T}
            if pv_use is not None
            else {}
        ),
        "charge_schedule": {},
        "charge_energy": {},
    }

    for b in B:
        sched: Dict[str, List[int]] = {}
        en: Dict[str, List[float]] = {}
        for c in C:
            for s in S:
                key = f"{c}|{s}"
                s_arr = [int(round(y[b, c, s, t].X)) for t in T]
                e_arr = [round(float(e[b, c, s, t].X), 4) for t in T]
                if any(s_arr):
                    sched[key] = s_arr
                if any(abs(v) > 1e-9 for v in e_arr):
                    en[key] = e_arr
        if sched:
            details["charge_schedule"][b] = sched
        if en:
            details["charge_energy"][b] = en

    return float(model.ObjVal), details


def _evaluate_with_scipy(
    sol: AssignmentSolution,
    cfg: ProblemConfig,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """scipy.linprog を使った簡易 LP (充電を連続緩和して近似)"""
    # 簡易実装: 各時刻に必要な充電量を計算し、PV で賄えない分を買電
    T = list(range(cfg.num_periods))
    B = [b.bus_id for b in cfg.buses]
    R = [tr.trip_id for tr in cfg.trips]
    bus_lut = {b.bus_id: b for b in cfg.buses}
    prices = cfg.grid_price_yen_per_kwh

    # 各バスの各時刻の消費量を計算
    bus_demand = {b: [0.0] * cfg.num_periods for b in B}
    for r in R:
        b = sol.assignment.get(r)
        if b and b in bus_demand:
            for t in T:
                bus_demand[b][t] += cfg.trip_energy_at_time[r][t]

    # 全バスのSOCシミュレーション（必要充電量を推定）
    total_needed = [0.0] * cfg.num_periods
    for b in B:
        bp = bus_lut[b]
        soc = bp.soc_init_kwh
        for t in T:
            soc -= bus_demand[b][t]
            if soc < bp.soc_min_kwh:
                needed = bp.soc_min_kwh - soc + 10.0  # 余裕
                total_needed[t] += needed / cfg.charge_efficiency
                soc = bp.soc_min_kwh + 10.0

    # PV/買電 配分
    total_cost = 0.0
    grid_buy_result = {}
    pv_use_result = {}
    for t in T:
        pv_cap = cfg.pv_gen_kwh[t] if cfg.enable_pv and t < len(cfg.pv_gen_kwh) else 0.0
        pv = min(pv_cap, total_needed[t])
        grid = max(0.0, total_needed[t] - pv)
        grid_buy_result[t] = round(grid, 4)
        pv_use_result[t] = round(pv, 4)
        if t < len(prices):
            total_cost += prices[t] * grid

    details = {
        "objective": round(total_cost, 2),
        "grid_buy": grid_buy_result,
        "pv_use": pv_use_result,
    }

    return total_cost, details


def _evaluate_heuristic(
    sol: AssignmentSolution,
    cfg: ProblemConfig,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """ソルバー無し環境用の簡易ヒューリスティック"""
    return _evaluate_with_scipy(sol, cfg) if _SCIPY_AVAILABLE else (float("inf"), None)


# ---------------------------------------------------------------------------
# 初期解生成
# ---------------------------------------------------------------------------

def generate_initial_solution(
    cfg: ProblemConfig,
    rng: random.Random,
) -> AssignmentSolution:
    """貪欲法で初期解を生成"""
    assignment: Dict[str, str] = {}
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}
    bus_ids = [b.bus_id for b in cfg.buses]

    sorted_trips = sorted(cfg.trips, key=lambda tr: tr.start_t)

    for tr in sorted_trips:
        candidates = []
        for b_id in bus_ids:
            conflict = False
            for assigned_r, assigned_b in assignment.items():
                if assigned_b != b_id:
                    continue
                at = trip_lut[assigned_r]
                if not (tr.end_t < at.start_t or at.end_t < tr.start_t):
                    conflict = True
                    break
            if not conflict:
                candidates.append(b_id)

        if candidates:
            # 負荷均等化
            loads = []
            for c in candidates:
                load = sum(
                    trip_lut[ar].energy_kwh
                    for ar, ab in assignment.items()
                    if ab == c
                )
                loads.append((load, c))
            loads.sort()
            assignment[tr.trip_id] = loads[0][1]
        else:
            assignment[tr.trip_id] = rng.choice(bus_ids)

    return AssignmentSolution(assignment)


# ---------------------------------------------------------------------------
# ALNS メインループ
# ---------------------------------------------------------------------------

def solve_alns(
    cfg: ProblemConfig,
    params: Optional[ALNSParams] = None,
    callback: Optional[Callable[[int, float, float], None]] = None,
) -> SolveResult:
    """
    ALNS で解く。

    Parameters
    ----------
    cfg : ProblemConfig
    params : ALNSParams (省略時はデフォルト)
    callback : Optional[(iteration, current_cost, best_cost) -> None]

    Returns
    -------
    SolveResult
    """
    if params is None:
        params = ALNSParams()

    if not cfg.trip_active:
        cfg = precompute_helpers(cfg)

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
    current_sol = generate_initial_solution(cfg, rng)
    current_cost, current_details = evaluate_assignment(current_sol, cfg)
    best_sol = current_sol.copy()
    best_cost = current_cost
    best_details = current_details

    temp = params.init_temp
    no_improve_count = 0
    iteration_log: List[Dict[str, Any]] = []

    for iteration in range(1, params.max_iterations + 1):
        # 破壊率
        ratio = rng.uniform(params.destroy_ratio_min, params.destroy_ratio_max)

        # ルーレットでオペレータ選択
        d_idx = _roulette_select(weights_d, rng)
        r_idx = _roulette_select(weights_r, rng)

        # 破壊
        partial_sol, removed = destroy_ops[d_idx](current_sol, cfg, ratio, rng)

        # 修復
        new_sol = repair_ops[r_idx](partial_sol, removed, cfg, rng)

        # 評価
        new_cost, new_details = evaluate_assignment(new_sol, cfg)

        # 受理判定
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
            # シミュレーテッドアニーリング受理
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

    # 結果構築
    result = SolveResult(
        solver_name="alns",
        status="FEASIBLE" if best_cost < float("inf") else "INFEASIBLE",
        objective_value=round(best_cost, 2) if best_cost < float("inf") else None,
        solve_time_sec=round(elapsed, 3),
    )

    # 割当
    for b in [bus.bus_id for bus in cfg.buses]:
        trips = best_sol.get_trips_for_bus(b)
        if trips:
            result.assignment[b] = trips

    # 詳細情報
    if best_details:
        result.grid_buy = best_details.get("grid_buy", {})
        result.pv_use = best_details.get("pv_use", {})

        if "soc" in best_details:
            result.soc_series = best_details["soc"]
        if "charge_schedule" in best_details:
            result.charge_schedule = best_details["charge_schedule"]
        if "charge_energy" in best_details:
            result.charge_energy = best_details["charge_energy"]

    # KPI
    prices = cfg.grid_price_yen_per_kwh
    total_cost = 0.0
    total_grid = 0.0
    for t, val in result.grid_buy.items():
        total_grid += val
        if isinstance(t, int) and t < len(prices):
            total_cost += prices[t] * val
    result.total_grid_cost_yen = round(total_cost, 2)
    result.total_grid_kwh = round(total_grid, 4)
    result.total_pv_kwh = round(sum(result.pv_use.values()), 4)

    result.iteration_log = iteration_log

    return result


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
