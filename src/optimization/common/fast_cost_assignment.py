"""Fast cost-aware vehicle assignment over an already feasible path cover.

This module deliberately does not rebuild or relax timetable chains.  It only
maps the duties in the canonical baseline path cover to concrete available
vehicles.  Charging and SOC feasibility remain the responsibility of the
canonical fixed-assignment charging MILP.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any, Mapping

import numpy as np
from scipy.optimize import linear_sum_assignment

from src.optimization.common.cost_components import normalize_cost_component_flags
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ProblemVehicle,
)
from src.optimization.common.soc_helpers import (
    is_electric_vehicle,
    vehicle_capacity_kwh,
    vehicle_initial_soc_kwh,
    vehicle_powertrain_type,
    vehicle_reserve_soc_kwh,
)


_INVALID_ASSIGNMENT_COST = 1.0e15
_ELECTRIC_POWERTRAINS = {"BEV", "PHEV", "FCEV"}


def _vehicle_type(problem: CanonicalOptimizationProblem, vehicle: ProblemVehicle) -> Any:
    return next(
        (
            vehicle_type
            for vehicle_type in problem.vehicle_types
            if str(vehicle_type.vehicle_type_id) == str(vehicle.vehicle_type)
        ),
        None,
    )


def _positive_rate(vehicle_value: Any, type_value: Any, *, label: str) -> float:
    for raw_value in (vehicle_value, type_value):
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0.0:
            return value
    raise ValueError(f"Missing positive {label}; zero-distance/rate fallback is forbidden")


def _duty_distance_km(problem: CanonicalOptimizationProblem, duty: Any) -> float:
    revenue_distance_km = 0.0
    deadhead_min = 0.0
    for leg in duty.legs:
        distance_km = float(leg.trip.distance_km or 0.0)
        if not math.isfinite(distance_km) or distance_km <= 0.0:
            raise ValueError(
                f"Duty {duty.duty_id} trip {leg.trip.trip_id} has nonpositive distance"
            )
        revenue_distance_km += distance_km
        deadhead_min += max(float(leg.deadhead_from_prev_min or 0.0), 0.0)
    deadhead_speed_kmh = float(
        (problem.metadata or {}).get("deadhead_speed_kmh", 18.0) or 18.0
    )
    if not math.isfinite(deadhead_speed_kmh) or deadhead_speed_kmh <= 0.0:
        raise ValueError("deadhead_speed_kmh must be positive")
    return revenue_distance_km + deadhead_min * deadhead_speed_kmh / 60.0


def _minimum_grid_unit_cost(problem: CanonicalOptimizationProblem) -> float:
    co2_price = max(float(problem.scenario.co2_price_per_kg or 0.0), 0.0)
    unit_costs = [
        max(float(slot.grid_buy_yen_per_kwh or 0.0), 0.0)
        + co2_price * max(float(slot.co2_factor or 0.0), 0.0)
        for slot in problem.price_slots
    ]
    if not unit_costs:
        raise ValueError("Fast cost assignment requires explicit electricity price slots")
    return min(unit_costs)


def _electric_supply_proxy(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
    duty: Any,
    *,
    duty_energy_kwh: float,
    charging_efficiency: float,
    minimum_grid_unit_cost: float,
) -> tuple[float, float, float, float]:
    """Estimate PV-accessible energy, residual grid energy, and peak cost.

    The approximation is intentionally optimistic and is used only to rank
    fixed-path candidates.  The downstream MILP enforces the shared PV/BESS,
    charger, grid, and SOC constraints exactly.
    """

    timestep_min = max(int(problem.scenario.timestep_min or 0), 1)
    horizon_start_min = int(
        (problem.metadata or {}).get("horizon_start_min", 0) or 0
    )
    first_departure_min = min(int(leg.trip.departure_min) for leg in duty.legs)
    last_arrival_min = max(int(leg.trip.arrival_min) for leg in duty.legs)
    pv_accessible_kwh = 0.0
    home_depot_id = str(vehicle.home_depot_id or "")
    home_asset = problem.depot_energy_assets.get(home_depot_id)
    assets = (home_asset,) if home_asset is not None else ()
    for asset in assets:
        for slot_index, generation_kwh in enumerate(
            asset.pv_generation_kwh_by_slot
        ):
            slot_start_min = horizon_start_min + slot_index * timestep_min
            if not first_departure_min <= slot_start_min < last_arrival_min:
                pv_accessible_kwh += max(float(generation_kwh or 0.0), 0.0)

    required_supply_kwh = max(duty_energy_kwh, 0.0) / charging_efficiency
    pv_proxy_kwh = min(required_supply_kwh, pv_accessible_kwh)
    residual_grid_kwh = max(required_supply_kwh - pv_proxy_kwh, 0.0)
    horizon_duration_min = max(
        int(problem.scenario.horizon_duration_min or 24 * 60), timestep_min
    )
    unavailable_duration_min = max(last_arrival_min - first_departure_min, 0)
    charging_hours = max(
        (horizon_duration_min - unavailable_duration_min) / 60.0,
        timestep_min / 60.0,
    )
    peak_kw_proxy = residual_grid_kwh / charging_hours
    demand_rate = max(
        float(problem.scenario.demand_charge_on_peak_horizon_yen_per_kw or 0.0),
        float(problem.scenario.demand_charge_off_peak_horizon_yen_per_kw or 0.0),
    )
    demand_cost_proxy = peak_kw_proxy * demand_rate
    grid_energy_cost_proxy = residual_grid_kwh * minimum_grid_unit_cost
    return (
        pv_proxy_kwh,
        residual_grid_kwh,
        grid_energy_cost_proxy,
        demand_cost_proxy,
    )


def _vehicle_duty_proxy_cost(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
    duty: Any,
    *,
    duty_distance_km: float,
    minimum_grid_unit_cost: float,
    component_flags: Mapping[str, bool],
) -> float:
    if any(
        str(vehicle.vehicle_type).upper()
        not in {str(item).upper() for item in leg.trip.allowed_vehicle_types}
        for leg in duty.legs
    ):
        return _INVALID_ASSIGNMENT_COST

    vehicle_type = _vehicle_type(problem, vehicle)
    powertrain = vehicle_powertrain_type(problem, vehicle)
    variable_cost = 0.0
    if powertrain in _ELECTRIC_POWERTRAINS:
        energy_rate = _positive_rate(
            vehicle.energy_consumption_kwh_per_km,
            getattr(vehicle_type, "energy_consumption_kwh_per_km", None),
            label=f"energy consumption for {vehicle.vehicle_id}",
        )
        charging_efficiency = float(
            (problem.metadata or {}).get("charging_efficiency", 0.95) or 0.95
        )
        if not 0.0 < charging_efficiency <= 1.0:
            raise ValueError("charging_efficiency must be in (0, 1]")
        duty_energy_kwh = duty_distance_km * energy_rate
        if component_flags.get("electricity_cost", True):
            (
                _,
                _,
                grid_energy_cost_proxy,
                demand_cost_proxy,
            ) = _electric_supply_proxy(
                problem,
                vehicle,
                duty,
                duty_energy_kwh=duty_energy_kwh,
                charging_efficiency=charging_efficiency,
                minimum_grid_unit_cost=minimum_grid_unit_cost,
            )
            variable_cost += float(problem.objective_weights.energy) * (
                grid_energy_cost_proxy
            )
            if component_flags.get("demand_charge_cost", True):
                variable_cost += float(problem.objective_weights.demand) * (
                    demand_cost_proxy
                )

        # This term is a feasibility-oriented tie-break, not an invented cost.
        # It assigns higher-SOC buses to more energy-intensive duties while the
        # exact charging MILP remains the sole feasibility authority.
        capacity_kwh = vehicle_capacity_kwh(problem, vehicle)
        initial_kwh = vehicle_initial_soc_kwh(
            problem, vehicle, cap_kwh=capacity_kwh
        )
        reserve_kwh = vehicle_reserve_soc_kwh(
            problem, vehicle, cap_kwh=capacity_kwh
        )
        initial_shortfall_kwh = max(
            duty_energy_kwh - max(initial_kwh - reserve_kwh, 0.0), 0.0
        )
        variable_cost += initial_shortfall_kwh * 1.0e-4
    else:
        fuel_rate = _positive_rate(
            vehicle.fuel_consumption_l_per_km,
            getattr(vehicle_type, "fuel_consumption_l_per_km", None),
            label=f"fuel consumption for {vehicle.vehicle_id}",
        )
        emission_factor = float(
            getattr(vehicle_type, "co2_emission_kg_per_l", None)
            or problem.scenario.ice_co2_kg_per_l
            or 0.0
        )
        fuel_unit_cost = max(
            float(problem.scenario.diesel_price_yen_per_l or 0.0), 0.0
        ) + max(float(problem.scenario.co2_price_per_kg or 0.0), 0.0) * max(
            emission_factor, 0.0
        )
        if component_flags.get("fuel_cost", True):
            variable_cost += (
                float(problem.objective_weights.fuel)
                * duty_distance_km
                * fuel_rate
                * fuel_unit_cost
            )

    if component_flags.get("vehicle_fixed_cost", True):
        fixed_cost = float(vehicle.fixed_use_cost_jpy or 0.0)
        if fixed_cost <= 0.0 and vehicle_type is not None:
            fixed_cost = float(vehicle_type.fixed_use_cost_jpy or 0.0)
        variable_cost += float(problem.objective_weights.vehicle) * fixed_cost

    # Stable, economically immaterial tie-break for reproducible assignments.
    return variable_cost + (sum(ord(char) for char in str(vehicle.vehicle_id)) % 997) * 1.0e-9


def build_fast_cost_aware_assignment(
    problem: CanonicalOptimizationProblem,
    *,
    requested_bev_count: int,
) -> tuple[AssignmentPlan, dict[str, Any]]:
    """Assign fixed baseline duties to an exact requested number of BEVs.

    The returned assignment is a heuristic assignment candidate.  It is not a
    globally optimal dispatch claim and contains no synthetic charging slots.
    """

    baseline = problem.baseline_plan
    if baseline is None or not baseline.duties:
        raise ValueError("Fast assignment requires a nonempty canonical baseline plan")
    expected_trip_ids = {str(trip.trip_id) for trip in problem.trips}
    baseline_trip_ids = [
        str(leg.trip.trip_id) for duty in baseline.duties for leg in duty.legs
    ]
    if set(baseline_trip_ids) != expected_trip_ids or len(baseline_trip_ids) != len(
        expected_trip_ids
    ):
        raise ValueError("Baseline path cover must serve every trip exactly once")
    if baseline.unserved_trip_ids:
        raise ValueError("Fast assignment refuses a baseline with unserved trips")

    duties = tuple(baseline.duties)
    available_vehicles = tuple(
        vehicle for vehicle in problem.vehicles if bool(vehicle.available)
    )
    bev_vehicles = sorted(
        (
            vehicle
            for vehicle in available_vehicles
            if is_electric_vehicle(problem, vehicle)
        ),
        key=lambda vehicle: (
            -vehicle_initial_soc_kwh(problem, vehicle),
            str(vehicle.vehicle_id),
        ),
    )
    non_bev_vehicles = sorted(
        (
            vehicle
            for vehicle in available_vehicles
            if not is_electric_vehicle(problem, vehicle)
        ),
        key=lambda vehicle: str(vehicle.vehicle_id),
    )
    duty_count = len(duties)
    requested = int(requested_bev_count)
    if requested < 0 or requested > duty_count:
        raise ValueError(f"requested_bev_count must be between 0 and {duty_count}")
    required_non_bev_count = duty_count - requested
    if requested > len(bev_vehicles) or required_non_bev_count > len(non_bev_vehicles):
        raise ValueError(
            "Requested BEV/non-BEV mix exceeds the available concrete fleet"
        )

    selected_vehicles = tuple(
        bev_vehicles[:requested] + non_bev_vehicles[:required_non_bev_count]
    )
    component_flags = normalize_cost_component_flags(
        (problem.metadata or {}).get("cost_component_flags")
    )
    minimum_grid_unit_cost = _minimum_grid_unit_cost(problem)
    duty_distances = tuple(_duty_distance_km(problem, duty) for duty in duties)
    cost_matrix = np.full(
        (duty_count, duty_count), _INVALID_ASSIGNMENT_COST, dtype=float
    )
    for duty_index, (duty, duty_distance_km) in enumerate(
        zip(duties, duty_distances)
    ):
        for vehicle_index, vehicle in enumerate(selected_vehicles):
            cost_matrix[duty_index, vehicle_index] = _vehicle_duty_proxy_cost(
                problem,
                vehicle,
                duty,
                duty_distance_km=duty_distance_km,
                minimum_grid_unit_cost=minimum_grid_unit_cost,
                component_flags=component_flags,
            )

    row_indices, column_indices = linear_sum_assignment(cost_matrix)
    chosen_costs = cost_matrix[row_indices, column_indices]
    if len(row_indices) != duty_count or np.any(
        chosen_costs >= _INVALID_ASSIGNMENT_COST
    ):
        raise ValueError(
            f"No vehicle-compatible fixed-path assignment for {requested} BEVs"
        )

    assigned_duties = []
    duty_vehicle_map: dict[str, str] = {}
    assignment_rows = []
    for duty_index, vehicle_index in sorted(
        zip(row_indices.tolist(), column_indices.tolist())
    ):
        original_duty = duties[duty_index]
        vehicle = selected_vehicles[vehicle_index]
        new_duty_id = f"fast_{vehicle.vehicle_id}"
        assigned_duty = replace(
            original_duty,
            duty_id=new_duty_id,
            vehicle_type=str(vehicle.vehicle_type),
        )
        assigned_duties.append(assigned_duty)
        duty_vehicle_map[new_duty_id] = str(vehicle.vehicle_id)
        assignment_rows.append(
            {
                "duty_id": new_duty_id,
                "vehicle_id": str(vehicle.vehicle_id),
                "vehicle_type": str(vehicle.vehicle_type),
                "powertrain_type": vehicle_powertrain_type(problem, vehicle),
                "trip_count": len(assigned_duty.legs),
                "estimated_distance_km": duty_distances[duty_index],
                "proxy_variable_cost_jpy": float(
                    cost_matrix[duty_index, vehicle_index]
                ),
            }
        )

    metadata = {
        **dict(baseline.metadata or {}),
        "source": "fast_cost_aware_fixed_path_assignment",
        "baseline_path_cover_source": str(
            (baseline.metadata or {}).get("source") or ""
        ),
        "duty_vehicle_map": duty_vehicle_map,
        "assignment_heuristic": True,
        "assignment_global_optimality": False,
        "assignment_timetable_chains_modified": False,
        "requested_bev_count": requested,
        "actual_bev_count": sum(
            1
            for vehicle in selected_vehicles
            if is_electric_vehicle(problem, vehicle)
        ),
        "proxy_cost_semantics": (
            "distance_variable_energy_fuel_co2_fixed_use_cost_with_"
            "weather_time_aware_pv_and_demand_proxy; "
            "exact_charging_and_accounting_cost_evaluated_downstream"
        ),
    }
    plan = AssignmentPlan(
        duties=tuple(assigned_duties),
        charging_slots=(),
        refuel_slots=(),
        served_trip_ids=tuple(sorted(expected_trip_ids)),
        unserved_trip_ids=(),
        metadata=metadata,
    )
    audit = {
        "requested_bev_count": requested,
        "actual_bev_count": metadata["actual_bev_count"],
        "duty_count": duty_count,
        "trip_count": len(expected_trip_ids),
        "proxy_total_cost_jpy": float(np.sum(chosen_costs)),
        "minimum_grid_unit_cost_yen_per_kwh": minimum_grid_unit_cost,
        "timetable_chains_modified": False,
        "assignment_global_optimality": False,
        "assignment_rows": assignment_rows,
    }
    return plan, audit
