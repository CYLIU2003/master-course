"""Independent exact oracle for bounded grid-only BEV/ICE cases.

The production Gurobi model must not certify itself.  This module therefore
uses complete Cartesian trip-to-vehicle enumeration and a separate SciPy/
HiGHS mixed-integer charging subproblem.  The scope is intentionally narrow:
one depot, one day, zero PV, zero BESS, flat grid tariff, constant-power
charging, depot-to-depot trips, and return-to-initial BEV SOC.  Unsupported
physics fail closed instead of being approximated.

Within that scope the oracle is exact.  Assignment is completely enumerated;
each fixed assignment optimizes grid charging with binary charger-port use,
slot SOC bounds, departure readiness, terminal SOC equality, vehicle charge
power, charger concurrency, and the depot import limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    ProblemTrip,
    ProblemVehicle,
    day_index_for_minute,
    normalize_service_coverage_mode,
)


MAX_EXACT_TRIPS = 10
MAX_EXACT_ASSIGNMENTS = 1_000_000
CHARGE_EFFICIENCY = 0.95
TOLERANCE = 1.0e-7
_ELECTRIC_POWERTRAINS = frozenset({"BEV"})


class SmallElectricOracleInfeasibleError(ValueError):
    """Raised when exhaustive enumeration finds no physically feasible plan."""

    def __init__(
        self,
        message: str,
        *,
        enumerated_assignment_count: int,
        dispatch_feasible_assignment_count: int,
        energy_feasible_assignment_count: int,
    ) -> None:
        super().__init__(message)
        self.enumerated_assignment_count = int(enumerated_assignment_count)
        self.dispatch_feasible_assignment_count = int(
            dispatch_feasible_assignment_count
        )
        self.energy_feasible_assignment_count = int(
            energy_feasible_assignment_count
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": "small_exact_electric_oracle_v1",
            "status": "INFEASIBLE",
            "assignment_enumeration_complete": True,
            "enumerated_assignment_count": self.enumerated_assignment_count,
            "dispatch_feasible_assignment_count": (
                self.dispatch_feasible_assignment_count
            ),
            "energy_feasible_assignment_count": (
                self.energy_feasible_assignment_count
            ),
            "message": str(self),
        }


@dataclass(frozen=True)
class SmallElectricOracleResult:
    assignment_by_trip: Mapping[str, str]
    plan: AssignmentPlan
    enumerated_assignment_count: int
    dispatch_feasible_assignment_count: int
    energy_feasible_assignment_count: int
    used_vehicle_day_count: int
    canonical_operating_cost_jpy: float
    electricity_cost_jpy: float
    fuel_cost_jpy: float
    grid_import_kwh: float
    fuel_l: float
    terminal_soc_kwh_by_vehicle: Mapping[str, float]
    objective_tuple: tuple[float, float, float]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": "small_exact_electric_oracle_v1",
            "status": "OPTIMAL",
            "method": (
                "complete_assignment_enumeration_plus_scipy_highs_milp_"
                "charging"
            ),
            "scope": (
                "strict_single_day_one_depot_zero_pv_zero_bess_flat_tariff_"
                "constant_power_return_to_initial_max_10_trips"
            ),
            "assignment_enumeration_complete": True,
            "charging_subproblem_global_optimality": "SCIPY_HIGHS_OPTIMAL",
            "enumerated_assignment_count": self.enumerated_assignment_count,
            "dispatch_feasible_assignment_count": (
                self.dispatch_feasible_assignment_count
            ),
            "energy_feasible_assignment_count": (
                self.energy_feasible_assignment_count
            ),
            "used_vehicle_day_count": self.used_vehicle_day_count,
            "canonical_operating_cost_jpy": self.canonical_operating_cost_jpy,
            "electricity_cost_jpy": self.electricity_cost_jpy,
            "fuel_cost_jpy": self.fuel_cost_jpy,
            "grid_import_kwh": self.grid_import_kwh,
            "fuel_l": self.fuel_l,
            "terminal_soc_kwh_by_vehicle": dict(
                sorted(self.terminal_soc_kwh_by_vehicle.items())
            ),
            "objective_tuple": list(self.objective_tuple),
            "assignment_by_trip": dict(sorted(self.assignment_by_trip.items())),
        }


@dataclass(frozen=True)
class _CandidateEvaluation:
    assignment_by_trip: Mapping[str, str]
    plan: AssignmentPlan
    used_vehicle_day_count: int
    canonical_operating_cost_jpy: float
    electricity_cost_jpy: float
    fuel_cost_jpy: float
    grid_import_kwh: float
    fuel_l: float
    terminal_soc_kwh_by_vehicle: Mapping[str, float]

    @property
    def objective_tuple(self) -> tuple[float, float, float]:
        return (
            float(self.used_vehicle_day_count),
            float(self.canonical_operating_cost_jpy),
            0.0,
        )


@dataclass(frozen=True)
class _ElectricSubproblemResult:
    charge_input_kwh_by_vehicle_slot: Mapping[tuple[str, int], float]
    soc_start_kwh_by_vehicle_slot: Mapping[str, Mapping[int, float]]
    terminal_soc_kwh_by_vehicle: Mapping[str, float]
    electricity_cost_jpy: float
    grid_import_kwh: float


def solve_small_exact_electric_oracle(
    problem: CanonicalOptimizationProblem,
    *,
    max_trips: int = MAX_EXACT_TRIPS,
    max_assignments: int = MAX_EXACT_ASSIGNMENTS,
) -> SmallElectricOracleResult:
    """Return the globally best plan inside the documented bounded scope."""

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
    _validate_supported_problem(
        problem,
        trips=trips,
        vehicles=vehicles,
        max_trips=max_trips,
    )

    eligible_vehicle_ids_by_trip: list[tuple[str, ...]] = []
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in vehicles}
    for trip in trips:
        allowed = {str(value).upper() for value in trip.allowed_vehicle_types}
        eligible = tuple(
            str(vehicle.vehicle_id)
            for vehicle in vehicles
            if str(vehicle.vehicle_type).upper() in allowed
        )
        if not eligible:
            raise ValueError(
                f"small electric oracle trip {trip.trip_id!r} has no compatible vehicle"
            )
        eligible_vehicle_ids_by_trip.append(eligible)

    _validate_assignment_space(
        eligible_vehicle_ids_by_trip,
        max_assignments=max_assignments,
    )

    best: _CandidateEvaluation | None = None
    best_signature = ""
    enumerated = 0
    dispatch_feasible = 0
    energy_feasible = 0
    for selected_vehicle_ids in product(*eligible_vehicle_ids_by_trip):
        enumerated += 1
        assignment = {
            str(trip.trip_id): str(vehicle_id)
            for trip, vehicle_id in zip(trips, selected_vehicle_ids)
        }
        paths = _dispatch_feasible_paths(
            problem,
            trips=trips,
            vehicle_by_id=vehicle_by_id,
            assignment_by_trip=assignment,
        )
        if paths is None:
            continue
        dispatch_feasible += 1
        candidate = _evaluate_candidate(
            problem,
            trips=trips,
            vehicle_by_id=vehicle_by_id,
            assignment_by_trip=assignment,
            paths=paths,
        )
        if candidate is None:
            continue
        energy_feasible += 1
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
        raise SmallElectricOracleInfeasibleError(
            "small electric oracle found no feasible complete assignment",
            enumerated_assignment_count=enumerated,
            dispatch_feasible_assignment_count=dispatch_feasible,
            energy_feasible_assignment_count=energy_feasible,
        )
    return SmallElectricOracleResult(
        assignment_by_trip=dict(best.assignment_by_trip),
        plan=best.plan,
        enumerated_assignment_count=enumerated,
        dispatch_feasible_assignment_count=dispatch_feasible,
        energy_feasible_assignment_count=energy_feasible,
        used_vehicle_day_count=best.used_vehicle_day_count,
        canonical_operating_cost_jpy=best.canonical_operating_cost_jpy,
        electricity_cost_jpy=best.electricity_cost_jpy,
        fuel_cost_jpy=best.fuel_cost_jpy,
        grid_import_kwh=best.grid_import_kwh,
        fuel_l=best.fuel_l,
        terminal_soc_kwh_by_vehicle=dict(best.terminal_soc_kwh_by_vehicle),
        objective_tuple=best.objective_tuple,
    )


def _validate_assignment_space(
    eligible_vehicle_ids_by_trip: Sequence[Sequence[str]],
    *,
    max_assignments: int,
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
                "small electric oracle assignment space "
                f"{assignment_count} exceeds hard limit {hard_limit}"
            )


def _validate_supported_problem(
    problem: CanonicalOptimizationProblem,
    *,
    trips: Sequence[ProblemTrip],
    vehicles: Sequence[ProblemVehicle],
    max_trips: int,
) -> None:
    limit = min(max(int(max_trips), 1), MAX_EXACT_TRIPS)
    if not trips or len(trips) > limit:
        raise ValueError(f"small electric oracle requires 1..{limit} trips")
    if not vehicles:
        raise ValueError("small electric oracle requires an available fleet")
    unsupported_powertrains = sorted(
        {
            str(vehicle.vehicle_type).upper()
            for vehicle in vehicles
            if str(vehicle.vehicle_type).upper()
            not in (_ELECTRIC_POWERTRAINS | {"ICE"})
        }
    )
    if unsupported_powertrains:
        raise ValueError(
            "small electric oracle supports only BEV and ICE: "
            + ", ".join(unsupported_powertrains)
        )
    if normalize_service_coverage_mode(problem.scenario.service_coverage_mode) != (
        "strict"
    ):
        raise ValueError("small electric oracle requires strict coverage")
    if str(problem.scenario.objective_mode or "").strip().lower() != "total_cost":
        raise ValueError("small electric oracle requires objective_mode=total_cost")
    if str(problem.metadata.get("objective_preset") or "").strip() != (
        "research_lexicographic_v1"
    ):
        raise ValueError(
            "small electric oracle requires objective_preset="
            "research_lexicographic_v1"
        )
    if int(problem.scenario.planning_days or 1) != 1:
        raise ValueError("small electric oracle supports one service day")
    diesel_price = float(problem.scenario.diesel_price_yen_per_l or 0.0)
    if not math.isfinite(diesel_price) or diesel_price < 0.0:
        raise ValueError(
            "small electric oracle requires finite non-negative diesel price"
        )
    if str(problem.metadata.get("charging_power_model") or "").strip() != (
        "constant_power_v0"
    ):
        raise ValueError("small electric oracle requires constant_power_v0")
    if str(problem.metadata.get("bev_terminal_soc_policy") or "").strip() != (
        "return_to_initial"
    ):
        raise ValueError(
            "small electric oracle requires bev_terminal_soc_policy="
            "return_to_initial"
        )
    if bool(problem.metadata.get("allow_soc_violation_slack", False)):
        raise ValueError("small electric oracle forbids SOC slack")
    nonzero_bess = any(
        bool(getattr(asset, "bess_enabled", False))
        or any(
            abs(float(value or 0.0)) > TOLERANCE
            for value in (
                getattr(asset, "bess_energy_kwh", 0.0),
                getattr(asset, "bess_power_kw", 0.0),
                getattr(asset, "bess_initial_soc_kwh", 0.0),
                getattr(asset, "bess_soc_min_kwh", 0.0),
                getattr(asset, "bess_soc_max_kwh", 0.0),
                getattr(asset, "bess_terminal_soc_min_kwh", 0.0),
                getattr(asset, "bess_terminal_soc_target_kwh", 0.0),
            )
        )
        for asset in problem.depot_energy_assets.values()
    )
    if nonzero_bess:
        raise ValueError("small electric oracle requires BESS=0")
    nonzero_pv = any(
        bool(getattr(asset, "pv_enabled", False))
        or abs(float(getattr(asset, "pv_capacity_kw", 0.0) or 0.0))
        > TOLERANCE
        or any(
            abs(float(value or 0.0)) > TOLERANCE
            for value in tuple(asset.available_pv_surplus_kwh_by_slot or ())
            + tuple(asset.pv_generation_kwh_by_slot or ())
            + tuple(asset.capacity_factor_by_slot or ())
        )
        for asset in problem.depot_energy_assets.values()
    )
    if nonzero_pv or any(
        abs(float(getattr(slot, "pv_available_kw", 0.0) or 0.0)) > TOLERANCE
        for slot in problem.pv_slots
    ):
        raise ValueError("small electric oracle requires PV=0")

    raw_prices = tuple(
        float(slot.grid_buy_yen_per_kwh or 0.0) for slot in problem.price_slots
    )
    if any(not math.isfinite(value) or value < 0.0 for value in raw_prices):
        raise ValueError("small electric oracle requires finite non-negative tariff")
    prices = {round(value, 9) for value in raw_prices}
    if not prices or len(prices) != 1:
        raise ValueError("small electric oracle requires one flat grid tariff")
    if not problem.price_slots:
        raise ValueError("small electric oracle requires time slots")
    expected_slots = tuple(range(len(problem.price_slots)))
    actual_slots = tuple(sorted(int(slot.slot_index) for slot in problem.price_slots))
    if actual_slots != expected_slots:
        raise ValueError("small electric oracle requires contiguous slots from zero")

    depot_ids = {str(vehicle.home_depot_id or "") for vehicle in vehicles}
    depot_ids.update(str(depot.depot_id or "") for depot in problem.depots)
    depot_ids.discard("")
    if len(depot_ids) != 1:
        raise ValueError("small electric oracle requires exactly one depot")
    depot_id = next(iter(depot_ids))
    timestep = max(int(problem.scenario.timestep_min), 1)
    horizon_start = _horizon_start_min(problem)
    for trip in trips:
        distance_km = float(trip.distance_km or 0.0)
        if not math.isfinite(distance_km) or distance_km < 0.0:
            raise ValueError(
                "small electric oracle requires finite non-negative trip distance"
            )
        if str(trip.origin) != depot_id or str(trip.destination) != depot_id:
            raise ValueError(
                "small electric oracle requires depot-to-depot trips"
            )
        if (
            (int(trip.departure_min) - horizon_start) % timestep != 0
            or (int(trip.arrival_min) - horizon_start) % timestep != 0
        ):
            raise ValueError(
                "small electric oracle requires slot-boundary trip times"
            )
    if any(tuple(vehicle.compatible_charger_ids or ()) for vehicle in vehicles):
        raise ValueError(
            "small electric oracle does not support charger-ID compatibility"
        )
    for vehicle in vehicles:
        if _is_electric(vehicle):
            required_values = {
                "battery_capacity_kwh": vehicle.battery_capacity_kwh,
                "initial_soc": vehicle.initial_soc,
                "reserve_soc": vehicle.reserve_soc,
                "energy_consumption_kwh_per_km": (
                    vehicle.energy_consumption_kwh_per_km
                ),
                "charge_power_max_kw": vehicle.charge_power_max_kw,
            }
            invalid = [
                key
                for key, value in required_values.items()
                if value is None
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ]
            if invalid or float(vehicle.battery_capacity_kwh or 0.0) <= 0.0:
                raise ValueError(
                    f"small electric oracle BEV {vehicle.vehicle_id!r} has "
                    "missing/invalid fields: "
                    + ", ".join(sorted(invalid or {"battery_capacity_kwh"}))
                )
        else:
            required_values = {
                "fuel_tank_capacity_l": vehicle.fuel_tank_capacity_l,
                "initial_fuel_l": vehicle.initial_fuel_l,
                "fuel_reserve_l": vehicle.fuel_reserve_l,
                "fuel_consumption_l_per_km": (
                    vehicle.fuel_consumption_l_per_km
                ),
            }
            invalid = [
                key
                for key, value in required_values.items()
                if value is None
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ]
            if invalid or float(vehicle.fuel_tank_capacity_l or 0.0) <= 0.0:
                raise ValueError(
                    f"small electric oracle ICE {vehicle.vehicle_id!r} has "
                    "missing/invalid fields: "
                    + ", ".join(sorted(invalid or {"fuel_tank_capacity_l"}))
                )
    charger_powers = {
        round(float(charger.power_kw or 0.0), 9)
        for charger in problem.chargers
        if str(charger.depot_id or "") == depot_id
    }
    if len(charger_powers) > 1:
        raise ValueError("small electric oracle requires homogeneous chargers")
    if any(
        str(charger.depot_id or "") != depot_id for charger in problem.chargers
    ):
        raise ValueError("small electric oracle forbids other-depot chargers")
    if any(
        not math.isfinite(float(charger.power_kw or 0.0))
        or float(charger.power_kw or 0.0) <= 0.0
        or int(charger.simultaneous_ports or 0) <= 0
        for charger in problem.chargers
    ):
        raise ValueError(
            "small electric oracle requires positive finite charger capacity"
        )

    component_flags = dict(problem.metadata.get("cost_component_flags") or {})
    required_enabled = [
        key
        for key in ("electricity_cost", "fuel_cost")
        if not bool(component_flags.get(key, True))
    ]
    if required_enabled:
        raise ValueError(
            "small electric oracle requires enabled cost components: "
            + ", ".join(sorted(required_enabled))
        )
    supported_enabled = {
        "electricity_cost",
        "fuel_cost",
        "vehicle_fixed_cost",
        "vehicle_usage_cost",
        # Strict coverage makes this term identically zero.
        "unserved_penalty",
    }
    unsupported_enabled = [
        key
        for key, enabled in component_flags.items()
        if bool(enabled) and key not in supported_enabled
    ]
    if unsupported_enabled:
        raise ValueError(
            "small electric oracle has unsupported enabled cost components: "
            + ", ".join(sorted(unsupported_enabled))
        )
    relevant_weights = {
        "energy": problem.objective_weights.energy,
        "fuel": problem.objective_weights.fuel,
        "vehicle": problem.objective_weights.vehicle,
        "vehicle_usage": problem.objective_weights.vehicle_usage,
    }
    nonunit = [
        key
        for key, value in relevant_weights.items()
        if abs(float(value) - 1.0) > TOLERANCE
    ]
    if nonunit:
        raise ValueError(
            "small electric oracle requires unit accounting weights: "
            + ", ".join(sorted(nonunit))
        )


def _dispatch_feasible_paths(
    problem: CanonicalOptimizationProblem,
    *,
    trips: Sequence[ProblemTrip],
    vehicle_by_id: Mapping[str, ProblemVehicle],
    assignment_by_trip: Mapping[str, str],
) -> dict[str, tuple[ProblemTrip, ...]] | None:
    grouped: dict[str, list[ProblemTrip]] = {}
    for trip in trips:
        grouped.setdefault(
            str(assignment_by_trip[str(trip.trip_id)]), []
        ).append(trip)
    result: dict[str, tuple[ProblemTrip, ...]] = {}
    horizon_start = _horizon_start_min(problem)
    for vehicle_id, path in grouped.items():
        vehicle = vehicle_by_id[vehicle_id]
        ordered = tuple(
            sorted(
                path,
                key=lambda trip: (
                    int(trip.departure_min),
                    int(trip.arrival_min),
                    str(trip.trip_id),
                ),
            )
        )
        if int(ordered[0].departure_min) < horizon_start:
            return None
        for previous, current in zip(ordered, ordered[1:]):
            if str(current.trip_id) not in set(
                problem.feasible_connections.get(str(previous.trip_id), ())
            ):
                return None
        if _is_electric(vehicle):
            capacity = _vehicle_capacity_kwh(problem, vehicle)
            initial = _vehicle_initial_soc_kwh(vehicle, capacity)
            reserve = _vehicle_reserve_kwh(vehicle, capacity)
            if capacity <= 0.0 or not (reserve <= initial <= capacity):
                return None
        else:
            fuel_required = sum(_trip_fuel_l(trip, vehicle) for trip in ordered)
            initial_fuel = float(
                vehicle.initial_fuel_l
                if vehicle.initial_fuel_l is not None
                else vehicle.fuel_tank_capacity_l
                or 0.0
            )
            if initial_fuel - fuel_required + TOLERANCE < max(
                float(vehicle.fuel_reserve_l or 0.0), 0.0
            ):
                return None
        result[vehicle_id] = ordered
    return result


def _evaluate_candidate(
    problem: CanonicalOptimizationProblem,
    *,
    trips: Sequence[ProblemTrip],
    vehicle_by_id: Mapping[str, ProblemVehicle],
    assignment_by_trip: Mapping[str, str],
    paths: Mapping[str, Sequence[ProblemTrip]],
) -> _CandidateEvaluation | None:
    electric_paths = {
        vehicle_id: tuple(path)
        for vehicle_id, path in paths.items()
        if _is_electric(vehicle_by_id[vehicle_id])
    }
    electric = _solve_electric_subproblem(
        problem,
        vehicle_by_id=vehicle_by_id,
        paths=electric_paths,
    )
    if electric is None:
        return None

    fuel_l = sum(
        _trip_fuel_l(trip, vehicle_by_id[vehicle_id])
        for vehicle_id, path in paths.items()
        if not _is_electric(vehicle_by_id[vehicle_id])
        for trip in path
    )
    fuel_cost = fuel_l * max(
        float(problem.scenario.diesel_price_yen_per_l or 0.0), 0.0
    )
    used_vehicle_days = {
        (
            vehicle_id,
            day_index_for_minute(
                int(trip.departure_min),
                _horizon_start_min(problem),
            ),
        )
        for vehicle_id, path in paths.items()
        for trip in path
    }
    flags = dict(problem.metadata.get("cost_component_flags") or {})
    fixed_cost = (
        sum(
            max(float(vehicle_by_id[vehicle_id].fixed_use_cost_jpy or 0.0), 0.0)
            for vehicle_id in paths
        )
        if bool(flags.get("vehicle_fixed_cost", True))
        else 0.0
    )
    vehicle_day_cost = (
        max(
            float(
                problem.metadata.get(
                    "vehicle_usage_cost_jpy_per_used_bus", 0.0
                )
                or 0.0
            ),
            0.0,
        )
        * len(used_vehicle_days)
        if bool(flags.get("vehicle_usage_cost", True))
        else 0.0
    )
    canonical_cost = (
        electric.electricity_cost_jpy
        + fuel_cost
        + fixed_cost
        + vehicle_day_cost
    )
    plan = _assignment_plan(
        problem,
        trips=trips,
        vehicle_by_id=vehicle_by_id,
        assignment_by_trip=assignment_by_trip,
        paths=paths,
        electric=electric,
    )
    return _CandidateEvaluation(
        assignment_by_trip=dict(assignment_by_trip),
        plan=plan,
        used_vehicle_day_count=len(used_vehicle_days),
        canonical_operating_cost_jpy=canonical_cost,
        electricity_cost_jpy=electric.electricity_cost_jpy,
        fuel_cost_jpy=fuel_cost,
        grid_import_kwh=electric.grid_import_kwh,
        fuel_l=fuel_l,
        terminal_soc_kwh_by_vehicle=dict(
            electric.terminal_soc_kwh_by_vehicle
        ),
    )


def _solve_electric_subproblem(
    problem: CanonicalOptimizationProblem,
    *,
    vehicle_by_id: Mapping[str, ProblemVehicle],
    paths: Mapping[str, Sequence[ProblemTrip]],
) -> _ElectricSubproblemResult | None:
    if not paths:
        return _ElectricSubproblemResult({}, {}, {}, 0.0, 0.0)
    slot_indices = tuple(
        sorted(int(slot.slot_index) for slot in problem.price_slots)
    )
    vehicle_ids = tuple(sorted(paths))
    timestep_h = max(int(problem.scenario.timestep_min), 1) / 60.0
    price = max(float(problem.price_slots[0].grid_buy_yen_per_kwh or 0.0), 0.0)
    depot_id = str(vehicle_by_id[vehicle_ids[0]].home_depot_id)
    depot = next(
        (item for item in problem.depots if str(item.depot_id) == depot_id),
        None,
    )
    import_limit_kw = max(float(getattr(depot, "import_limit_kw", 0.0) or 0.0), 0.0)
    chargers = tuple(
        charger
        for charger in problem.chargers
        if str(charger.depot_id) == depot_id
    )
    charger_power_kw = max(
        (float(charger.power_kw or 0.0) for charger in chargers),
        default=0.0,
    )
    port_count = sum(max(int(charger.simultaneous_ports or 1), 1) for charger in chargers)

    variable_keys = tuple(
        (vehicle_id, slot_idx)
        for vehicle_id in vehicle_ids
        for slot_idx in slot_indices
    )
    charge_index = {key: index for index, key in enumerate(variable_keys)}
    on_offset = len(variable_keys)
    variable_count = 2 * len(variable_keys)
    objective = np.zeros(variable_count, dtype=float)
    objective[:on_offset] = price
    integrality = np.zeros(variable_count, dtype=int)
    integrality[on_offset:] = 1
    lower = np.zeros(variable_count, dtype=float)
    upper = np.ones(variable_count, dtype=float)
    upper[:on_offset] = 0.0

    load_by_vehicle_slot: dict[tuple[str, int], float] = {}
    trip_energy_by_vehicle_trip: dict[tuple[str, str], float] = {}
    active_by_vehicle_slot: set[tuple[str, int]] = set()
    capacity_by_vehicle: dict[str, float] = {}
    initial_by_vehicle: dict[str, float] = {}
    reserve_by_vehicle: dict[str, float] = {}
    for vehicle_id, path in paths.items():
        vehicle = vehicle_by_id[vehicle_id]
        capacity = _vehicle_capacity_kwh(problem, vehicle)
        capacity_by_vehicle[vehicle_id] = capacity
        initial_by_vehicle[vehicle_id] = _vehicle_initial_soc_kwh(
            vehicle, capacity
        )
        reserve_by_vehicle[vehicle_id] = _vehicle_reserve_kwh(vehicle, capacity)
        max_power_kw = min(
            max(float(vehicle.charge_power_max_kw or 0.0), 0.0),
            charger_power_kw,
        )
        for slot_idx in slot_indices:
            key = (vehicle_id, slot_idx)
            active = any(
                _trip_active_in_slot(problem, trip, slot_idx) for trip in path
            )
            if active:
                active_by_vehicle_slot.add(key)
            max_input = 0.0 if active else max_power_kw * timestep_h
            upper[charge_index[key]] = max_input
            upper[on_offset + charge_index[key]] = 1.0 if max_input > 0.0 else 0.0
        for trip in path:
            energy = _trip_energy_kwh(trip, vehicle)
            trip_energy_by_vehicle_trip[(vehicle_id, str(trip.trip_id))] = energy
            for slot_idx in slot_indices:
                fraction = _trip_slot_fraction(problem, trip, slot_idx)
                if fraction <= 0.0:
                    continue
                key = (vehicle_id, slot_idx)
                load_by_vehicle_slot[key] = (
                    load_by_vehicle_slot.get(key, 0.0) + energy * fraction
                )

    rows: list[np.ndarray] = []
    row_lower: list[float] = []
    row_upper: list[float] = []

    def add_row(
        coefficients: Mapping[int, float],
        minimum: float,
        maximum: float,
    ) -> None:
        row = np.zeros(variable_count, dtype=float)
        for index, coefficient in coefficients.items():
            row[int(index)] = float(coefficient)
        rows.append(row)
        row_lower.append(float(minimum))
        row_upper.append(float(maximum))

    for key, index in charge_index.items():
        max_input = float(upper[index])
        add_row(
            {index: 1.0, on_offset + index: -max_input},
            -np.inf,
            0.0,
        )
    for slot_idx in slot_indices:
        add_row(
            {
                on_offset + charge_index[(vehicle_id, slot_idx)]: 1.0
                for vehicle_id in vehicle_ids
            },
            -np.inf,
            float(port_count),
        )
        if import_limit_kw > 0.0:
            add_row(
                {
                    charge_index[(vehicle_id, slot_idx)]: 1.0
                    for vehicle_id in vehicle_ids
                },
                -np.inf,
                import_limit_kw * timestep_h,
            )

    for vehicle_id, path in paths.items():
        initial = initial_by_vehicle[vehicle_id]
        reserve = reserve_by_vehicle[vehicle_id]
        capacity = capacity_by_vehicle[vehicle_id]
        cumulative_load = 0.0
        previous_charge_indices: list[int] = []
        for slot_idx in slot_indices:
            coefficients = {
                index: CHARGE_EFFICIENCY for index in previous_charge_indices
            }
            add_row(
                coefficients,
                reserve - initial + cumulative_load,
                capacity - initial + cumulative_load,
            )
            for trip in path:
                if _slot_index(problem, int(trip.departure_min)) != slot_idx:
                    continue
                required = (
                    reserve
                    + trip_energy_by_vehicle_trip[
                        (vehicle_id, str(trip.trip_id))
                    ]
                )
                add_row(
                    coefficients,
                    required - initial + cumulative_load,
                    np.inf,
                )
            cumulative_load += load_by_vehicle_slot.get(
                (vehicle_id, slot_idx), 0.0
            )
            previous_charge_indices.append(
                charge_index[(vehicle_id, slot_idx)]
            )
        # return_to_initial: eta * total grid input equals total traction load.
        add_row(
            {
                charge_index[(vehicle_id, slot_idx)]: CHARGE_EFFICIENCY
                for slot_idx in slot_indices
            },
            cumulative_load,
            cumulative_load,
        )

    constraints = LinearConstraint(
        np.vstack(rows),
        np.asarray(row_lower),
        np.asarray(row_upper),
    )
    result = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=constraints,
        options={"mip_rel_gap": 0.0, "presolve": True},
    )
    if not bool(result.success) or result.x is None:
        return None

    charge: dict[tuple[str, int], float] = {}
    soc_trace: dict[str, dict[int, float]] = {}
    terminal: dict[str, float] = {}
    for vehicle_id in vehicle_ids:
        soc = initial_by_vehicle[vehicle_id]
        soc_trace[vehicle_id] = {}
        for slot_idx in slot_indices:
            soc_trace[vehicle_id][slot_idx] = soc
            input_kwh = max(
                float(result.x[charge_index[(vehicle_id, slot_idx)]]), 0.0
            )
            if input_kwh > TOLERANCE:
                charge[(vehicle_id, slot_idx)] = input_kwh
            soc += CHARGE_EFFICIENCY * input_kwh
            soc -= load_by_vehicle_slot.get((vehicle_id, slot_idx), 0.0)
        terminal[vehicle_id] = soc
        if abs(soc - initial_by_vehicle[vehicle_id]) > 1.0e-5:
            raise AssertionError(
                f"independent oracle terminal SOC mismatch for {vehicle_id}: "
                f"{soc} != {initial_by_vehicle[vehicle_id]}"
            )
    grid_import = sum(charge.values())
    return _ElectricSubproblemResult(
        charge_input_kwh_by_vehicle_slot=charge,
        soc_start_kwh_by_vehicle_slot=soc_trace,
        terminal_soc_kwh_by_vehicle=terminal,
        electricity_cost_jpy=grid_import * price,
        grid_import_kwh=grid_import,
    )


def _assignment_plan(
    problem: CanonicalOptimizationProblem,
    *,
    trips: Sequence[ProblemTrip],
    vehicle_by_id: Mapping[str, ProblemVehicle],
    assignment_by_trip: Mapping[str, str],
    paths: Mapping[str, Sequence[ProblemTrip]],
    electric: _ElectricSubproblemResult,
) -> AssignmentPlan:
    dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
    duties: list[VehicleDuty] = []
    duty_vehicle_map: dict[str, str] = {}
    for vehicle_id, path in sorted(paths.items()):
        duty_id = f"electric_oracle_{vehicle_id}"
        duties.append(
            VehicleDuty(
                duty_id=duty_id,
                vehicle_type=str(vehicle_by_id[vehicle_id].vehicle_type),
                legs=tuple(
                    DutyLeg(
                        trip=dispatch_trip_by_id[str(trip.trip_id)],
                        deadhead_from_prev_min=0,
                    )
                    for trip in path
                ),
            )
        )
        duty_vehicle_map[duty_id] = vehicle_id

    expanded_ports = [
        str(charger.charger_id)
        for charger in sorted(problem.chargers, key=lambda item: str(item.charger_id))
        for _port_index in range(max(int(charger.simultaneous_ports or 1), 1))
    ]
    timestep_h = max(int(problem.scenario.timestep_min), 1) / 60.0
    charging_slots: list[ChargingSlot] = []
    grid_by_slot: dict[int, float] = {}
    charge_by_slot: dict[int, list[tuple[str, float]]] = {}
    for (vehicle_id, slot_idx), energy_kwh in (
        electric.charge_input_kwh_by_vehicle_slot.items()
    ):
        charge_by_slot.setdefault(int(slot_idx), []).append(
            (str(vehicle_id), float(energy_kwh))
        )
        grid_by_slot[int(slot_idx)] = (
            grid_by_slot.get(int(slot_idx), 0.0) + float(energy_kwh)
        )
    for slot_idx, rows in sorted(charge_by_slot.items()):
        if len(rows) > len(expanded_ports):
            raise AssertionError("oracle extracted more simultaneous charges than ports")
        for (vehicle_id, energy_kwh), charger_id in zip(
            sorted(rows), expanded_ports
        ):
            charging_slots.append(
                ChargingSlot(
                    vehicle_id=vehicle_id,
                    slot_index=slot_idx,
                    charger_id=charger_id,
                    charge_kw=energy_kwh / timestep_h,
                    charging_depot_id=str(
                        vehicle_by_id[vehicle_id].home_depot_id
                    ),
                    energy_source="grid",
                )
            )
    depot_id = str(next(iter(vehicle_by_id.values())).home_depot_id)
    return AssignmentPlan(
        duties=tuple(duties),
        charging_slots=tuple(charging_slots),
        grid_to_bus_kwh_by_depot_slot=(
            {depot_id: grid_by_slot} if grid_by_slot else {}
        ),
        pv_to_bus_kwh_by_depot_slot={},
        bess_to_bus_kwh_by_depot_slot={},
        pv_to_bess_kwh_by_depot_slot={},
        grid_to_bess_kwh_by_depot_slot={},
        pv_curtail_kwh_by_depot_slot={},
        bess_soc_kwh_by_depot_slot={},
        vehicle_soc_kwh_by_vehicle_slot={
            vehicle_id: dict(by_slot)
            for vehicle_id, by_slot in (
                electric.soc_start_kwh_by_vehicle_slot.items()
            )
        },
        served_trip_ids=tuple(sorted(str(trip.trip_id) for trip in trips)),
        unserved_trip_ids=(),
        metadata={
            "source": "small_exact_electric_oracle_v1",
            "duty_vehicle_map": duty_vehicle_map,
            "source_provenance_exact": True,
            "derived_source_split": False,
            "postsolve_repair_applied": False,
            "solver_objective_matches_accounting_total": True,
            "optimization_structure": "independent_exact_oracle",
            "bev_terminal_soc_target_kwh_by_vehicle": dict(
                electric.terminal_soc_kwh_by_vehicle
            ),
            "assignment_by_trip": dict(assignment_by_trip),
        },
    )


def _trip_energy_kwh(trip: ProblemTrip, vehicle: ProblemVehicle) -> float:
    values = dict(getattr(trip, "energy_kwh_by_vehicle_type", {}) or {})
    for key in (str(vehicle.vehicle_type), str(vehicle.vehicle_type).upper()):
        if key in values:
            return max(float(values[key] or 0.0), 0.0)
    rate = max(float(vehicle.energy_consumption_kwh_per_km or 0.0), 0.0)
    if rate > 0.0:
        return max(float(trip.distance_km or 0.0), 0.0) * rate
    return max(float(trip.energy_kwh or 0.0), 0.0)


def _trip_fuel_l(trip: ProblemTrip, vehicle: ProblemVehicle) -> float:
    values = dict(getattr(trip, "fuel_l_by_vehicle_type", {}) or {})
    for key in (str(vehicle.vehicle_type), str(vehicle.vehicle_type).upper()):
        if key in values:
            return max(float(values[key] or 0.0), 0.0)
    rate = max(float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0)
    if rate > 0.0:
        return max(float(trip.distance_km or 0.0), 0.0) * rate
    return max(float(trip.fuel_l or 0.0), 0.0)


def _vehicle_capacity_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
) -> float:
    if float(vehicle.battery_capacity_kwh or 0.0) > 0.0:
        return float(vehicle.battery_capacity_kwh)
    vehicle_type = next(
        (
            item
            for item in problem.vehicle_types
            if str(item.vehicle_type_id) == str(vehicle.vehicle_type)
        ),
        None,
    )
    return max(float(getattr(vehicle_type, "battery_capacity_kwh", 0.0) or 0.0), 0.0)


def _vehicle_initial_soc_kwh(
    vehicle: ProblemVehicle,
    capacity_kwh: float,
) -> float:
    value = float(
        vehicle.initial_soc if vehicle.initial_soc is not None else 0.8
    )
    return min(max(value * capacity_kwh if value <= 1.0 else value, 0.0), capacity_kwh)


def _vehicle_reserve_kwh(
    vehicle: ProblemVehicle,
    capacity_kwh: float,
) -> float:
    value = float(vehicle.reserve_soc if vehicle.reserve_soc is not None else 0.15)
    return min(max(value * capacity_kwh if value <= 1.0 else value, 0.0), capacity_kwh)


def _is_electric(vehicle: ProblemVehicle) -> bool:
    return str(vehicle.vehicle_type).upper() in _ELECTRIC_POWERTRAINS


def _horizon_start_min(problem: CanonicalOptimizationProblem) -> int:
    try:
        hour, minute = str(problem.scenario.horizon_start).split(":", 1)
        return int(hour) * 60 + int(minute)
    except (AttributeError, ValueError):
        return 0


def _slot_index(problem: CanonicalOptimizationProblem, minute: int) -> int:
    adjusted = int(minute)
    start = _horizon_start_min(problem)
    if adjusted < start:
        adjusted += 24 * 60
    return max((adjusted - start) // max(int(problem.scenario.timestep_min), 1), 0)


def _trip_active_in_slot(
    problem: CanonicalOptimizationProblem,
    trip: ProblemTrip,
    slot_idx: int,
) -> bool:
    return _trip_slot_fraction(problem, trip, slot_idx) > 0.0


def _trip_slot_fraction(
    problem: CanonicalOptimizationProblem,
    trip: ProblemTrip,
    slot_idx: int,
) -> float:
    step = max(int(problem.scenario.timestep_min), 1)
    start = _horizon_start_min(problem)
    slot_start = start + int(slot_idx) * step
    slot_end = slot_start + step
    departure = int(trip.departure_min)
    arrival = int(trip.arrival_min)
    if departure < start:
        departure += 24 * 60
    if arrival < start:
        arrival += 24 * 60
    if arrival < departure:
        arrival += 24 * 60
    overlap = max(min(arrival, slot_end) - max(departure, slot_start), 0)
    return overlap / max(arrival - departure, 1)
