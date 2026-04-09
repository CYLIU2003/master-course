from __future__ import annotations

import time
from dataclasses import replace
from typing import Iterable, Sequence

from src.dispatch.models import VehicleDuty

from .evaluator import CostEvaluator
from .feasibility import FeasibilityChecker
from .problem import AssignmentPlan, CanonicalOptimizationProblem, SolutionState
from .search_profile import SearchProfile


def build_solution_state(
    problem: CanonicalOptimizationProblem,
    plan: AssignmentPlan,
    *,
    feasibility: FeasibilityChecker,
    evaluator: CostEvaluator,
    profile: SearchProfile | None = None,
    started_at: float | None = None,
) -> SolutionState:
    eval_started = time.perf_counter()
    report = feasibility.evaluate(problem, plan)
    breakdown = evaluator.evaluate(problem, plan)
    vehicle_ledger, daily_ledger = evaluator.build_plan_ledgers(problem, plan, breakdown)
    plan = replace(plan, vehicle_cost_ledger=vehicle_ledger, daily_cost_ledger=daily_ledger)
    if profile is not None:
        elapsed = time.perf_counter() - eval_started
        profile.record_evaluation(
            elapsed,
            feasible=report.feasible,
            elapsed_sec=(time.perf_counter() - started_at) if started_at is not None else elapsed,
        )
    return SolutionState(
        problem=problem,
        plan=plan,
        cost_breakdown=breakdown.to_dict(),
        feasible=report.feasible,
        infeasibility_reasons=report.errors,
        metadata={"warnings": report.warnings},
    )


def feasibility_first_better(candidate: SolutionState, incumbent: SolutionState, best: SolutionState) -> bool:
    if candidate.is_feasible() and not best.is_feasible():
        return True
    if candidate.is_feasible() and best.is_feasible():
        return candidate.objective() < best.objective()
    if not candidate.is_feasible() and not best.is_feasible():
        return candidate.objective() < best.objective()
    return False


def rebuild_plan_from_duties(
    problem: CanonicalOptimizationProblem,
    source_plan: AssignmentPlan,
    duties: Sequence[VehicleDuty],
    *,
    keep_energy_slots: bool = False,
    preserve_unserved: bool = True,
    metadata_updates: dict[str, object] | None = None,
) -> AssignmentPlan:
    served_trip_ids = tuple(sorted({trip_id for duty in duties for trip_id in duty.trip_ids}))
    all_trip_ids = {trip.trip_id for trip in problem.trips}
    unserved_trip_ids = all_trip_ids - set(served_trip_ids)
    if preserve_unserved:
        unserved_trip_ids = unserved_trip_ids.union(set(source_plan.unserved_trip_ids))
    unserved_trip_ids = tuple(sorted(unserved_trip_ids))
    metadata = dict(source_plan.metadata)
    if metadata_updates:
        metadata.update(metadata_updates)
    return AssignmentPlan(
        duties=tuple(duties),
        charging_slots=source_plan.charging_slots if keep_energy_slots else (),
        refuel_slots=source_plan.refuel_slots if keep_energy_slots else (),
        served_trip_ids=served_trip_ids,
        unserved_trip_ids=unserved_trip_ids,
        metadata=metadata,
    )


def merge_plan_duties(*plans: AssignmentPlan) -> tuple[VehicleDuty, ...]:
    duties: list[VehicleDuty] = []
    seen_trip_ids: set[str] = set()
    for plan in plans:
        for duty in plan.duties:
            trip_ids = tuple(str(trip_id) for trip_id in duty.trip_ids)
            if not trip_ids:
                continue
            if seen_trip_ids.intersection(trip_ids):
                continue
            duties.append(duty)
            seen_trip_ids.update(trip_ids)
    return tuple(duties)
