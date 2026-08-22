"""Post-solve stress checks that never change a saved optimization decision."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping

from src.dispatch.models import DispatchContext, Trip
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import CanonicalOptimizationProblem
from src.optimization.common.result import ResultSerializer

from .physical_event_schedule import validate_physical_event_schedule


FIXED_SOLUTION_STRESS_SCHEMA_VERSION = "fixed_solution_stress_v1"


@dataclass(frozen=True)
class FixedSolutionStress:
    """One explicit perturbation applied to inputs, never to decisions."""

    name: str
    energy_scale: float = 1.0
    travel_time_scale: float = 1.0
    pv_scale: float = 1.0
    charger_outage_id: str | None = None
    initial_soc_delta_percentage_points: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("fixed-solution stress name must not be empty")
        for field_name, value in (
            ("energy_scale", self.energy_scale),
            ("travel_time_scale", self.travel_time_scale),
            ("pv_scale", self.pv_scale),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{field_name} must be finite and positive")
        if not math.isfinite(float(self.initial_soc_delta_percentage_points)):
            raise ValueError("initial_soc_delta_percentage_points must be finite")


def standard_fixed_solution_stresses(
    canonical_result: Mapping[str, Any],
) -> tuple[FixedSolutionStress, ...]:
    """Return the requested six auditable fixed-decision perturbations."""
    used_chargers = sorted(
        {
            str(row.get("charger_id") or "").strip()
            for row in list(canonical_result.get("charging_schedule") or ())
            if isinstance(row, Mapping) and str(row.get("charger_id") or "").strip()
        }
    )
    if not used_chargers:
        raise ValueError(
            "one_charger_outage requires a canonical result with at least one "
            "used physical charger"
        )
    outage_charger = used_chargers[0]
    return (
        FixedSolutionStress(name="bev_energy_plus_10pct", energy_scale=1.10),
        FixedSolutionStress(name="bev_energy_plus_20pct", energy_scale=1.20),
        FixedSolutionStress(name="travel_time_plus_10pct", travel_time_scale=1.10),
        FixedSolutionStress(name="pv_minus_20pct", pv_scale=0.80),
        FixedSolutionStress(name="one_charger_outage", charger_outage_id=outage_charger),
        FixedSolutionStress(
            name="initial_soc_minus_5pp",
            initial_soc_delta_percentage_points=-5.0,
        ),
        FixedSolutionStress(
            name="combined_energy20_time10_pv20_charger_soc5",
            energy_scale=1.20,
            travel_time_scale=1.10,
            pv_scale=0.80,
            charger_outage_id=outage_charger,
            initial_soc_delta_percentage_points=-5.0,
        ),
    )


def apply_fixed_solution_stress(
    problem: CanonicalOptimizationProblem,
    stress: FixedSolutionStress,
) -> CanonicalOptimizationProblem:
    """Copy inputs for a stress case while preserving the dispatch decision."""
    dispatch_context = _scaled_dispatch_context(problem.dispatch_context, stress)
    trips = tuple(
        replace(
            trip,
            energy_kwh=float(trip.energy_kwh or 0.0) * stress.energy_scale,
            energy_kwh_by_vehicle_type={
                str(key): float(value or 0.0) * stress.energy_scale
                for key, value in dict(trip.energy_kwh_by_vehicle_type or {}).items()
            },
            arrival_min=_scaled_arrival_min(
                trip.departure_min,
                trip.arrival_min,
                stress.travel_time_scale,
            ),
        )
        for trip in problem.trips
    )
    vehicles = tuple(
        _apply_initial_soc_delta(vehicle, stress.initial_soc_delta_percentage_points)
        for vehicle in problem.vehicles
    )
    assets = {
        depot_id: replace(
            asset,
            pv_generation_kwh_by_slot=tuple(
                float(value or 0.0) * stress.pv_scale
                for value in asset.pv_generation_kwh_by_slot
            ),
            available_pv_surplus_kwh_by_slot=tuple(
                float(value or 0.0) * stress.pv_scale
                for value in asset.available_pv_surplus_kwh_by_slot
            ),
        )
        for depot_id, asset in problem.depot_energy_assets.items()
    }
    chargers = tuple(
        charger
        for charger in problem.chargers
        if str(charger.charger_id) != str(stress.charger_outage_id or "")
    )
    metadata = dict(problem.metadata or {})
    metadata["fixed_solution_stress"] = {
        "name": stress.name,
        "energy_scale": stress.energy_scale,
        "travel_time_scale": stress.travel_time_scale,
        "pv_scale": stress.pv_scale,
        "charger_outage_id": stress.charger_outage_id,
        "initial_soc_delta_percentage_points": stress.initial_soc_delta_percentage_points,
        "reoptimization_performed": False,
    }
    return replace(
        problem,
        dispatch_context=dispatch_context,
        trips=trips,
        vehicles=vehicles,
        chargers=chargers,
        depot_energy_assets=assets,
        metadata=metadata,
    )


def evaluate_fixed_solution_stress(
    *,
    problem: CanonicalOptimizationProblem,
    canonical_result: Mapping[str, Any],
    stress: FixedSolutionStress,
) -> dict[str, Any]:
    """Independently evaluate one saved decision under altered inputs.

    The returned cost difference is intentionally unavailable for an invalid
    fixed decision.  Reporting a monetary counterfactual after the plan has
    already failed its physical contract would turn an infeasible schedule
    into a misleading operational-cost claim.
    """
    baseline_plan = ResultSerializer.deserialize_plan(problem, canonical_result)
    baseline_validation = validate_physical_event_schedule(
        problem=problem,
        serialized_result=canonical_result,
    )
    baseline_cost = CostEvaluator().evaluate(problem, baseline_plan).to_dict()
    stressed_problem = apply_fixed_solution_stress(problem, stress)
    stressed_plan = ResultSerializer.deserialize_plan(stressed_problem, canonical_result)
    physical = validate_physical_event_schedule(
        problem=stressed_problem,
        serialized_result=canonical_result,
    )
    pv_supply_violations = _pv_supply_violations(stressed_problem, stressed_plan)
    physically_accepted = bool(physical.get("accepted")) and not pv_supply_violations
    stressed_cost = (
        CostEvaluator().evaluate(stressed_problem, stressed_plan).to_dict()
        if physically_accepted
        else None
    )
    metrics = dict(physical.get("metrics") or {})
    trip_count = len(stressed_problem.trips)
    unassigned_count = int(metrics.get("unassigned_trip_count") or 0)
    minimum_soc = min(
        (
            float(row.get("soc_after_kwh"))
            for row in list(physical.get("vehicle_soc_events") or ())
            if row.get("soc_after_kwh") is not None
        ),
        default=None,
    )
    baseline_total = float(baseline_cost.get("total_cost", 0.0) or 0.0)
    stressed_total = (
        float(stressed_cost.get("total_cost", 0.0) or 0.0)
        if stressed_cost is not None
        else None
    )
    return {
        "schema_version": FIXED_SOLUTION_STRESS_SCHEMA_VERSION,
        "stress": dict(stressed_problem.metadata["fixed_solution_stress"]),
        "reoptimization_performed": False,
        "baseline_physical_accepted": bool(baseline_validation.get("accepted")),
        "physical_accepted": physically_accepted,
        "completion_rate": (trip_count - unassigned_count) / trip_count if trip_count else 0.0,
        "minimum_soc_kwh": minimum_soc,
        "physical_violation_count": len(list(physical.get("violations") or ())) + len(pv_supply_violations),
        "physical_validation": physical,
        "pv_supply_violations": pv_supply_violations,
        "baseline_cost_jpy": baseline_total,
        "fixed_decision_cost_jpy": stressed_total,
        "additional_cost_jpy": (
            stressed_total - baseline_total if stressed_total is not None else None
        ),
        "cost_status": (
            "available_fixed_decision_accounting"
            if stressed_total is not None
            else "unavailable_due_to_fixed_decision_physical_failure"
        ),
    }


def _scaled_dispatch_context(
    context: Any,
    stress: FixedSolutionStress,
) -> Any:
    if not isinstance(context, DispatchContext):
        raise ValueError("fixed-solution stress requires DispatchContext")
    trips = [
        replace(
            trip,
            arrival_time=_hhmm(
                _scaled_arrival_min(
                    trip.departure_min,
                    trip.arrival_min,
                    stress.travel_time_scale,
                )
            ),
        )
        for trip in context.trips
    ]
    return replace(context, trips=trips)


def _scaled_arrival_min(departure_min: int, arrival_min: int, scale: float) -> int:
    duration = int(arrival_min) - int(departure_min)
    if duration <= 0:
        duration += 24 * 60
    return (int(departure_min) + max(1, math.ceil(duration * scale))) % (24 * 60)


def _hhmm(minute: int) -> str:
    normalized = int(minute) % (24 * 60)
    return f"{normalized // 60:02d}:{normalized % 60:02d}"


def _apply_initial_soc_delta(vehicle: Any, delta_percentage_points: float) -> Any:
    capacity = float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 0.0)
    if capacity <= 0.0 or delta_percentage_points == 0.0:
        return vehicle
    current = getattr(vehicle, "initial_soc", None)
    initial = 0.8 * capacity if current is None else float(current)
    if initial <= 1.0:
        initial *= capacity
    return replace(
        vehicle,
        initial_soc=min(max(initial + capacity * delta_percentage_points / 100.0, 0.0), capacity),
    )


def _pv_supply_violations(
    problem: CanonicalOptimizationProblem,
    plan: Any,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for depot_id, asset in problem.depot_energy_assets.items():
        pv_to_bus = dict(plan.pv_to_bus_kwh_by_depot_slot.get(depot_id, {}) or {})
        pv_to_bess = dict(plan.pv_to_bess_kwh_by_depot_slot.get(depot_id, {}) or {})
        slots = set(pv_to_bus).union(pv_to_bess)
        generation = tuple(asset.pv_generation_kwh_by_slot or ())
        for slot_index in sorted(slots):
            used = max(float(pv_to_bus.get(slot_index, 0.0) or 0.0), 0.0) + max(
                float(pv_to_bess.get(slot_index, 0.0) or 0.0), 0.0
            )
            available = (
                max(float(generation[int(slot_index)] or 0.0), 0.0)
                if 0 <= int(slot_index) < len(generation)
                else 0.0
            )
            if used > available + 1.0e-6:
                violations.append(
                    {
                        "code": "pv_supply_exceeded",
                        "depot_id": str(depot_id),
                        "slot_index": int(slot_index),
                        "used_kwh": used,
                        "available_kwh": available,
                    }
                )
    return violations
