"""
solver_ga.py — 遺伝的アルゴリズム (GA) ソルバー

染色体表現: trip_id -> bus_id のマッピング（ALNSと同じAssignmentSolution）
適応度: evaluate_assignment() で内側LP/ヒューリスティックを解いて総コスト算出

主にALNS/Gurobi との最適化コスト・計算時間の比較用。
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
# GA パラメータ
# ---------------------------------------------------------------------------

@dataclass
class GAParams:
    """遺伝的アルゴリズムのハイパーパラメータ"""
    population_size: int = 30
    max_generations: int = 200
    max_no_improve: int = 50
    crossover_rate: float = 0.85
    mutation_rate: float = 0.15
    tournament_size: int = 3
    elitism_count: int = 2
    seed: int = 42


# ---------------------------------------------------------------------------
# GA 個体（染色体）
# ---------------------------------------------------------------------------

class Individual:
    """GA の個体: AssignmentSolution + fitness"""

    def __init__(self, solution: AssignmentSolution, fitness: float = float("inf"),
                 details: Optional[Dict[str, Any]] = None):
        self.solution = solution
        self.fitness = fitness
        self.details = details

    def copy(self) -> "Individual":
        return Individual(
            self.solution.copy(),
            self.fitness,
            copy.deepcopy(self.details) if self.details else None,
        )


# ---------------------------------------------------------------------------
# 初期集団生成
# ---------------------------------------------------------------------------

def _generate_population(
    cfg: ProblemConfig,
    pop_size: int,
    rng: random.Random,
) -> List[Individual]:
    """多様な初期集団を生成"""
    population: List[Individual] = []

    # 1つ目: 貪欲法
    greedy_sol = generate_initial_solution(cfg, rng)
    population.append(Individual(greedy_sol))

    trip_ids = [tr.trip_id for tr in cfg.trips]
    bus_ids = [b.bus_id for b in cfg.buses]
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}

    for _ in range(pop_size - 1):
        assignment: Dict[str, str] = {}
        # ランダム可能割り当て（オーバーラップ回避を試行）
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
        population.append(Individual(AssignmentSolution(assignment)))

    return population


# ---------------------------------------------------------------------------
# 選択: トーナメント選択
# ---------------------------------------------------------------------------

def _tournament_select(
    population: List[Individual],
    tournament_size: int,
    rng: random.Random,
) -> Individual:
    """トーナメント選択"""
    candidates = rng.sample(population, min(tournament_size, len(population)))
    return min(candidates, key=lambda ind: ind.fitness)


# ---------------------------------------------------------------------------
# 交叉: 一様交叉（便ごと）
# ---------------------------------------------------------------------------

def _crossover(
    parent1: Individual,
    parent2: Individual,
    cfg: ProblemConfig,
    rng: random.Random,
) -> Tuple[Individual, Individual]:
    """一様交叉: 各便について50%の確率で親を切り替え"""
    trip_ids = [tr.trip_id for tr in cfg.trips]

    child1_assign: Dict[str, str] = {}
    child2_assign: Dict[str, str] = {}

    for r in trip_ids:
        p1_bus = parent1.solution.assignment.get(r)
        p2_bus = parent2.solution.assignment.get(r)

        if p1_bus is None:
            p1_bus = rng.choice([b.bus_id for b in cfg.buses])
        if p2_bus is None:
            p2_bus = rng.choice([b.bus_id for b in cfg.buses])

        if rng.random() < 0.5:
            child1_assign[r] = p1_bus
            child2_assign[r] = p2_bus
        else:
            child1_assign[r] = p2_bus
            child2_assign[r] = p1_bus

    child1 = Individual(AssignmentSolution(child1_assign))
    child2 = Individual(AssignmentSolution(child2_assign))
    return child1, child2


# ---------------------------------------------------------------------------
# 突然変異: ランダム便の再割り当て
# ---------------------------------------------------------------------------

def _mutate(
    individual: Individual,
    cfg: ProblemConfig,
    rng: random.Random,
) -> Individual:
    """突然変異: ランダムに1-2便を別のバスに割り当て直し"""
    new_ind = individual.copy()
    trip_ids = list(new_ind.solution.assignment.keys())
    bus_ids = [b.bus_id for b in cfg.buses]
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}

    n_mutate = rng.randint(1, max(1, min(3, len(trip_ids) // 3)))
    targets = rng.sample(trip_ids, min(n_mutate, len(trip_ids)))

    for r in targets:
        tr = trip_lut[r]
        # オーバーラップ回避を試行
        candidates = []
        for b_id in bus_ids:
            conflict = False
            for ar in new_ind.solution.get_trips_for_bus(b_id):
                if ar == r:
                    continue
                at = trip_lut[ar]
                if not (tr.end_t < at.start_t or at.end_t < tr.start_t):
                    conflict = True
                    break
            if not conflict:
                candidates.append(b_id)

        if candidates:
            new_ind.solution.assignment[r] = rng.choice(candidates)
        else:
            new_ind.solution.assignment[r] = rng.choice(bus_ids)

    new_ind.fitness = float("inf")
    new_ind.details = None
    return new_ind


# ---------------------------------------------------------------------------
# 適応度評価
# ---------------------------------------------------------------------------

def _evaluate_individual(
    individual: Individual,
    cfg: ProblemConfig,
) -> Individual:
    """個体の適応度を評価（未評価の場合のみ）"""
    if individual.fitness < float("inf"):
        return individual
    cost, details = evaluate_assignment(individual.solution, cfg)
    individual.fitness = cost
    individual.details = details
    return individual


# ---------------------------------------------------------------------------
# 実行不能解の修復
# ---------------------------------------------------------------------------

def _repair_overlaps(
    individual: Individual,
    cfg: ProblemConfig,
    rng: random.Random,
) -> Individual:
    """オーバーラップしている割り当てを修復"""
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}
    bus_ids = [b.bus_id for b in cfg.buses]
    sol = individual.solution
    changed = False

    for b_id in bus_ids:
        bus_trips = sol.get_trips_for_bus(b_id)
        if len(bus_trips) < 2:
            continue

        # 時刻順にソート
        bus_trips_sorted = sorted(bus_trips, key=lambda r: trip_lut[r].start_t)

        for i in range(len(bus_trips_sorted) - 1):
            r1 = bus_trips_sorted[i]
            r2 = bus_trips_sorted[i + 1]
            t1 = trip_lut[r1]
            t2 = trip_lut[r2]

            if not (t1.end_t < t2.start_t or t2.end_t < t1.start_t):
                # オーバーラップ -> r2 を別バスに移す
                candidates = []
                for alt_b in bus_ids:
                    if alt_b == b_id:
                        continue
                    conflict = False
                    for ar in sol.get_trips_for_bus(alt_b):
                        at = trip_lut[ar]
                        if not (t2.end_t < at.start_t or at.end_t < t2.start_t):
                            conflict = True
                            break
                    if not conflict:
                        candidates.append(alt_b)

                if candidates:
                    sol.assignment[r2] = rng.choice(candidates)
                    changed = True

    if changed:
        individual.fitness = float("inf")
        individual.details = None
    return individual


# ---------------------------------------------------------------------------
# GA メインループ
# ---------------------------------------------------------------------------

def solve_ga(
    cfg: ProblemConfig,
    params: Optional[GAParams] = None,
    callback: Optional[Callable[[int, float, float], None]] = None,
) -> SolveResult:
    """
    遺伝的アルゴリズムで解く。

    Parameters
    ----------
    cfg : ProblemConfig
    params : GAParams (省略時はデフォルト)
    callback : Optional[(generation, current_best_fitness, global_best_fitness) -> None]

    Returns
    -------
    SolveResult
    """
    if params is None:
        params = GAParams()

    if not cfg.trip_active:
        cfg = precompute_helpers(cfg)

    rng = random.Random(params.seed)
    t_start = time.perf_counter()

    # ---------- 初期集団 ----------
    population = _generate_population(cfg, params.population_size, rng)

    # 全個体を評価
    for i in range(len(population)):
        population[i] = _evaluate_individual(population[i], cfg)

    population.sort(key=lambda ind: ind.fitness)

    best_individual = population[0].copy()
    best_fitness = best_individual.fitness
    no_improve_count = 0
    iteration_log: List[Dict[str, Any]] = []

    # ---------- 世代ループ ----------
    for gen in range(1, params.max_generations + 1):
        new_population: List[Individual] = []

        # エリート保存
        elites = [population[i].copy() for i in range(min(params.elitism_count, len(population)))]
        new_population.extend(elites)

        # 子孫生成
        while len(new_population) < params.population_size:
            # 選択
            parent1 = _tournament_select(population, params.tournament_size, rng)
            parent2 = _tournament_select(population, params.tournament_size, rng)

            # 交叉
            if rng.random() < params.crossover_rate:
                child1, child2 = _crossover(parent1, parent2, cfg, rng)
            else:
                child1 = parent1.copy()
                child2 = parent2.copy()

            # 突然変異
            if rng.random() < params.mutation_rate:
                child1 = _mutate(child1, cfg, rng)
            if rng.random() < params.mutation_rate:
                child2 = _mutate(child2, cfg, rng)

            # オーバーラップ修復
            child1 = _repair_overlaps(child1, cfg, rng)
            child2 = _repair_overlaps(child2, cfg, rng)

            new_population.append(child1)
            if len(new_population) < params.population_size:
                new_population.append(child2)

        # 全個体を評価
        for i in range(len(new_population)):
            new_population[i] = _evaluate_individual(new_population[i], cfg)

        new_population.sort(key=lambda ind: ind.fitness)
        population = new_population[:params.population_size]

        # 最良解更新
        gen_best = population[0].fitness
        if gen_best < best_fitness:
            best_individual = population[0].copy()
            best_fitness = gen_best
            no_improve_count = 0
        else:
            no_improve_count += 1

        # ログ
        avg_fitness = sum(
            ind.fitness for ind in population if ind.fitness < float("inf")
        )
        n_finite = sum(1 for ind in population if ind.fitness < float("inf"))
        avg_val = avg_fitness / n_finite if n_finite > 0 else None

        log_entry = {
            "iteration": gen,
            "current_cost": round(gen_best, 2) if gen_best < float("inf") else None,
            "best_cost": round(best_fitness, 2) if best_fitness < float("inf") else None,
            "avg_cost": round(avg_val, 2) if avg_val is not None else None,
            "population_size": len(population),
        }
        iteration_log.append(log_entry)

        if callback:
            callback(gen, gen_best, best_fitness)

        # 早期終了
        if no_improve_count >= params.max_no_improve:
            break

    elapsed = time.perf_counter() - t_start

    # ---------- 結果構築 ----------
    result = SolveResult(
        solver_name="ga",
        status="FEASIBLE" if best_fitness < float("inf") else "INFEASIBLE",
        objective_value=round(best_fitness, 2) if best_fitness < float("inf") else None,
        solve_time_sec=round(elapsed, 3),
    )

    # 割当
    for b in [bus.bus_id for bus in cfg.buses]:
        trips = best_individual.solution.get_trips_for_bus(b)
        if trips:
            result.assignment[b] = trips

    # 詳細情報
    if best_individual.details:
        result.grid_buy = best_individual.details.get("grid_buy", {})
        result.pv_use = best_individual.details.get("pv_use", {})
        if "soc" in best_individual.details:
            result.soc_series = best_individual.details["soc"]
        if "charge_schedule" in best_individual.details:
            result.charge_schedule = best_individual.details["charge_schedule"]
        if "charge_energy" in best_individual.details:
            result.charge_energy = best_individual.details["charge_energy"]

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
