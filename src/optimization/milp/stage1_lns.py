"""Adaptive large-neighbourhood search (MIP-based LNS) for the Stage 1 assignment.

The full-network Stage 1 MILP of the 2026-11-28 midterm weeks did not improve on
its supplied seed within 6 h (root LP ~2.2 h, one node).  This module improves
the incumbent before the main Stage 1 optimize:

1. Load the supplied seed as a complete incumbent (``SolutionLimit=1``).
2. Repeatedly free the binary variables that touch a neighbourhood of trips
   (a time window, a random trip sample, a route family on one day, or one
   whole day), fix every other trip-indexed binary at its incumbent value,
   re-optimize the same model with the incumbent as MIP start, and accept a
   strictly cheaper solution.  Operator weights adapt (ALNS roulette).
3. Restore every bound and parameter, and leave the best incumbent as the
   complete MIP start of the unchanged model.

The caller then runs the normal Stage 1 optimize, so the reported status, bound
and gap come from the unchanged full model.  The model, constraints and
objective are never changed; only variable bounds are tightened temporarily.
Every sub-solve's incumbent is feasible for the full model (fixing only
restricts it), and lazy-constraint callbacks are passed through.  The result
is a heuristic improvement, never an optimality certificate.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np


# "full_day" (all trips of one day) was never accepted in rc7 (0/44) and is the
# neighbourhood most likely to hit the memory cap; it stays available but unused.
OPERATORS = ("time_window", "random_trips", "route_day")
# "vehicle_day" (2026-11-07, user "C"): free every trip that a few battery and a few
# engine buses serve on one day in the incumbent, so whole duties can move between
# vehicles and powertrains. Trip-sample neighbourhoods almost never free a complete
# duty, so the seed's BEV/ICE split could not change (rc29: 0.5 % improvement in 1 h).
ALL_OPERATORS = OPERATORS + ("vehicle_day",)


@dataclass(frozen=True)
class LnsTrip:
    trip_id: str
    start_min: int
    day_index: int
    route_key: str


@dataclass(frozen=True)
class LnsSettings:
    time_budget_sec: float
    iteration_time_limit_sec: float = 300.0
    initial_time_limit_sec: float = 1800.0
    window_min: float = 240.0
    random_fraction: float = 0.08
    seed: int = 42
    improvement_tolerance_yen: float = 1.0
    max_iterations: Optional[int] = None
    operators: Sequence[str] = OPERATORS


def trip_index_arrays(names: Sequence[str], trip_ids: Sequence[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map each variable name to up to two trip indices (``-1`` when absent).

    Names are ``<family>_<...>_<trip>[_<trip>]``; trip IDs contain no ``_``.
    A name with more than two trip tokens is marked ``many`` and never fixed.
    """
    lookup = {trip_id: index for index, trip_id in enumerate(trip_ids)}
    first = np.full(len(names), -1, dtype=np.int32)
    second = np.full(len(names), -1, dtype=np.int32)
    many = np.zeros(len(names), dtype=bool)
    for position, name in enumerate(names):
        found = [lookup[token] for token in name.split("_") if token in lookup]
        if found:
            first[position] = found[0]
            if len(found) > 1:
                second[position] = found[1]
            if len(found) > 2:
                many[position] = True
    return first, second, many


