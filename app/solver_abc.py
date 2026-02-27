"""
solver_abc.py — 人工蜂コロニー (ABC) ソルバー

蜂の種類:
  - 雇用蜂 (Employed Bee):    各食料源の近傍を探索
  - 傍観蜂 (Onlooker Bee):    適応度に基づく確率で食料源を選択・近傍探索
  - 偵察蜂 (Scout Bee):       改善しない食料源を破棄しランダム生成

食料源（解）: trip_id -> bus_id のマッピング（AssignmentSolution）
適応度: evaluate_assignment() で内側LP/ヒューリスティック → 総コスト → fitness変換

主にALNS/Gurobi/GA との最適化コスト・計算時間の比較用。
"""
from __future__ import annotations

import copy
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .model_core import (
    ProblemConfig,
    SolveResult,
    precompute_helpers,
)
from .solver_alns import (
    AssignmentSolution,
    evaluate_assignment,
    generate_initial_solution,
)


# ---------------------------------------------------------------------------
# ABC パラメータ
# ---------------------------------------------------------------------------

@dataclass
class ABCParams:
    """人工蜂コロニーのハイパーパラメータ"""
    colony_size: int = 30          # 雇用蜂数 = 食料源数 (傍観蜂数も同数)
    max_iterations: int = 200      # 最大反復回数（サイクル数）
    max_no_improve: int = 50       # 改善なし上限
    limit: int = 20                # 食料源の改善なし上限 → 偵察蜂発動
    perturbation_size: int = 3     # 近傍探索で変更する便数
    seed: int = 42


# ---------------------------------------------------------------------------
# 食料源 (Food Source)
# ---------------------------------------------------------------------------

class FoodSource:
    """ABC の食料源: AssignmentSolution + cost + trial"""

    def __init__(
        self,
        solution: AssignmentSolution,
        cost: float = float("inf"),
        details: Optional[Dict[str, Any]] = None,
        trial: int = 0,
    ):
        self.solution = solution
        self.cost = cost
        self.details = details
        self.trial = trial  # 改善なし連続回数

    def copy(self) -> "FoodSource":
        return FoodSource(
            self.solution.copy(),
            self.cost,
            copy.deepcopy(self.details) if self.details else None,
            self.trial,
        )

    @property
    def fitness(self) -> float:
        """コストから適応度へ変換 (最小化 → 最大化)"""
        if self.cost >= 0:
            return 1.0 / (1.0 + self.cost)
        else:
            return 1.0 + abs(self.cost)


# ---------------------------------------------------------------------------
# 近傍生成: 便の再割り当て
# ---------------------------------------------------------------------------

def _generate_neighbor(
    source: FoodSource,
    other: FoodSource,
    cfg: ProblemConfig,
    perturbation_size: int,
    rng: random.Random,
) -> FoodSource:
    """
    食料源の近傍解を生成。
    ABC の標準的な更新: v_ij = x_ij + phi * (x_ij - x_kj)
    離散問題では、ランダムな便を other の対応バスまたは別バスに変更。
    """
    new_sol = source.solution.copy()
    trip_ids = list(new_sol.assignment.keys())
    bus_ids = [b.bus_id for b in cfg.buses]
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}

    n_change = min(perturbation_size, len(trip_ids))
    targets = rng.sample(trip_ids, n_change)

    for r in targets:
        tr = trip_lut[r]

        # 50%: other の割り当てを参考にする
        if rng.random() < 0.5 and r in other.solution.assignment:
            candidate_bus = other.solution.assignment[r]
        else:
            candidate_bus = rng.choice(bus_ids)

        # オーバーラップチェック
        conflict = False
        for ar in new_sol.get_trips_for_bus(candidate_bus):
            if ar == r:
                continue
            at = trip_lut[ar]
            if not (tr.end_t < at.start_t or at.end_t < tr.start_t):
                conflict = True
                break

        if not conflict:
            new_sol.assignment[r] = candidate_bus
        else:
            # フォールバック: 衝突しないバスを探す
            candidates = []
            for b_id in bus_ids:
                ok = True
                for ar in new_sol.get_trips_for_bus(b_id):
                    if ar == r:
                        continue
                    at = trip_lut[ar]
                    if not (tr.end_t < at.start_t or at.end_t < tr.start_t):
                        ok = False
                        break
                if ok:
                    candidates.append(b_id)
            if candidates:
                new_sol.assignment[r] = rng.choice(candidates)

    return FoodSource(new_sol)


