"""Independent exhaustive oracle for bounded all-ICE assignment cases.

The production MILP must not validate itself.  This module enumerates every
trip-to-vehicle assignment for at most ten trips and applies the canonical
connection, startup/return, fuel-inventory, and research lexicographic cost
semantics without importing any solver implementation.

The first version is deliberately narrow: one service day, strict coverage,
all-ICE fleet, and no refuelling.  Unsupported physics fail closed instead of
being silently approximated.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import json
from typing import Any, Mapping, Sequence

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ProblemTrip,
    ProblemVehicle,
    day_index_for_minute,
    normalize_service_coverage_mode,
)


MAX_EXACT_TRIPS = 10
MAX_EXACT_ASSIGNMENTS = 1_000_000
_ELECTRIC_POWERTRAINS = frozenset({"BEV", "PHEV", "FCEV"})


@dataclass(frozen=True)
class SmallExactOracleResult:
    assignment_by_trip: Mapping[str, str]
    plan: AssignmentPlan
    enumerated_assignment_count: int
    feasible_assignment_count: int
    used_vehicle_day_count: int
    canonical_operating_cost_jpy: float
    fuel_l: float
    fuel_cost_jpy: float
    inter_trip_deadhead_km: float
    objective_tuple: tuple[float, float, float]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": "small_exact_assignment_oracle_v1",
            "method": "complete_cartesian_trip_vehicle_enumeration",
            "scope": "strict_single_day_all_ice_no_refuelling_max_10_trips",
            "enumerated_assignment_count": self.enumerated_assignment_count,
            "feasible_assignment_count": self.feasible_assignment_count,
            "used_vehicle_day_count": self.used_vehicle_day_count,
            "canonical_operating_cost_jpy": self.canonical_operating_cost_jpy,
            "fuel_l": self.fuel_l,
            "fuel_cost_jpy": self.fuel_cost_jpy,
            "inter_trip_deadhead_km": self.inter_trip_deadhead_km,
            "objective_tuple": list(self.objective_tuple),
            "assignment_by_trip": dict(sorted(self.assignment_by_trip.items())),
        }


@dataclass(frozen=True)
class _CandidateEvaluation:
    assignment_by_trip: Mapping[str, str]
    used_vehicle_day_count: int
    canonical_operating_cost_jpy: float
    fuel_l: float
    fuel_cost_jpy: float
    inter_trip_deadhead_km: float

    @property
    def objective_tuple(self) -> tuple[float, float, float]:
        return (
            float(self.used_vehicle_day_count),
            float(self.canonical_operating_cost_jpy),
            float(self.inter_trip_deadhead_km),
        )


def solve_small_exact_assignment_oracle(
    problem: CanonicalOptimizationProblem,
    *,
    max_trips: int = MAX_EXACT_TRIPS,
    max_assignments: int = MAX_EXACT_ASSIGNMENTS,
) -> SmallExactOracleResult:
    """Enumerate and rank all feasible assignments for a bounded case."""

    trips = tuple(
        sorted(
            problem.trips,
            key=lambda trip: (
                int(trip.departure_min),
                int(trip.arrival_min),
                str(trip.trip_id),
            ),
        )
    )
    vehicles = tuple(
        sorted(
            (
                vehicle
                for vehicle in problem.vehicles
                if bool(getattr(vehicle, "available", True))
            ),
            key=lambda vehicle: str(vehicle.vehicle_id),
        )
    )
    _validate_supported_problem(problem, trips=trips, vehicles=vehicles, max_trips=max_trips)

    eligible_vehicle_ids_by_trip: list[tuple[str, ...]] = []
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in vehicles}
    for trip in trips:
        eligible = tuple(
            str(vehicle.vehicle_id)
            for vehicle in vehicles
            if str(vehicle.vehicle_type) in set(trip.allowed_vehicle_types)
        )
        if not eligible:
            raise ValueError(
                f"small exact oracle trip {trip.trip_id!r} has no compatible vehicle"
            )
        eligible_vehicle_ids_by_trip.append(eligible)

    _validate_assignment_space(
        eligible_vehicle_ids_by_trip,
        max_assignments=max_assignments,
        label="small exact oracle",
    )

    best: _CandidateEvaluation | None = None
    best_signature = ""
    enumerated = 0
    feasible = 0
    for selected_vehicle_ids in product(*eligible_vehicle_ids_by_trip):
        enumerated += 1
        assignment = {
            str(trip.trip_id): str(vehicle_id)
            for trip, vehicle_id in zip(trips, selected_vehicle_ids)
        }
        candidate = _evaluate_candidate(
            problem,
            trips=trips,
            vehicle_by_id=vehicle_by_id,
            assignment_by_trip=assignment,
        )
        if candidate is None:
            continue
        feasible += 1
        signature = json.dumps(
            dict(sorted(assignment.items())),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if best is None or (candidate.objective_tuple, signature) < (
            best.objective_tuple,
            best_signature,
        ):
            best = candidate
            best_signature = signature

    if best is None:
        raise ValueError("small exact oracle found no feasible complete assignment")
    plan = _assignment_plan(problem, trips=trips, assignment_by_trip=best.assignment_by_trip)
    return SmallExactOracleResult(
        assignment_by_trip=dict(best.assignment_by_trip),
        plan=plan,
        enumerated_assignment_count=enumerated,
        feasible_assignment_count=feasible,
        used_vehicle_day_count=best.used_vehicle_day_count,
        canonical_operating_cost_jpy=best.canonical_operating_cost_jpy,
        fuel_l=best.fuel_l,
        fuel_cost_jpy=best.fuel_cost_jpy,
        inter_trip_deadhead_km=best.inter_trip_deadhead_km,
        objective_tuple=best.objective_tuple,
    )


def _validate_assignment_space(
    eligible_vehicle_ids_by_trip: Sequence[Sequence[str]],
    *,
    max_assignments: int,
    label: str,
) -> None:
    hard_limit = min(
        max(int(max_assignments), 1),
        MAX_EXACT_ASSIGNMENTS,
    )
    assignment_count = 1
    for eligible in eligible_vehicle_ids_by_trip:
        assignment_count *= len(eligible)
        if assignment_count > hard_limit:
            raise ValueError(
                f"{label} assignment space {assignment_count} exceeds "
                f"hard limit {hard_limit}"
            )


def _validate_supported_problem(
    problem: CanonicalOptimizationProblem,
    *,
    trips: Sequence[ProblemTrip],
    vehicles: Sequence[ProblemVehicle],
    max_trips: int,
) -> None:
    if not trips or len(trips) > min(max(int(max_trips), 1), MAX_EXACT_TRIPS):
        raise ValueError(
            f"small exact oracle requires 1..{min(max(int(max_trips), 1), MAX_EXACT_TRIPS)} trips"
        )
    if not vehicles:
        raise ValueError("small exact oracle requires at least one available vehicle")
    if normalize_service_coverage_mode(problem.scenario.service_coverage_mode) != "strict":
        raise ValueError("small exact oracle requires strict service coverage")
    if str(problem.scenario.objective_mode or "").strip().lower() != "total_cost":
        raise ValueError("small exact oracle v1 requires objective_mode=total_cost")
    if str(problem.metadata.get("objective_preset") or "").strip() != (
        "research_lexicographic_v1"
    ):
        raise ValueError(
            "small exact oracle v1 requires objective_preset="
            "research_lexicographic_v1"
        )
    if int(problem.scenario.planning_days or 1) != 1:
        raise ValueError("small exact oracle currently supports one service day")
    electric = [
        str(vehicle.vehicle_id)
        for vehicle in vehicles
        if str(vehicle.vehicle_type).upper() in _ELECTRIC_POWERTRAINS
    ]
    if electric:
        raise ValueError(
            "small exact oracle v1 supports all-ICE cases only; "
            f"electric vehicles present: {electric}"
        )
    if any(
        bool(getattr(asset, "bess_enabled", False))
        for asset in problem.depot_energy_assets.values()
    ):
        raise ValueError("small exact oracle v1 does not support BESS")
    if any(
        bool(getattr(asset, "pv_enabled", False))
        for asset in problem.depot_energy_assets.values()
    ):
        raise ValueError("small exact oracle v1 does not support PV")
    component_flags = dict(problem.metadata.get("cost_component_flags") or {})
    unsupported_enabled = [
        key
        for key in (
            "driver_cost",
            "switch_cost",
            "demand_charge_cost",
            "co2_cost",
        )
        if bool(component_flags.get(key, False))
    ]
    if unsupported_enabled:
        raise ValueError(
            "small exact oracle v1 has unsupported enabled cost components: "
            + ", ".join(sorted(unsupported_enabled))
        )


def _evaluate_candidate(
    problem: CanonicalOptimizationProblem,
    *,
    trips: Sequence[ProblemTrip],
    vehicle_by_id: Mapping[str, ProblemVehicle],
    assignment_by_trip: Mapping[str, str],
) -> _CandidateEvaluation | None:
    paths: dict[str, list[ProblemTrip]] = {}
    for trip in trips:
        vehicle_id = str(assignment_by_trip[str(trip.trip_id)])
        paths.setdefault(vehicle_id, []).append(trip)

    total_fuel_l = 0.0
    inter_trip_deadhead_km = 0.0
    used_vehicle_days: set[tuple[str, int]] = set()
    for vehicle_id, path in paths.items():
        vehicle = vehicle_by_id[vehicle_id]
        ordered_path = sorted(
            path,
            key=lambda trip: (
                int(trip.departure_min),
                int(trip.arrival_min),
                str(trip.trip_id),
            ),
        )
        startup_deadhead = _required_deadhead_min(
            problem,
            str(vehicle.home_depot_id),
            str(ordered_path[0].origin),
        )
        if startup_deadhead is None:
            return None
        horizon_start = int(problem.metadata.get("horizon_start_min") or 0)
        if horizon_start + startup_deadhead > int(ordered_path[0].departure_min):
            return None
        total_fuel_l += _deadhead_fuel_l(problem, vehicle, startup_deadhead)

        for index, trip in enumerate(ordered_path):
            used_vehicle_days.add(
                (
                    vehicle_id,
                    day_index_for_minute(
                        int(trip.departure_min),
                        horizon_start,
                    ),
                )
            )
            total_fuel_l += _trip_fuel_l(trip, vehicle)
            if index == 0:
                continue
            previous = ordered_path[index - 1]
            if str(trip.trip_id) not in set(
                problem.feasible_connections.get(str(previous.trip_id), ())
            ):
                return None
            deadhead_min = _required_deadhead_min(
                problem,
                str(previous.destination),
                str(trip.origin),
            )
            if deadhead_min is None:
                return None
            deadhead_km = _deadhead_distance_km(problem, deadhead_min)
            inter_trip_deadhead_km += deadhead_km
            total_fuel_l += deadhead_km * max(
                float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0
            )

        return_deadhead = _required_deadhead_min(
            problem,
            str(ordered_path[-1].destination),
            str(vehicle.home_depot_id),
        )
        if return_deadhead is None:
            return None
        total_fuel_l += _deadhead_fuel_l(problem, vehicle, return_deadhead)
        initial_fuel_l = float(
            vehicle.initial_fuel_l
            if vehicle.initial_fuel_l is not None
            else vehicle.fuel_tank_capacity_l
            or 0.0
        )
        reserve_fuel_l = max(float(vehicle.fuel_reserve_l or 0.0), 0.0)
        vehicle_path_fuel = _path_fuel_l(problem, vehicle, ordered_path)
        if initial_fuel_l - vehicle_path_fuel + 1.0e-9 < reserve_fuel_l:
            return None

    fuel_cost_jpy = (
        max(float(problem.objective_weights.fuel), 0.0)
        * max(float(problem.scenario.diesel_price_yen_per_l), 0.0)
        * total_fuel_l
    )
    component_flags = dict(problem.metadata.get("cost_component_flags") or {})
    fixed_vehicle_cost = 0.0
    if bool(component_flags.get("vehicle_fixed_cost", True)):
        fixed_vehicle_cost = max(float(problem.objective_weights.vehicle), 0.0) * sum(
            max(float(vehicle_by_id[vehicle_id].fixed_use_cost_jpy or 0.0), 0.0)
            for vehicle_id in paths
        )
    vehicle_day_cost = 0.0
    if bool(component_flags.get("vehicle_usage_cost", True)):
        vehicle_day_cost = (
            max(float(problem.objective_weights.vehicle_usage), 0.0)
            * max(
                float(
                    problem.metadata.get(
                        "vehicle_usage_cost_jpy_per_used_bus", 0.0
                    )
                    or 0.0
                ),
                0.0,
            )
            * len(used_vehicle_days)
        )
    canonical_cost = fuel_cost_jpy + fixed_vehicle_cost + vehicle_day_cost
    return _CandidateEvaluation(
        assignment_by_trip=dict(assignment_by_trip),
        used_vehicle_day_count=len(used_vehicle_days),
        canonical_operating_cost_jpy=canonical_cost,
        fuel_l=total_fuel_l,
        fuel_cost_jpy=fuel_cost_jpy,
        inter_trip_deadhead_km=inter_trip_deadhead_km,
    )


def _path_fuel_l(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
    path: Sequence[ProblemTrip],
) -> float:
    total = 0.0
    startup = _required_deadhead_min(
        problem, str(vehicle.home_depot_id), str(path[0].origin)
    )
    if startup is None:
        return float("inf")
    total += _deadhead_fuel_l(problem, vehicle, startup)
    for index, trip in enumerate(path):
        total += _trip_fuel_l(trip, vehicle)
        if index > 0:
            deadhead = _required_deadhead_min(
                problem, str(path[index - 1].destination), str(trip.origin)
            )
            if deadhead is None:
                return float("inf")
            total += _deadhead_fuel_l(problem, vehicle, deadhead)
    return_deadhead = _required_deadhead_min(
        problem, str(path[-1].destination), str(vehicle.home_depot_id)
    )
    if return_deadhead is None:
        return float("inf")
    return total + _deadhead_fuel_l(problem, vehicle, return_deadhead)


def _trip_fuel_l(trip: ProblemTrip, vehicle: ProblemVehicle) -> float:
    quantities = dict(getattr(trip, "fuel_l_by_vehicle_type", {}) or {})
    for key in (str(vehicle.vehicle_type), str(vehicle.vehicle_type).upper()):
        if key in quantities:
            return max(float(quantities[key] or 0.0), 0.0)
    fuel_rate = max(float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0)
    if fuel_rate > 0.0:
        return max(float(trip.distance_km or 0.0), 0.0) * fuel_rate
    return max(float(trip.fuel_l or 0.0), 0.0)


def _required_deadhead_min(
    problem: CanonicalOptimizationProblem,
    from_location: str,
    to_location: str,
) -> int | None:
    context = problem.dispatch_context
    if context.locations_equivalent(from_location, to_location):
        return 0
    minutes = max(int(context.get_deadhead_min(from_location, to_location) or 0), 0)
    return minutes if minutes > 0 else None


def _deadhead_distance_km(
    problem: CanonicalOptimizationProblem,
    deadhead_min: int,
) -> float:
    speed_kmh = max(
        float(problem.metadata.get("deadhead_speed_kmh", 18.0) or 18.0), 0.0
    )
    return max(float(deadhead_min), 0.0) * speed_kmh / 60.0


def _deadhead_fuel_l(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
    deadhead_min: int,
) -> float:
    return _deadhead_distance_km(problem, deadhead_min) * max(
        float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0
    )


def _assignment_plan(
    problem: CanonicalOptimizationProblem,
    *,
    trips: Sequence[ProblemTrip],
    assignment_by_trip: Mapping[str, str],
) -> AssignmentPlan:
    dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
    vehicle_by_id = {
        str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles
    }
    grouped: dict[str, list[ProblemTrip]] = {}
    for trip in trips:
        grouped.setdefault(str(assignment_by_trip[str(trip.trip_id)]), []).append(trip)
    duties: list[VehicleDuty] = []
    duty_vehicle_map: dict[str, str] = {}
    for vehicle_id, path in sorted(grouped.items()):
        vehicle = vehicle_by_id[vehicle_id]
        ordered = sorted(
            path,
            key=lambda trip: (
                int(trip.departure_min),
                int(trip.arrival_min),
                str(trip.trip_id),
            ),
        )
        legs: list[DutyLeg] = []
        previous: ProblemTrip | None = None
        for trip in ordered:
            deadhead_min = 0
            if previous is not None:
                deadhead_min = int(
                    problem.dispatch_context.get_deadhead_min(
                        str(previous.destination), str(trip.origin)
                    )
                    or 0
                )
            legs.append(
                DutyLeg(
                    trip=dispatch_trip_by_id[str(trip.trip_id)],
                    deadhead_from_prev_min=deadhead_min,
                )
            )
            previous = trip
        duty_id = f"oracle_{vehicle_id}"
        duties.append(
            VehicleDuty(
                duty_id=duty_id,
                vehicle_type=str(vehicle.vehicle_type),
                legs=tuple(legs),
            )
        )
        duty_vehicle_map[duty_id] = vehicle_id
    served = tuple(sorted(str(trip.trip_id) for trip in trips))
    return AssignmentPlan(
        duties=tuple(duties),
        served_trip_ids=served,
        unserved_trip_ids=(),
        metadata={
            "source": "small_exact_assignment_oracle_v1",
            "duty_vehicle_map": duty_vehicle_map,
        },
    )