class _Neighbourhoods:
    def __init__(self, trips: Sequence[LnsTrip], settings: LnsSettings, rng: random.Random):
        self.trips, self.settings, self.rng = trips, settings, rng
        self.start = np.array([trip.start_min for trip in trips], dtype=np.int64)
        self.days = sorted({trip.day_index for trip in trips})
        self.scale = {name: 1.0 for name in ALL_OPERATORS}
        self.assignment: Optional[Dict[int, str]] = None   # trip index -> vehicle in the incumbent
        self.vehicle_types: Mapping[str, str] = {}

    def vehicle_day_mask(self) -> np.ndarray:
        """All trips of ``k`` battery and ``k`` engine buses on one day (k = 3 x scale)."""
        n = len(self.trips)
        mask = np.zeros(n, dtype=bool)
        if not self.assignment:
            return mask
        day = self.rng.choice(self.days)
        by_vehicle: Dict[str, List[int]] = {}
        for index, vehicle in sorted(self.assignment.items()):
            if self.trips[index].day_index == day:
                by_vehicle.setdefault(vehicle, []).append(index)
        k = max(1, round(3 * self.scale["vehicle_day"]))
        groups: Dict[bool, List[str]] = {True: [], False: []}
        for vehicle in sorted(by_vehicle):
            kind = str(self.vehicle_types.get(vehicle, "")).upper()
            groups[kind in {"BEV", "PHEV", "FCEV"}].append(vehicle)
        chosen: List[str] = []
        for electric in (True, False):
            pool = groups[electric]
            chosen += self.rng.sample(pool, min(k, len(pool)))
        for vehicle in chosen:
            mask[by_vehicle[vehicle]] = True
        return mask

    def free_mask(self, operator: str) -> np.ndarray:
        n = len(self.trips)
        mask = np.zeros(n, dtype=bool)
        scale = self.scale[operator]
        if operator == "time_window":
            width = self.settings.window_min * scale
            low, high = int(self.start.min()), int(self.start.max())
            begin = self.rng.uniform(low, max(low, high - width))
            mask = (self.start >= begin) & (self.start < begin + width)
        elif operator == "random_trips":
            count = max(2, int(n * min(self.settings.random_fraction * scale, 0.5)))
            mask[self.rng.sample(range(n), min(count, n))] = True
        elif operator == "vehicle_day":
            mask = self.vehicle_day_mask()
        elif operator == "route_day":
            day = self.rng.choice(self.days)
            keys = sorted({t.route_key for t in self.trips if t.day_index == day})
            chosen = set(self.rng.sample(keys, max(1, min(len(keys), round(2 * scale)))))
            mask = np.array([t.day_index == day and t.route_key in chosen for t in self.trips])
        else:
            day = self.rng.choice(self.days)
            mask = np.array([t.day_index == day for t in self.trips])
        if mask.sum() < 2:
            mask[self.rng.sample(range(n), min(2, n))] = True
        return mask

    def adapt(self, operator: str, *, timed_out: bool, improved: bool) -> None:
        if timed_out and not improved:
            self.scale[operator] = max(0.25, self.scale[operator] * 0.8)
        elif not timed_out and not improved:
            self.scale[operator] = min(4.0, self.scale[operator] * 1.25)