# ---------------------------------------------------------------------------
# ランダム食料源生成（偵察蜂用）
# ---------------------------------------------------------------------------

def _random_food_source(
    cfg: ProblemConfig,
    rng: random.Random,
) -> FoodSource:
    """ランダムな食料源を生成"""
    trip_ids = [tr.trip_id for tr in cfg.trips]
    bus_ids = [b.bus_id for b in cfg.buses]
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}

    assignment: Dict[str, str] = {}
    shuffled = list(trip_ids)
    rng.shuffle(shuffled)

    for r in shuffled:
        tr = trip_lut[r]
        candidates = []
        for b_id in bus_ids:
            conflict = False
            for ar, ab in assignment.items():
                if ab != b_id:
                    continue
                at = trip_lut[ar]
                if not (tr.end_t < at.start_t or at.end_t < tr.start_t):
                    conflict = True
                    break
            if not conflict:
                candidates.append(b_id)

        if candidates:
            assignment[r] = rng.choice(candidates)
        else:
            assignment[r] = rng.choice(bus_ids)

    return FoodSource(AssignmentSolution(assignment))


# ---------------------------------------------------------------------------
# 食料源の評価
# ---------------------------------------------------------------------------

def _evaluate_food_source(
    fs: FoodSource,
    cfg: ProblemConfig,
) -> FoodSource:
    """食料源のコストを評価"""
    cost, details = evaluate_assignment(fs.solution, cfg)
    fs.cost = cost
    fs.details = details
    return fs


# ---------------------------------------------------------------------------
# ABC メインループ
# ---------------------------------------------------------------------------

