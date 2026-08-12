"""Deterministic arrival-immediate charging for thesis M0/M2 baselines.

The adapter is intentionally not an optimizer.  It preserves the supplied
vehicle assignment, processes time slots chronologically, gives charging
priority to the vehicle that has been continuously present at its home depot
the longest, uses direct PV before grid electricity, and never dispatches the
stationary battery.  Any physical shortfall is returned as a failed baseline;
there is no repair, fallback, or reassignment.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping, Sequence

from src.dispatch.feasibility import evaluate_startup_feasibility
from src.dispatch.route_band import fragment_transition_diagnostic
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargerDefinition,
    ChargingSlot,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.common.soc_helpers import (
    deadhead_energy_kwh,
    effective_final_soc_target_kwh,
    final_soc_floor_kwh,
    horizon_start_min,
    is_electric_vehicle,
    return_deadhead_energy_kwh,
    return_deadhead_min_to_home,
    slot_absolute_min,
    slot_index,
    slot_index_ceil,
    startup_deadhead_energy_kwh,
    trip_active_slot_indices,
    trip_energy_kwh,
    trip_slot_energy_fraction,
    vehicle_capacity_kwh,
    vehicle_initial_soc_kwh,
)


CHARGE_EFFICIENCY = 0.95
TOLERANCE = 1.0e-6


@dataclass(frozen=True)
class ImmediateChargeBaselineResult:
    plan: AssignmentPlan
    feasible: bool
    errors: tuple[str, ...]
    audit: Mapping[str, Any]


@dataclass(frozen=True)
class _ResidenceInterval:
    start_min: int
    end_min: int


@dataclass(frozen=True)
class _VehicleFragment:
    duty: Any
    trips: tuple[ProblemTrip, ...]


def apply_arrival_immediate_charging(
    problem: CanonicalOptimizationProblem,
    assignment: AssignmentPlan,
    *,
    method_id: str,
) -> ImmediateChargeBaselineResult:
    """Apply the non-optimizing charging rule to a fixed assignment."""

    method = str(method_id or "").strip().upper()
    if method not in {"M0", "M2"}:
        raise ValueError("arrival-immediate baseline method_id must be M0 or M2")
    slot_indices = tuple(
        sorted({int(slot.slot_index) for slot in problem.price_slots})
    )
    if not slot_indices:
        raise ValueError("arrival-immediate baseline requires price/time slots")
    timestep_min = max(int(problem.scenario.timestep_min), 1)
    timestep_h = timestep_min / 60.0
    charging_model = str(
        problem.metadata.get("charging_power_model") or "constant_power_v0"
    ).strip().lower()
    if charging_model not in {"constant_power_v0", "piecewise_soc_taper_v1"}:
        raise ValueError(f"unsupported charging_power_model: {charging_model}")
    minimum_session_min = max(
        int(problem.metadata.get("minimum_charge_session_minutes") or 0),
        0,
    )
    if charging_model == "piecewise_soc_taper_v1" and (
        minimum_session_min > timestep_min
    ):
        raise ValueError(
            "arrival-immediate baseline v1 requires timestep_min >= "
            "minimum_charge_session_minutes"
        )

    trip_by_id = problem.trip_by_id()
    vehicle_by_id = {
        str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles
    }
    paths, path_errors = _vehicle_paths(
        problem,
        assignment,
        trip_by_id=trip_by_id,
        vehicle_by_id=vehicle_by_id,
    )
    drive_kwh_by_vehicle_slot: dict[tuple[str, int], float] = {}
    residence_by_vehicle: dict[str, tuple[_ResidenceInterval, ...]] = {}
    preparation_errors = list(path_errors)
    horizon_end = slot_absolute_min(problem, slot_indices[-1]) + timestep_min
    for vehicle_id, fragments in paths.items():
        vehicle = vehicle_by_id[vehicle_id]
        if not is_electric_vehicle(problem, vehicle):
            continue
        intervals, errors = _build_vehicle_physics(
            problem,
            vehicle,
            fragments,
            slot_indices=slot_indices,
            horizon_end_min=horizon_end,
            drive_kwh_by_vehicle_slot=drive_kwh_by_vehicle_slot,
        )
        residence_by_vehicle[vehicle_id] = intervals
        preparation_errors.extend(errors)

    soc_kwh_by_vehicle: dict[str, float] = {}
    reserve_kwh_by_vehicle: dict[str, float] = {}
    capacity_kwh_by_vehicle: dict[str, float] = {}
    terminal_required_kwh_by_vehicle: dict[str, float] = {}
    electric_vehicle_ids: list[str] = []
    for vehicle_id in sorted(paths):
        vehicle = vehicle_by_id[vehicle_id]
        if not is_electric_vehicle(problem, vehicle):
            continue
        capacity = vehicle_capacity_kwh(problem, vehicle)
        if capacity <= 0.0:
            preparation_errors.append(
                f"vehicle {vehicle_id} has no positive battery capacity"
            )
            continue
        electric_vehicle_ids.append(vehicle_id)
        capacity_kwh_by_vehicle[vehicle_id] = capacity
        soc_kwh_by_vehicle[vehicle_id] = vehicle_initial_soc_kwh(
            problem,
            vehicle,
            cap_kwh=capacity,
        )
        reserve_kwh_by_vehicle[vehicle_id] = final_soc_floor_kwh(
            problem,
            vehicle,
            cap_kwh=capacity,
        )
        target = effective_final_soc_target_kwh(
            problem,
            vehicle,
            cap_kwh=capacity,
        )
        terminal_required_kwh_by_vehicle[vehicle_id] = (
            reserve_kwh_by_vehicle[vehicle_id]
            if target is None
            else max(reserve_kwh_by_vehicle[vehicle_id], target)
        )

    chargers_by_depot = _expanded_charger_ports(problem)
    import_limit_kw_by_depot = {
        str(depot.depot_id): (
            max(float(depot.import_limit_kw or 0.0), 0.0)
            if float(depot.import_limit_kw or 0.0) > 0.0
            else math.inf
        )
        for depot in problem.depots
    }
    charging_slots: list[ChargingSlot] = []
    grid_to_bus: dict[str, dict[int, float]] = {}
    pv_to_bus: dict[str, dict[int, float]] = {}
    pv_curtail: dict[str, dict[int, float]] = {}
    vehicle_soc_trace: dict[str, dict[int, float]] = {
        vehicle_id: {} for vehicle_id in electric_vehicle_ids
    }
    soc_errors: list[str] = []

    for slot_idx in slot_indices:
        slot_start = slot_absolute_min(problem, slot_idx)
        slot_end = slot_start + timestep_min
        for vehicle_id in electric_vehicle_ids:
            vehicle_soc_trace[vehicle_id][slot_idx] = soc_kwh_by_vehicle[
                vehicle_id
            ]
            drive_kwh = max(
                float(
                    drive_kwh_by_vehicle_slot.get((vehicle_id, slot_idx), 0.0)
                ),
                0.0,
            )
            soc_kwh_by_vehicle[vehicle_id] -= drive_kwh
            if (
                soc_kwh_by_vehicle[vehicle_id] + TOLERANCE
                < reserve_kwh_by_vehicle[vehicle_id]
            ):
                soc_errors.append(
                    f"vehicle {vehicle_id} SOC below floor in slot {slot_idx}: "
                    f"{soc_kwh_by_vehicle[vehicle_id]:.6f} < "
                    f"{reserve_kwh_by_vehicle[vehicle_id]:.6f} kWh"
                )

        pv_remaining_by_depot = {
            depot_id: _pv_generation_kwh_at_slot(problem, depot_id, slot_idx)
            for depot_id in _known_depot_ids(problem)
        }
        grid_remaining_by_depot = {
            depot_id: import_limit_kw_by_depot.get(depot_id, math.inf)
            * timestep_h
            for depot_id in _known_depot_ids(problem)
        }
        ports_by_depot = {
            depot_id: list(ports)
            for depot_id, ports in chargers_by_depot.items()
        }
        candidates = []
        for vehicle_id in electric_vehicle_ids:
            interval = _covering_residence_interval(
                residence_by_vehicle.get(vehicle_id, ()),
                slot_start,
                slot_end,
            )
            if interval is None:
                continue
            remaining_drive_kwh = sum(
                max(float(energy_kwh or 0.0), 0.0)
                for (candidate_vehicle_id, candidate_slot), energy_kwh in (
                    drive_kwh_by_vehicle_slot.items()
                )
                if candidate_vehicle_id == vehicle_id
                and int(candidate_slot) > int(slot_idx)
            )
            charge_ceiling_kwh = min(
                capacity_kwh_by_vehicle[vehicle_id],
                terminal_required_kwh_by_vehicle[vehicle_id]
                + remaining_drive_kwh,
            )
            if soc_kwh_by_vehicle[vehicle_id] >= charge_ceiling_kwh - TOLERANCE:
                continue
            candidates.append(
                (interval.start_min, vehicle_id, charge_ceiling_kwh)
            )

        for _arrival_min, vehicle_id, charge_ceiling_kwh in sorted(candidates):
            vehicle = vehicle_by_id[vehicle_id]
            depot_id = str(vehicle.home_depot_id or "depot_default")
            port = _take_compatible_port(
                ports_by_depot.get(depot_id, []),
                vehicle,
            )
            if port is None:
                continue
            charger, _port_index = port
            capacity = capacity_kwh_by_vehicle[vehicle_id]
            soc = soc_kwh_by_vehicle[vehicle_id]
            power_limit_kw = min(
                max(float(charger.power_kw or 0.0), 0.0),
                _vehicle_charge_power_kw(problem, vehicle),
            )
            power_limit_kw *= _charge_taper_factor(
                charging_model,
                soc_kwh=soc,
                capacity_kwh=capacity,
            )
            power_limit_kw *= _session_time_factor(
                problem,
                charging_model=charging_model,
                timestep_min=timestep_min,
            )
            requested_input_kwh = min(
                power_limit_kw * timestep_h,
                max(
                    (charge_ceiling_kwh - soc) / CHARGE_EFFICIENCY,
                    0.0,
                ),
            )
            pv_kwh = min(
                requested_input_kwh,
                pv_remaining_by_depot.get(depot_id, 0.0),
            )
            grid_kwh = min(
                max(requested_input_kwh - pv_kwh, 0.0),
                grid_remaining_by_depot.get(depot_id, math.inf),
            )
            supplied_input_kwh = pv_kwh + grid_kwh
            if supplied_input_kwh <= TOLERANCE:
                ports_by_depot.setdefault(depot_id, []).append(port)
                continue
            soc_kwh_by_vehicle[vehicle_id] = min(
                capacity,
                soc + CHARGE_EFFICIENCY * supplied_input_kwh,
            )
            pv_remaining_by_depot[depot_id] = max(
                pv_remaining_by_depot.get(depot_id, 0.0) - pv_kwh,
                0.0,
            )
            grid_remaining_by_depot[depot_id] = max(
                grid_remaining_by_depot.get(depot_id, math.inf) - grid_kwh,
                0.0,
            )
            if pv_kwh > TOLERANCE:
                _add_energy(pv_to_bus, depot_id, slot_idx, pv_kwh)
                charging_slots.append(
                    ChargingSlot(
                        vehicle_id=vehicle_id,
                        slot_index=slot_idx,
                        charger_id=str(charger.charger_id),
                        charge_kw=pv_kwh / timestep_h,
                        charging_depot_id=depot_id,
                        energy_source="pv",
                    )
                )
            if grid_kwh > TOLERANCE:
                _add_energy(grid_to_bus, depot_id, slot_idx, grid_kwh)
                charging_slots.append(
                    ChargingSlot(
                        vehicle_id=vehicle_id,
                        slot_index=slot_idx,
                        charger_id=str(charger.charger_id),
                        charge_kw=grid_kwh / timestep_h,
                        charging_depot_id=depot_id,
                        energy_source="grid",
                    )
                )

        for depot_id, remaining_kwh in pv_remaining_by_depot.items():
            _add_energy(pv_curtail, depot_id, slot_idx, remaining_kwh)

    for vehicle_id in electric_vehicle_ids:
        vehicle = vehicle_by_id[vehicle_id]
        capacity = capacity_kwh_by_vehicle[vehicle_id]
        required = terminal_required_kwh_by_vehicle[vehicle_id]
        if soc_kwh_by_vehicle[vehicle_id] + TOLERANCE < required:
            soc_errors.append(
                f"vehicle {vehicle_id} terminal SOC below target: "
                f"{soc_kwh_by_vehicle[vehicle_id]:.6f} < {required:.6f} kWh"
            )

    bess_soc = {
        depot_id: {
            slot_idx: float(asset.bess_initial_soc_kwh or 0.0)
            for slot_idx in slot_indices
        }
        for depot_id, asset in problem.depot_energy_assets.items()
        if bool(asset.bess_enabled)
    }
    metadata = dict(assignment.metadata or {})
    metadata.update(
        {
            "source": "arrival_immediate_charge_baseline_v1",
            "thesis_ablation_method_id": method,
            "optimization_structure": "fixed_assignment_rule_energy_dispatch",
            "charging_policy": "arrival_immediate_pv_then_grid_no_bess",
            "charging_dispatch_optimized": False,
            "bess_dispatch_optimized": False,
            "source_provenance_exact": True,
            "derived_source_split": False,
            "postsolve_repair_applied": False,
            "research_kpi_eligible": False,
            "thesis_ablation_candidate": True,
            "vehicle_soc_trace_semantics": "start_of_slot_before_drive_and_charge",
            "fragment_transition_policy": (
                "direct_when_feasible_else_explicit_home_depot_reset"
            ),
        }
    )
    candidate_plan = replace(
        assignment,
        charging_slots=tuple(
            sorted(
                charging_slots,
                key=lambda item: (
                    int(item.slot_index),
                    str(item.vehicle_id),
                    str(item.energy_source),
                ),
            )
        ),
        grid_to_bus_kwh_by_depot_slot=grid_to_bus,
        pv_to_bus_kwh_by_depot_slot=pv_to_bus,
        bess_to_bus_kwh_by_depot_slot={},
        pv_to_bess_kwh_by_depot_slot={},
        grid_to_bess_kwh_by_depot_slot={},
        pv_curtail_kwh_by_depot_slot=pv_curtail,
        bess_soc_kwh_by_depot_slot=bess_soc,
        contract_over_limit_kwh_by_depot_slot={},
        vehicle_soc_kwh_by_vehicle_slot=vehicle_soc_trace,
        metadata=metadata,
    )
    physical_report = FeasibilityChecker().evaluate(problem, candidate_plan)
    errors = tuple(
        dict.fromkeys(
            [
                *preparation_errors,
                *soc_errors,
                *physical_report.errors,
            ]
        )
    )
    feasible = not errors and bool(physical_report.feasible)
    final_metadata = dict(candidate_plan.metadata or {})
    final_metadata.update(
        {
            "rule_baseline_feasible": feasible,
            "rule_baseline_error_count": len(errors),
            "rule_baseline_errors": errors,
            "physical_validation_metrics": dict(physical_report.metrics),
        }
    )
    final_plan = replace(candidate_plan, metadata=final_metadata)
    audit = {
        "schema_version": "arrival_immediate_charge_baseline_audit_v1",
        "method_id": method,
        "feasible": feasible,
        "error_count": len(errors),
        "errors": list(errors),
        "electric_vehicle_count": len(electric_vehicle_ids),
        "charging_slot_row_count": len(charging_slots),
        "grid_to_bus_kwh": _sum_nested_energy(grid_to_bus),
        "pv_to_bus_kwh": _sum_nested_energy(pv_to_bus),
        "pv_curtailed_kwh": _sum_nested_energy(pv_curtail),
        "bess_dispatch_policy": "disabled_hold_initial_soc",
        "priority_rule": "longest_continuous_home_depot_presence_then_vehicle_id",
        "source_rule": "direct_pv_first_then_grid",
        "pv_input_semantics": "available_surplus_after_depot_load",
        "charger_residence_rule": "vehicle_must_cover_the_complete_time_slot",
        "session_policy": "conservative_reconnect_each_charged_slot_v1",
        "setup_teardown_application": (
            "deducted_from_each_charged_slot_for_piecewise_soc_taper_v1"
        ),
        "minimum_charge_session_minutes": minimum_session_min,
    }
    return ImmediateChargeBaselineResult(
        plan=final_plan,
        feasible=feasible,
        errors=errors,
        audit=audit,
    )


def build_m0_rule_baseline(
    problem: CanonicalOptimizationProblem,
) -> ImmediateChargeBaselineResult:
    """Build M0 from the canonical non-optimizing dispatch baseline."""

    if problem.baseline_plan is None:
        raise ValueError("M0 requires problem.baseline_plan")
    return apply_arrival_immediate_charging(
        problem,
        problem.baseline_plan,
        method_id="M0",
    )


def build_m2_simple_charge_baseline(
    problem: CanonicalOptimizationProblem,
    optimized_assignment: AssignmentPlan,
) -> ImmediateChargeBaselineResult:
    """Build M2 from an externally optimized, fixed assignment."""

    source = str(
        optimized_assignment.metadata.get("optimization_structure") or ""
    ).strip().lower()
    if source not in {"assignment_only", "two_stage", "integrated"}:
        raise ValueError(
            "M2 requires an assignment produced by assignment-only or "
            "integrated optimization"
        )
    return apply_arrival_immediate_charging(
        problem,
        optimized_assignment,
        method_id="M2",
    )


def _vehicle_paths(
    problem: CanonicalOptimizationProblem,
    assignment: AssignmentPlan,
    *,
    trip_by_id: Mapping[str, ProblemTrip],
    vehicle_by_id: Mapping[str, ProblemVehicle],
) -> tuple[dict[str, tuple[_VehicleFragment, ...]], tuple[str, ...]]:
    grouped: dict[str, list[_VehicleFragment]] = {}
    errors: list[str] = []
    seen: set[str] = set()
    for duty in assignment.duties:
        vehicle_id = str(assignment.vehicle_id_for_duty(duty.duty_id))
        if vehicle_id not in vehicle_by_id:
            errors.append(f"duty {duty.duty_id} maps to unknown vehicle {vehicle_id}")
            continue
        fragment_trips: list[ProblemTrip] = []
        for trip_id in duty.trip_ids:
            normalized_trip_id = str(trip_id)
            if normalized_trip_id in seen:
                errors.append(f"trip {normalized_trip_id} is assigned more than once")
                continue
            seen.add(normalized_trip_id)
            trip = trip_by_id.get(normalized_trip_id)
            if trip is None:
                errors.append(f"unknown trip {normalized_trip_id} in assignment")
                continue
            fragment_trips.append(trip)
        if fragment_trips:
            grouped.setdefault(vehicle_id, []).append(
                _VehicleFragment(
                    duty=duty,
                    trips=tuple(
                        sorted(
                            fragment_trips,
                            key=lambda trip: (
                                _service_minute(problem, trip.departure_min),
                                _service_minute(problem, trip.arrival_min),
                                str(trip.trip_id),
                            ),
                        )
                    ),
                )
            )
    expected = set(problem.eligible_trip_ids())
    missing = sorted(expected - seen)
    if missing:
        errors.append(f"assignment misses {len(missing)} trips: {', '.join(missing[:10])}")
    return (
        {
            vehicle_id: tuple(
                sorted(
                    fragments,
                    key=lambda fragment: (
                        _service_minute(
                            problem,
                            fragment.trips[0].departure_min,
                        ),
                        str(getattr(fragment.duty, "duty_id", "")),
                    ),
                )
            )
            for vehicle_id, fragments in grouped.items()
        },
        tuple(errors),
    )


def _build_vehicle_physics(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
    fragments: Sequence[_VehicleFragment],
    *,
    slot_indices: Sequence[int],
    horizon_end_min: int,
    drive_kwh_by_vehicle_slot: dict[tuple[str, int], float],
) -> tuple[tuple[_ResidenceInterval, ...], tuple[str, ...]]:
    if not fragments:
        return (), ()
    vehicle_id = str(vehicle.vehicle_id)
    context = problem.dispatch_context
    errors: list[str] = []
    first = fragments[0].trips[0]
    dispatch_trip = context.trips_by_id().get(str(first.trip_id), first)
    startup = evaluate_startup_feasibility(
        dispatch_trip,
        context,
        str(vehicle.home_depot_id),
    )
    if not startup.feasible:
        errors.append(
            f"vehicle {vehicle_id} cannot reach first trip {first.trip_id}: "
            f"{startup.reason_code}"
        )
    first_departure = _service_minute(problem, first.departure_min)
    intervals: list[_ResidenceInterval] = []
    _append_interval(
        intervals,
        horizon_start_min(problem),
        first_departure - max(int(startup.deadhead_time_min or 0), 0),
    )
    _add_drive_energy(
        drive_kwh_by_vehicle_slot,
        vehicle_id,
        slot_index(problem, first.departure_min),
        startup_deadhead_energy_kwh(problem, vehicle, first),
    )

    for fragment_index, fragment in enumerate(fragments):
        if fragment_index > 0:
            _append_fragment_transition(
                problem,
                vehicle,
                fragments[fragment_index - 1],
                fragment,
                intervals=intervals,
                drive_kwh_by_vehicle_slot=drive_kwh_by_vehicle_slot,
                errors=errors,
            )
        for index, trip in enumerate(fragment.trips):
            trip_energy = trip_energy_kwh(problem, vehicle, trip)
            for active_slot in trip_active_slot_indices(
                problem,
                trip.departure_min,
                trip.arrival_min,
            ):
                if active_slot not in slot_indices:
                    continue
                _add_drive_energy(
                    drive_kwh_by_vehicle_slot,
                    vehicle_id,
                    active_slot,
                    trip_energy
                    * trip_slot_energy_fraction(
                        problem,
                        trip.departure_min,
                        trip.arrival_min,
                        active_slot,
                    ),
                )
            if index == 0:
                continue
            previous = fragment.trips[index - 1]
            if str(trip.trip_id) not in set(
                problem.feasible_connections.get(str(previous.trip_id), ())
            ):
                errors.append(
                    f"vehicle {vehicle_id} infeasible transition "
                    f"{previous.trip_id}->{trip.trip_id}"
                )
            _add_drive_energy(
                drive_kwh_by_vehicle_slot,
                vehicle_id,
                slot_index(problem, trip.departure_min),
                deadhead_energy_kwh(problem, vehicle, previous, trip),
            )
            _append_connection_residence(
                problem,
                vehicle,
                previous,
                trip,
                intervals,
            )

    last = fragments[-1].trips[-1]
    return_exists, return_deadhead_min = return_deadhead_min_to_home(
        problem,
        vehicle,
        last,
    )
    if not return_exists:
        errors.append(
            f"vehicle {vehicle_id} cannot return from trip {last.trip_id} "
            "to home depot"
        )
    else:
        return_complete = _service_minute(problem, last.arrival_min) + int(
            return_deadhead_min
        )
        _add_drive_energy(
            drive_kwh_by_vehicle_slot,
            vehicle_id,
            slot_index_ceil(problem, return_complete),
            return_deadhead_energy_kwh(problem, vehicle, last),
        )
        _append_interval(intervals, return_complete, horizon_end_min)
    return tuple(intervals), tuple(errors)


def _append_fragment_transition(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
    previous_fragment: _VehicleFragment,
    current_fragment: _VehicleFragment,
    *,
    intervals: list[_ResidenceInterval],
    drive_kwh_by_vehicle_slot: dict[tuple[str, int], float],
    errors: list[str],
) -> None:
    """Materialize the same direct-or-depot transition used by validation."""

    previous = previous_fragment.trips[-1]
    current = current_fragment.trips[0]
    fixed_route_band_mode = bool(
        problem.metadata.get("fixed_route_band_mode", False)
        or problem.metadata.get("route_band_restricted", False)
        or getattr(problem.dispatch_context, "fixed_route_band_mode", False)
    )
    allow_same_day_depot_cycles = bool(
        problem.metadata.get(
            "allow_same_day_depot_cycles",
            getattr(problem.scenario, "allow_same_day_depot_cycles", True),
        )
    )
    diagnostic = fragment_transition_diagnostic(
        previous_fragment.duty,
        current_fragment.duty,
        home_depot_id=str(vehicle.home_depot_id),
        dispatch_context=problem.dispatch_context,
        fixed_route_band_mode=fixed_route_band_mode,
        horizon_start_min=horizon_start_min(problem),
        allow_same_day_depot_cycles=allow_same_day_depot_cycles,
    )
    vehicle_id = str(vehicle.vehicle_id)
    if not diagnostic.feasible:
        errors.append(
            f"vehicle {vehicle_id} infeasible fragment transition "
            f"{previous.trip_id}->{current.trip_id}: {diagnostic.reason_code}"
        )
        return
    if diagnostic.direct_ok:
        _add_drive_energy(
            drive_kwh_by_vehicle_slot,
            vehicle_id,
            slot_index(problem, current.departure_min),
            deadhead_energy_kwh(problem, vehicle, previous, current),
        )
        _append_connection_residence(
            problem,
            vehicle,
            previous,
            current,
            intervals,
        )
        return

    return_exists, return_minutes = return_deadhead_min_to_home(
        problem,
        vehicle,
        previous,
    )
    startup = evaluate_startup_feasibility(
        problem.dispatch_context.trips_by_id().get(
            str(current.trip_id),
            current,
        ),
        problem.dispatch_context,
        str(vehicle.home_depot_id),
    )
    if not return_exists or not startup.feasible:
        errors.append(
            f"vehicle {vehicle_id} depot reset could not be materialized for "
            f"{previous.trip_id}->{current.trip_id}"
        )
        return
    turnaround_min = max(
        int(
            problem.dispatch_context.get_turnaround_min(
                str(previous.destination)
            )
            or 0
        ),
        0,
    )
    home_arrival = (
        _service_minute(problem, previous.arrival_min)
        + turnaround_min
        + int(return_minutes)
    )
    home_departure = _service_minute(problem, current.departure_min) - max(
        int(startup.deadhead_time_min or 0),
        0,
    )
    _add_drive_energy(
        drive_kwh_by_vehicle_slot,
        vehicle_id,
        slot_index_ceil(problem, home_arrival),
        return_deadhead_energy_kwh(problem, vehicle, previous),
    )
    _add_drive_energy(
        drive_kwh_by_vehicle_slot,
        vehicle_id,
        slot_index(problem, current.departure_min),
        startup_deadhead_energy_kwh(problem, vehicle, current),
    )
    _append_interval(intervals, home_arrival, home_departure)


def _append_connection_residence(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
    previous: ProblemTrip,
    current: ProblemTrip,
    intervals: list[_ResidenceInterval],
) -> None:
    context = problem.dispatch_context
    home = str(vehicle.home_depot_id)
    previous_arrival = _service_minute(problem, previous.arrival_min)
    current_departure = _service_minute(problem, current.departure_min)
    turnaround = max(
        int(context.get_turnaround_min(str(previous.destination)) or 0),
        0,
    )
    previous_at_home = context.locations_equivalent(
        str(previous.destination),
        home,
    )
    current_at_home = context.locations_equivalent(str(current.origin), home)
    if previous_at_home:
        leave_home = current_departure - _required_deadhead_min(
            context,
            home,
            str(current.origin),
        )
        _append_interval(
            intervals,
            previous_arrival + turnaround,
            leave_home,
        )
        return
    if current_at_home:
        home_arrival = (
            previous_arrival
            + turnaround
            + _required_deadhead_min(
                context,
                str(previous.destination),
                home,
            )
        )
        _append_interval(intervals, home_arrival, current_departure)


def _required_deadhead_min(context: Any, origin: str, destination: str) -> int:
    if context.locations_equivalent(origin, destination):
        return 0
    return max(int(context.get_deadhead_min(origin, destination) or 0), 0)


def _append_interval(
    intervals: list[_ResidenceInterval],
    start_min: int,
    end_min: int,
) -> None:
    if int(end_min) > int(start_min):
        intervals.append(
            _ResidenceInterval(start_min=int(start_min), end_min=int(end_min))
        )


def _covering_residence_interval(
    intervals: Sequence[_ResidenceInterval],
    slot_start: int,
    slot_end: int,
) -> _ResidenceInterval | None:
    for interval in intervals:
        if interval.start_min <= slot_start and interval.end_min >= slot_end:
            return interval
    return None


def _expanded_charger_ports(
    problem: CanonicalOptimizationProblem,
) -> dict[str, tuple[tuple[ChargerDefinition, int], ...]]:
    by_depot: dict[str, list[tuple[ChargerDefinition, int]]] = {}
    for charger in sorted(
        problem.chargers,
        key=lambda item: (-float(item.power_kw or 0.0), str(item.charger_id)),
    ):
        depot_id = str(charger.depot_id or "depot_default")
        for port_index in range(max(int(charger.simultaneous_ports or 1), 1)):
            by_depot.setdefault(depot_id, []).append((charger, port_index))
    return {key: tuple(value) for key, value in by_depot.items()}


def _take_compatible_port(
    ports: list[tuple[ChargerDefinition, int]],
    vehicle: ProblemVehicle,
) -> tuple[ChargerDefinition, int] | None:
    explicit_ids = set(str(item) for item in vehicle.compatible_charger_ids)
    for index, port in enumerate(ports):
        if explicit_ids and str(port[0].charger_id) not in explicit_ids:
            continue
        return ports.pop(index)
    return None


def _vehicle_charge_power_kw(
    problem: CanonicalOptimizationProblem,
    vehicle: ProblemVehicle,
) -> float:
    direct = max(float(vehicle.charge_power_max_kw or 0.0), 0.0)
    if direct > 0.0:
        return direct
    vehicle_type = next(
        (
            item
            for item in problem.vehicle_types
            if str(item.vehicle_type_id) == str(vehicle.vehicle_type)
        ),
        None,
    )
    return max(float(getattr(vehicle_type, "charge_power_max_kw", 0.0) or 0.0), 0.0)


def _charge_taper_factor(
    model: str,
    *,
    soc_kwh: float,
    capacity_kwh: float,
) -> float:
    if model == "constant_power_v0" or capacity_kwh <= 0.0:
        return 1.0
    ratio = soc_kwh / capacity_kwh
    if ratio < 0.80:
        return 1.0
    if ratio < 0.90:
        return 2.0 / 3.0
    return 1.0 / 3.0


def _session_time_factor(
    problem: CanonicalOptimizationProblem,
    *,
    charging_model: str,
    timestep_min: int,
) -> float:
    if charging_model == "constant_power_v0":
        return 1.0
    setup_min = max(float(problem.metadata.get("charge_setup_minutes") or 0.0), 0.0)
    teardown_min = max(
        float(problem.metadata.get("charge_teardown_minutes") or 0.0),
        0.0,
    )
    usable = float(timestep_min) - setup_min - teardown_min
    if usable <= 0.0:
        raise ValueError(
            "charge setup and teardown consume the whole time slot"
        )
    return usable / float(timestep_min)


def _known_depot_ids(problem: CanonicalOptimizationProblem) -> tuple[str, ...]:
    values = {str(depot.depot_id) for depot in problem.depots}
    values.update(str(key) for key in problem.depot_energy_assets)
    values.update(str(vehicle.home_depot_id) for vehicle in problem.vehicles)
    return tuple(sorted(value for value in values if value))


def _pv_generation_kwh_at_slot(
    problem: CanonicalOptimizationProblem,
    depot_id: str,
    slot_idx: int,
) -> float:
    asset = problem.depot_energy_assets.get(str(depot_id))
    if asset is None or not bool(asset.pv_enabled):
        return 0.0
    values = tuple(asset.available_pv_surplus_kwh_by_slot or ())
    if not values and str(asset.pv_input_semantics or "").strip().lower() == (
        "available_surplus_after_depot_load"
    ):
        values = tuple(asset.pv_generation_kwh_by_slot or ())
    if slot_idx < 0 or slot_idx >= len(values):
        return 0.0
    return max(float(values[slot_idx] or 0.0), 0.0)


def _service_minute(
    problem: CanonicalOptimizationProblem,
    minute: int,
) -> int:
    value = int(minute)
    if value < horizon_start_min(problem):
        value += 24 * 60
    return value


def _add_drive_energy(
    target: dict[tuple[str, int], float],
    vehicle_id: str,
    slot_idx: int,
    energy_kwh: float,
) -> None:
    if energy_kwh <= 0.0:
        return
    key = (str(vehicle_id), int(slot_idx))
    target[key] = target.get(key, 0.0) + float(energy_kwh)


def _add_energy(
    target: dict[str, dict[int, float]],
    depot_id: str,
    slot_idx: int,
    energy_kwh: float,
) -> None:
    if energy_kwh <= TOLERANCE:
        return
    by_slot = target.setdefault(str(depot_id), {})
    by_slot[int(slot_idx)] = by_slot.get(int(slot_idx), 0.0) + float(energy_kwh)


def _sum_nested_energy(values: Mapping[str, Mapping[int, float]]) -> float:
    return sum(
        max(float(value or 0.0), 0.0)
        for by_slot in values.values()
        for value in by_slot.values()
    )