def run_stage1_lns(
    model: Any,
    GRB: Any,
    *,
    trips: Sequence[LnsTrip],
    settings: LnsSettings,
    optimize: Callable[[Any], None],
    log: Callable[[str], None] = lambda message: None,
    vehicle_types: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Improve the model's incumbent in place; return auditable telemetry."""
    began = time.monotonic()
    rng = random.Random(settings.seed)
    saved_params = {name: model.getParamInfo(name)[2] for name in ("TimeLimit", "SolutionLimit", "MIPFocus", "MIPGap", "SoftMemLimit")}
    result: Dict[str, Any] = {
        "schema_version": "stage1_lns_v1", "applied": False, "operators": list(settings.operators),
        "settings": settings.__dict__.copy(), "iterations": [],
        "semantics": "heuristic incumbent improvement; bounds tightened temporarily, model unchanged; "
                     "never an optimality certificate",
    }
    # Pending additions are invisible to getVars() until update (lazy update mode).
    model.update()
    variables = model.getVars()
    best: Optional[np.ndarray] = None
    best_objective = math.inf
    try:
        model.Params.SolutionLimit = 1
        model.Params.TimeLimit = max(min(settings.initial_time_limit_sec, settings.time_budget_sec), 1.0)
        optimize(model)
        if model.SolCount < 1:
            result["skip_reason"] = "seed_not_loaded_within_initial_limit"
            return result
        best = np.array(model.getAttr("X", variables), dtype=float)
        best_objective = float(model.ObjVal)
        result.update(initial_objective=best_objective, initial_load_sec=round(time.monotonic() - began, 3))
        log(f"stage1 LNS: initial incumbent {best_objective:.2f}")

        vtypes = model.getAttr("VType", variables)
        binary = np.fromiter((kind == GRB.BINARY for kind in vtypes), dtype=bool, count=len(vtypes))
        # Names are read in chunks: 6.8M Python strings at once would cost ~1.5 GB.
        trip_ids = [trip.trip_id for trip in trips]
        trip_lookup = {trip_id: index for index, trip_id in enumerate(trip_ids)}
        assignment_positions: List[tuple] = []   # (position, vehicle, trip index) of y_<vehicle>_<trip>
        parts = []
        for i in range(0, len(variables), 250_000):
            chunk_names = model.getAttr("VarName", variables[i:i + 250_000])
            parts.append(trip_index_arrays(chunk_names, trip_ids))
            if "vehicle_day" in settings.operators:
                for offset, name in enumerate(chunk_names):
                    if name.startswith("y_"):
                        vehicle, _, trip_id = name[2:].rpartition("_")
                        if trip_id in trip_lookup:
                            assignment_positions.append((i + offset, vehicle, trip_lookup[trip_id]))
            del chunk_names
        first = np.concatenate([part[0] for part in parts]) if parts else np.zeros(0, dtype=np.int32)
        second = np.concatenate([part[1] for part in parts]) if parts else np.zeros(0, dtype=np.int32)
        many = np.concatenate([part[2] for part in parts]) if parts else np.zeros(0, dtype=bool)
        del parts
        candidates = np.flatnonzero(binary & (first >= 0) & ~many)
        candidate_vars = [variables[i] for i in candidates]
        original_lb = np.array(model.getAttr("LB", candidate_vars), dtype=float)
        original_ub = np.array(model.getAttr("UB", candidate_vars), dtype=float)
        result["trip_indexed_binary_count"] = int(len(candidates))
        neighbourhoods = _Neighbourhoods(trips, settings, rng)
        neighbourhoods.vehicle_types = dict(vehicle_types or {})

        def refresh_assignment() -> None:
            if assignment_positions:
                neighbourhoods.assignment = {trip: vehicle for position, vehicle, trip in assignment_positions
                                             if best[position] > 0.5}
        refresh_assignment()
        result["assignment_binary_count"] = len(assignment_positions)
        weights = {name: 1.0 for name in settings.operators}
        model.Params.SolutionLimit = 2_000_000_000
        model.Params.MIPFocus = 1
        # The run's relative MIPGap (e.g. 1 %) would declare a neighbourhood
        # "optimal" at the incumbent whenever its local bound is within 1 % of
        # the whole-week objective, so every sub-solve must close its own gap.
        model.Params.MIPGap = 0.0
        # Stop a too-large neighbourhood gracefully (status MEM_LIMIT) well before
        # the hard native cap, which would raise instead.
        hard_limit = float(model.Params.MemLimit)
        if math.isfinite(hard_limit) and hard_limit < 1e90:
            model.Params.SoftMemLimit = min(float(model.Params.SoftMemLimit), 0.8 * hard_limit)

        while True:
            remaining = settings.time_budget_sec - (time.monotonic() - began)
            if remaining < max(1.0, 0.25 * settings.iteration_time_limit_sec):
                break
            if settings.max_iterations is not None and len(result["iterations"]) >= settings.max_iterations:
                break
            operator = rng.choices(list(settings.operators), weights=[weights[name] for name in settings.operators])[0]
            free_trips = neighbourhoods.free_mask(operator)
            cand_first, cand_second = first[candidates], second[candidates]
            free_var = free_trips[cand_first] | ((cand_second >= 0) & free_trips[np.maximum(cand_second, 0)])
            fix_positions = np.flatnonzero(~free_var)
            fix_vars = [candidate_vars[i] for i in fix_positions]
            values = np.clip(np.rint(best[candidates[fix_positions]]), original_lb[fix_positions],
                             original_ub[fix_positions]).tolist()
            iteration_began = time.monotonic()
            model.setAttr("LB", fix_vars, values)
            model.setAttr("UB", fix_vars, values)
            model.setAttr("Start", variables, best.tolist())
            model.Params.TimeLimit = max(min(settings.iteration_time_limit_sec, remaining), 1.0)
            out_of_memory = False
            try:
                try:
                    optimize(model)
                    status = int(model.Status)
                    objective = float(model.ObjVal) if model.SolCount > 0 else math.inf
                    out_of_memory = status == getattr(GRB, "MEM_LIMIT", -1)
                except Exception as exc:
                    # A neighbourhood too large for the native memory cap fails only
                    # this sub-solve (Gurobi error 10001); shrink it and continue.
                    if getattr(exc, "errno", None) != 10001:
                        raise
                    out_of_memory, status, objective = True, -10001, math.inf
                improved = objective < best_objective - settings.improvement_tolerance_yen
                if improved:
                    best = np.array(model.getAttr("X", variables), dtype=float)
                    best_objective = objective
                    refresh_assignment()
            finally:
                model.setAttr("LB", candidate_vars, original_lb.tolist())
                model.setAttr("UB", candidate_vars, original_ub.tolist())
            timed_out = status == GRB.TIME_LIMIT
            weights[operator] = max(0.1, 0.8 * weights[operator] + 0.2 * (3.0 if improved else 0.0))
            neighbourhoods.adapt(operator, timed_out=timed_out or out_of_memory, improved=improved)
            if out_of_memory:
                neighbourhoods.scale[operator] = max(0.25, neighbourhoods.scale[operator] * 0.5)
            result["iterations"].append({
                "operator": operator, "free_trips": int(free_trips.sum()), "fixed_binaries": len(fix_vars),
                "status": status, "objective": None if math.isinf(objective) else objective,
                "improved": improved, "best_objective": best_objective,
                "sec": round(time.monotonic() - iteration_began, 3)})
            if improved:
                log(f"stage1 LNS: {operator} improved to {best_objective:.2f}")
        result.update(applied=True, best_objective=best_objective,
                      improvement_yen=result["initial_objective"] - best_objective,
                      accepted=sum(1 for item in result["iterations"] if item["improved"]),
                      operator_weights=weights, operator_scales=dict(neighbourhoods.scale))
        return result
    finally:
        if best is not None:
            # Whatever happens, the best incumbent found so far stays the MIP start.
            model.setAttr("Start", variables, best.tolist())
            result["best_objective_at_exit"] = best_objective
        for name, value in saved_params.items():
            model.setParam(name, value)
        result["elapsed_sec"] = round(time.monotonic() - began, 3)


def optimize_after_lns(model: Any, lns_result: Dict[str, Any], *, optimize: Callable[[Any], None]) -> None:
    """Run the final full-model solve after LNS without losing its incumbent.

    The soft memory cap gets the LNS sub-solve margin, so Gurobi normally stops
    with MEM_LIMIT and keeps the incumbent. If the native cap still raises
    (error 10001; rc11 hit it in every post-LNS root LP), the LNS best remains
    the model's MIP start and is reloaded without search; the status then reads
    solution_limit and ``final_solve_out_of_memory`` records the event.
    """
    hard_limit = float(model.Params.MemLimit)
    if math.isfinite(hard_limit) and hard_limit < 1e90:
        model.Params.SoftMemLimit = min(float(model.Params.SoftMemLimit), 0.8 * hard_limit)
    try:
        optimize(model)
    except Exception as exc:
        if getattr(exc, "errno", None) != 10001:
            raise
        lns_result["final_solve_out_of_memory"] = True
        model.Params.SolutionLimit = 1
        optimize(model)


def lns_trips(problem_trips: Sequence[Any]) -> List[LnsTrip]:
    """Absolute start minute per trip; per-day minutes are offset by the day index."""
    absolute = max((int(t.departure_min) for t in problem_trips), default=0) > 1.5 * 1440
    return [LnsTrip(trip_id=str(t.trip_id),
                    start_min=int(t.departure_min) if absolute else int(t.day_index) * 1440 + int(t.departure_min),
                    day_index=int(getattr(t, "day_index", 0) or 0),
                    route_key=str(getattr(t, "route_family_code", "") or getattr(t, "route_id", "")))
            for t in problem_trips]


def lns_settings_from_controls(controls: Mapping[str, Any], *, stage_time_limit_sec: float,
                               seed: int) -> Optional[LnsSettings]:
    """Return settings when the profile enables LNS and the budget leaves a final solve reserve."""
    if not controls.get("lns_enabled"):
        return None
    reserve = float(controls.get("lns_final_reserve_sec", 1800.0))
    budget = float(stage_time_limit_sec) - reserve
    iteration = float(controls.get("lns_iteration_time_limit_sec", 300.0))
    if budget < 2 * iteration:
        return None
    return LnsSettings(time_budget_sec=budget, iteration_time_limit_sec=iteration,
                       initial_time_limit_sec=float(controls.get("lns_initial_time_limit_sec", 1800.0)),
                       seed=int(seed), operators=tuple(controls.get("lns_operators", OPERATORS)))