def solve_abc(
    cfg: ProblemConfig,
    params: Optional[ABCParams] = None,
    callback: Optional[Callable[[int, float, float], None]] = None,
) -> SolveResult:
    """
    人工蜂コロニーアルゴリズムで解く。

    Parameters
    ----------
    cfg : ProblemConfig
    params : ABCParams (省略時はデフォルト)
    callback : Optional[(cycle, current_best_cost, global_best_cost) -> None]

    Returns
    -------
    SolveResult
    """
    if params is None:
        params = ABCParams()

    if not cfg.trip_active:
        cfg = precompute_helpers(cfg)

    rng = random.Random(params.seed)
    t_start = time.perf_counter()

    SN = params.colony_size  # 食料源数

    # ---------- 初期食料源 ----------
    food_sources: List[FoodSource] = []

    # 1つ目: 貪欲法
    greedy_sol = generate_initial_solution(cfg, rng)
    food_sources.append(FoodSource(greedy_sol))

    for _ in range(SN - 1):
        food_sources.append(_random_food_source(cfg, rng))

    # 全食料源を評価
    for i in range(len(food_sources)):
        food_sources[i] = _evaluate_food_source(food_sources[i], cfg)

    # 最良解
    best_source = min(food_sources, key=lambda fs: fs.cost).copy()
    best_cost = best_source.cost
    no_improve_count = 0
    iteration_log: List[Dict[str, Any]] = []

    # ---------- サイクルループ ----------
    for cycle in range(1, params.max_iterations + 1):

        # ===== 雇用蜂フェーズ =====
        for i in range(SN):
            # ランダムに別の食料源を選択
            others = [j for j in range(SN) if j != i]
            k = rng.choice(others)

            neighbor = _generate_neighbor(
                food_sources[i], food_sources[k], cfg,
                params.perturbation_size, rng,
            )
            neighbor = _evaluate_food_source(neighbor, cfg)

            # 貪欲選択
            if neighbor.cost < food_sources[i].cost:
                food_sources[i] = neighbor
                food_sources[i].trial = 0
            else:
                food_sources[i].trial += 1

        # ===== 傍観蜂フェーズ =====
        # 適応度に基づく確率計算
        fitnesses = [fs.fitness for fs in food_sources]
        total_fitness = sum(fitnesses)
        if total_fitness > 0:
            probs = [f / total_fitness for f in fitnesses]
        else:
            probs = [1.0 / SN] * SN

        for _ in range(SN):
            # ルーレット選択
            r_val = rng.random()
            cum = 0.0
            selected = 0
            for j in range(SN):
                cum += probs[j]
                if cum >= r_val:
                    selected = j
                    break

            # 近傍探索
            others = [j for j in range(SN) if j != selected]
            k = rng.choice(others)

            neighbor = _generate_neighbor(
                food_sources[selected], food_sources[k], cfg,
                params.perturbation_size, rng,
            )
            neighbor = _evaluate_food_source(neighbor, cfg)

            if neighbor.cost < food_sources[selected].cost:
                food_sources[selected] = neighbor
                food_sources[selected].trial = 0
            else:
                food_sources[selected].trial += 1

        # ===== 偵察蜂フェーズ =====
        for i in range(SN):
            if food_sources[i].trial >= params.limit:
                food_sources[i] = _random_food_source(cfg, rng)
                food_sources[i] = _evaluate_food_source(food_sources[i], cfg)

        # ===== 最良解更新 =====
        cycle_best = min(food_sources, key=lambda fs: fs.cost)
        if cycle_best.cost < best_cost:
            best_source = cycle_best.copy()
            best_cost = best_source.cost
            no_improve_count = 0
        else:
            no_improve_count += 1

        # ログ
        avg_cost = sum(
            fs.cost for fs in food_sources if fs.cost < float("inf")
        )
        n_finite = sum(1 for fs in food_sources if fs.cost < float("inf"))
        avg_val = avg_cost / n_finite if n_finite > 0 else None

        log_entry = {
            "iteration": cycle,
            "current_cost": round(cycle_best.cost, 2) if cycle_best.cost < float("inf") else None,
            "best_cost": round(best_cost, 2) if best_cost < float("inf") else None,
            "avg_cost": round(avg_val, 2) if avg_val is not None else None,
            "scout_triggered": sum(1 for fs in food_sources if fs.trial == 0 and cycle > 1),
        }
        iteration_log.append(log_entry)

        if callback:
            callback(cycle, cycle_best.cost, best_cost)

        # 早期終了
        if no_improve_count >= params.max_no_improve:
            break

    elapsed = time.perf_counter() - t_start

    # ---------- 結果構築 ----------
    result = SolveResult(
        solver_name="abc",
        status="FEASIBLE" if best_cost < float("inf") else "INFEASIBLE",
        objective_value=round(best_cost, 2) if best_cost < float("inf") else None,
        solve_time_sec=round(elapsed, 3),
    )

    # 割当
    for b in [bus.bus_id for bus in cfg.buses]:
        trips = best_source.solution.get_trips_for_bus(b)
        if trips:
            result.assignment[b] = trips

    # 詳細情報
    if best_source.details:
        result.grid_buy = best_source.details.get("grid_buy", {})
        result.pv_use = best_source.details.get("pv_use", {})
        if "soc" in best_source.details:
            result.soc_series = best_source.details["soc"]
        if "charge_schedule" in best_source.details:
            result.charge_schedule = best_source.details["charge_schedule"]
        if "charge_energy" in best_source.details:
            result.charge_energy = best_source.details["charge_energy"]

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
