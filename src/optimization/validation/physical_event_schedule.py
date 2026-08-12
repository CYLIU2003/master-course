from __future__ import annotations

from collections import Counter, defaultdict
import math
from typing import Any, Dict, Mapping, Sequence

from src.dispatch.feasibility import FeasibilityEngine, evaluate_startup_feasibility
from src.optimization.common.bev_terminal_policy import (
    BevTerminalSocPolicy,
    bev_terminal_numeric_acceptance_contract,
    normalize_bev_terminal_soc_policy,
)
from src.optimization.common.soc_helpers import (
    deadhead_before_trip_energy_kwh,
    return_deadhead_energy_kwh,
    return_deadhead_min_to_home,
    trip_energy_kwh,
)
from src.optimization.common.time_axis import normalize_horizon_start_min


PHYSICAL_EVENT_VALIDATION_SCHEMA_VERSION = "physical_event_schedule_validation_v2"

REQUIRED_ZERO_METRICS = (
    "unassigned_trip_count",
    "duplicate_trip_count",
    "unknown_vehicle_count",
    "vehicle_time_overlap_count",
    "infeasible_transition_count",
    "location_discontinuity_count",
    "unknown_operator_count",
    "blank_charger_id_count",
    "unknown_charger_id_count",
    "charger_depot_mismatch_count",
    "charging_location_violation_count",
    "charger_compatibility_violation_count",
    "charger_power_violation_count",
    "charger_concurrency_violation_count",
    "refueling_location_violation_count",
    "refueling_powertrain_violation_count",
    "ev_soc_lower_violation_count",
    "ev_soc_upper_violation_count",
    "bev_terminal_soc_violation_count",
    "fuel_lower_violation_count",
    "fuel_upper_violation_count",
)

_EXCLUSIVE_EVENT_TYPES = frozenset(
    {
        "startup_deadhead",
        "service_trip",
        "connection_deadhead",
        "charging",
        "refueling",
        "terminal_return",
    }
)


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _event(
    *,
    event_id: str,
    vehicle_id: str,
    event_type: str,
    start_min: int,
    end_min: int,
    start_location: str,
    end_location: str,
    distance_km: float = 0.0,
    energy_kwh: float = 0.0,
    fuel_l: float = 0.0,
    power_kw: float = 0.0,
    power_limit_kw: float = 0.0,
    trip_id: str = "",
    charger_id: str = "",
    depot_id: str = "",
    source_artifact: str = "canonical_solver_result",
) -> Dict[str, Any]:
    return {
        "event_id": event_id,
        "vehicle_id": vehicle_id,
        "event_type": event_type,
        "start_min": int(start_min),
        "end_min": int(end_min),
        "start_location": str(start_location or ""),
        "end_location": str(end_location or ""),
        "distance_km": float(distance_km),
        "energy_kwh": float(energy_kwh),
        "fuel_l": float(fuel_l),
        "power_kw": float(power_kw),
        "power_limit_kw": float(power_limit_kw),
        "trip_id": str(trip_id or ""),
        "charger_id": str(charger_id or ""),
        "depot_id": str(depot_id or ""),
        "source_artifact": source_artifact,
    }


def _trip_endpoint(trip: Any, *, origin: bool) -> str:
    if origin:
        return str(
            getattr(trip, "origin_stop_id", "")
            or getattr(trip, "origin", "")
            or ""
        )
    return str(
        getattr(trip, "destination_stop_id", "")
        or getattr(trip, "destination", "")
        or ""
    )


def _vehicle_powertrain(problem: Any, vehicle: Any) -> str:
    type_by_id = {
        str(item.vehicle_type_id): str(item.powertrain_type).upper()
        for item in tuple(problem.vehicle_types or ())
    }
    return type_by_id.get(
        str(vehicle.vehicle_type),
        "BEV" if vehicle.battery_capacity_kwh is not None else "ICE",
    )


def _type_specific_quantity(
    problem_trip: Any,
    vehicle: Any,
    field_name: str,
) -> float | None:
    quantities = dict(getattr(problem_trip, field_name, {}) or {})
    vehicle_type = str(getattr(vehicle, "vehicle_type", "") or "").strip()
    for key in (vehicle_type, vehicle_type.upper()):
        if key not in quantities:
            continue
        try:
            value = float(quantities[key] or 0.0)
        except (TypeError, ValueError):
            return None
        return max(value, 0.0) if math.isfinite(value) else None
    return None


def _service_energy(
    problem: Any,
    problem_trip: Any,
    vehicle: Any,
    powertrain: str,
) -> tuple[float, float]:
    distance_km = max(
        _finite_float(getattr(problem_trip, "distance_km", 0.0)),
        0.0,
    )
    if powertrain == "BEV":
        # Reconstruct from the materialized trip demand, not from a legacy
        # vehicle-average rate.  The canonical builder may assign a calibrated
        # or literature-proxy quantity to each trip while preserving the daily
        # aggregate.  The validator remains independent of solver output: it
        # reads only the canonical problem input and serialized decisions.
        return trip_energy_kwh(problem, vehicle, problem_trip), 0.0
    type_specific_fuel = _type_specific_quantity(
        problem_trip,
        vehicle,
        "fuel_l_by_vehicle_type",
    )
    if type_specific_fuel is not None:
        return 0.0, type_specific_fuel
    rate = _finite_float(
        getattr(vehicle, "fuel_consumption_l_per_km", None),
        _finite_float(getattr(problem_trip, "fuel_l", 0.0))
        / max(distance_km, 1.0e-9),
    )
    return 0.0, distance_km * max(rate, 0.0)


def _record_violation(
    violations: list[Dict[str, Any]],
    *,
    code: str,
    vehicle_id: str = "",
    event_id: str = "",
    detail: str = "",
) -> None:
    violations.append(
        {
            "code": code,
            "vehicle_id": vehicle_id,
            "event_id": event_id,
            "detail": detail,
        }
    )


def validate_physical_event_schedule(
    *,
    problem: Any,
    serialized_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Rebuild and validate the physical vehicle/charger timeline.

    This intentionally does not consume solver ``validation_metrics``. It
    derives the event ledger from canonical problem inputs plus the serialized
    assignment/charging/refueling decisions.
    """

    trip_by_id = {str(item.trip_id): item for item in tuple(problem.trips or ())}
    dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
    vehicle_by_id = {
        str(item.vehicle_id): item for item in tuple(problem.vehicles or ())
    }
    charger_by_id = {
        str(item.charger_id): item for item in tuple(problem.chargers or ())
    }
    raw_paths = dict(serialized_result.get("vehicle_paths") or {})
    events: list[Dict[str, Any]] = []
    violations: list[Dict[str, Any]] = []
    assigned_trip_ids: list[str] = []
    feasibility_engine = FeasibilityEngine()

    for vehicle_id, raw_trip_ids in sorted(raw_paths.items()):
        vehicle_key = str(vehicle_id)
        vehicle = vehicle_by_id.get(vehicle_key)
        if vehicle is None:
            _record_violation(
                violations,
                code="unknown_vehicle",
                vehicle_id=vehicle_key,
            )
            continue
        path = [str(item) for item in list(raw_trip_ids or ())]
        assigned_trip_ids.extend(path)
        previous_problem_trip = None
        previous_dispatch_trip = None
        previous_ready_min = None
        for sequence, trip_id in enumerate(path):
            problem_trip = trip_by_id.get(trip_id)
            dispatch_trip = dispatch_trip_by_id.get(trip_id)
            if problem_trip is None or dispatch_trip is None:
                _record_violation(
                    violations,
                    code="unknown_trip",
                    vehicle_id=vehicle_key,
                    detail=trip_id,
                )
                continue
            powertrain = _vehicle_powertrain(problem, vehicle)
            service_energy_kwh, service_fuel_l = _service_energy(
                problem, problem_trip, vehicle, powertrain
            )
            origin = _trip_endpoint(dispatch_trip, origin=True)
            destination = _trip_endpoint(dispatch_trip, origin=False)
            if not str(getattr(dispatch_trip, "operator_id", "") or "").strip():
                _record_violation(
                    violations,
                    code="unknown_operator",
                    vehicle_id=vehicle_key,
                    detail=trip_id,
                )

            if previous_dispatch_trip is None:
                startup = evaluate_startup_feasibility(
                    dispatch_trip,
                    problem.dispatch_context,
                    str(vehicle.home_depot_id),
                )
                if not startup.feasible:
                    _record_violation(
                        violations,
                        code="startup_transition_infeasible",
                        vehicle_id=vehicle_key,
                        detail=str(startup.reason_code),
                    )
                startup_min = max(int(startup.deadhead_time_min or 0), 0)
                startup_energy = (
                    deadhead_before_trip_energy_kwh(
                        problem,
                        vehicle,
                        problem_trip,
                        previous_trip=None,
                    )
                    if powertrain == "BEV"
                    else 0.0
                )
                startup_fuel = (
                    max(startup_min, 0)
                    * _finite_float(
                        getattr(problem.metadata, "deadhead_speed_kmh", 0.0)
                        if not isinstance(problem.metadata, Mapping)
                        else problem.metadata.get("deadhead_speed_kmh"),
                        18.0,
                    )
                    / 60.0
                    * max(
                        _finite_float(
                            getattr(vehicle, "fuel_consumption_l_per_km", 0.0)
                        ),
                        0.0,
                    )
                    if powertrain == "ICE"
                    else 0.0
                )
                if startup_min > 0:
                    events.append(
                        _event(
                            event_id=f"{vehicle_key}:startup",
                            vehicle_id=vehicle_key,
                            event_type="startup_deadhead",
                            start_min=int(problem_trip.departure_min) - startup_min,
                            end_min=int(problem_trip.departure_min),
                            start_location=str(vehicle.home_depot_id),
                            end_location=origin,
                            energy_kwh=startup_energy,
                            fuel_l=startup_fuel,
                        )
                    )
            else:
                connection = feasibility_engine.can_connect(
                    previous_dispatch_trip,
                    dispatch_trip,
                    problem.dispatch_context,
                    str(vehicle.vehicle_type),
                )
                if not connection.feasible:
                    _record_violation(
                        violations,
                        code="infeasible_transition",
                        vehicle_id=vehicle_key,
                        detail=(
                            f"{previous_dispatch_trip.trip_id}->{trip_id}:"
                            f"{connection.reason_code}"
                        ),
                    )
                    if connection.reason_code == "missing_deadhead":
                        _record_violation(
                            violations,
                            code="location_discontinuity",
                            vehicle_id=vehicle_key,
                            detail=f"{previous_dispatch_trip.trip_id}->{trip_id}",
                        )
                turnaround_min = int(connection.turnaround_time_min or 0)
                deadhead_min = int(connection.deadhead_time_min or 0)
                ready_after_turnaround = (
                    int(previous_problem_trip.arrival_min) + turnaround_min
                )
                if deadhead_min > 0:
                    deadhead_energy = (
                        deadhead_before_trip_energy_kwh(
                            problem,
                            vehicle,
                            problem_trip,
                            previous_trip=previous_problem_trip,
                        )
                        if powertrain == "BEV"
                        else 0.0
                    )
                    events.append(
                        _event(
                            event_id=f"{vehicle_key}:connection:{sequence}",
                            vehicle_id=vehicle_key,
                            event_type="connection_deadhead",
                            start_min=ready_after_turnaround,
                            end_min=ready_after_turnaround + deadhead_min,
                            start_location=_trip_endpoint(
                                previous_dispatch_trip, origin=False
                            ),
                            end_location=origin,
                            energy_kwh=deadhead_energy,
                        )
                    )
                previous_ready_min = ready_after_turnaround + deadhead_min
                if previous_ready_min < int(problem_trip.departure_min):
                    events.append(
                        _event(
                            event_id=f"{vehicle_key}:waiting:{sequence}",
                            vehicle_id=vehicle_key,
                            event_type="waiting",
                            start_min=previous_ready_min,
                            end_min=int(problem_trip.departure_min),
                            start_location=origin,
                            end_location=origin,
                        )
                    )

            events.append(
                _event(
                    event_id=f"{vehicle_key}:service:{sequence}",
                    vehicle_id=vehicle_key,
                    event_type="service_trip",
                    start_min=int(problem_trip.departure_min),
                    end_min=int(problem_trip.arrival_min),
                    start_location=origin,
                    end_location=destination,
                    distance_km=max(
                        _finite_float(getattr(problem_trip, "distance_km", 0.0)),
                        0.0,
                    ),
                    energy_kwh=service_energy_kwh,
                    fuel_l=service_fuel_l,
                    trip_id=trip_id,
                )
            )
            previous_problem_trip = problem_trip
            previous_dispatch_trip = dispatch_trip

        if previous_problem_trip is not None:
            return_feasible, return_min = return_deadhead_min_to_home(
                problem, vehicle, previous_problem_trip
            )
            if not return_feasible:
                _record_violation(
                    violations,
                    code="terminal_return_infeasible",
                    vehicle_id=vehicle_key,
                )
            if return_min > 0:
                return_start = int(previous_problem_trip.arrival_min)
                return_energy = (
                    return_deadhead_energy_kwh(
                        problem, vehicle, previous_problem_trip
                    )
                    if _vehicle_powertrain(problem, vehicle) == "BEV"
                    else 0.0
                )
                events.append(
                    _event(
                        event_id=f"{vehicle_key}:terminal_return",
                        vehicle_id=vehicle_key,
                        event_type="terminal_return",
                        start_min=return_start,
                        end_min=return_start + int(return_min),
                        start_location=_trip_endpoint(
                            previous_dispatch_trip, origin=False
                        ),
                        end_location=str(vehicle.home_depot_id),
                        energy_kwh=return_energy,
                    )
                )

    horizon_start_min = normalize_horizon_start_min(
        getattr(problem.scenario, "horizon_start", None),
        default=int(problem.metadata.get("horizon_start_min", 0) or 0),
    )
    timestep_min = int(problem.scenario.timestep_min)
    charger_slot_usage: Counter[tuple[str, int]] = Counter()
    # One physical charging session may be split into grid/PV/BESS source
    # rows. Aggregate those source-allocation rows before checking vehicle and
    # charger occupancy so one session is never counted two or three times.
    charging_rows_by_session: dict[
        tuple[str, str, str, int], Dict[str, Any]
    ] = {}
    for raw_row in list(serialized_result.get("charging_schedule") or ()):
        raw_vehicle_id = str(raw_row.get("vehicle_id") or "").strip()
        raw_charger_id = str(raw_row.get("charger_id") or "").strip()
        raw_depot_id = str(
            raw_row.get("charging_depot_id") or ""
        ).strip()
        raw_slot_index = int(raw_row.get("slot_index") or 0)
        session_key = (
            raw_vehicle_id,
            raw_charger_id,
            raw_depot_id,
            raw_slot_index,
        )
        session = charging_rows_by_session.setdefault(
            session_key,
            {
                "vehicle_id": raw_vehicle_id,
                "charger_id": raw_charger_id,
                "charging_depot_id": raw_depot_id,
                "slot_index": raw_slot_index,
                "charge_kw": 0.0,
                "discharge_kw": 0.0,
                "energy_sources": [],
            },
        )
        session["charge_kw"] += _finite_float(raw_row.get("charge_kw"))
        session["discharge_kw"] += _finite_float(
            raw_row.get("discharge_kw")
        )
        energy_source = str(raw_row.get("energy_source") or "").strip()
        if energy_source:
            session["energy_sources"].append(energy_source)

    for index, row in enumerate(charging_rows_by_session.values()):
        vehicle_id = str(row.get("vehicle_id") or "").strip()
        charger_id = str(row.get("charger_id") or "").strip()
        charge_kw = _finite_float(row.get("charge_kw"))
        discharge_kw = _finite_float(row.get("discharge_kw"))
        if abs(charge_kw) <= 1.0e-9 and abs(discharge_kw) <= 1.0e-9:
            continue
        slot_index = int(row.get("slot_index") or 0)
        event_id = f"{vehicle_id}:charging:{slot_index}:{index}"
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle is None:
            _record_violation(
                violations,
                code="unknown_vehicle",
                vehicle_id=vehicle_id,
                event_id=event_id,
            )
            continue
        if not charger_id:
            _record_violation(
                violations,
                code="blank_charger_id",
                vehicle_id=vehicle_id,
                event_id=event_id,
            )
            continue
        charger = charger_by_id.get(charger_id)
        if charger is None:
            _record_violation(
                violations,
                code="unknown_charger_id",
                vehicle_id=vehicle_id,
                event_id=event_id,
                detail=charger_id,
            )
            continue
        charging_depot_id = str(row.get("charging_depot_id") or "").strip()
        if charging_depot_id != str(charger.depot_id):
            _record_violation(
                violations,
                code="charger_depot_mismatch",
                vehicle_id=vehicle_id,
                event_id=event_id,
                detail=(
                    f"row={charging_depot_id or '<blank>'},"
                    f"charger={charger.depot_id}"
                ),
            )
        compatible_ids = tuple(vehicle.compatible_charger_ids or ())
        if compatible_ids and charger_id not in compatible_ids:
            _record_violation(
                violations,
                code="charger_compatibility_violation",
                vehicle_id=vehicle_id,
                event_id=event_id,
                detail=charger_id,
            )
        vehicle_limit = _finite_float(
            getattr(vehicle, "charge_power_max_kw", None),
            float(charger.power_kw),
        )
        allowed_power = min(float(charger.power_kw), vehicle_limit)
        if charge_kw > allowed_power + 1.0e-6:
            _record_violation(
                violations,
                code="charger_power_violation",
                vehicle_id=vehicle_id,
                event_id=event_id,
                detail=f"charge_kw={charge_kw},allowed_kw={allowed_power}",
            )
        charger_slot_usage[(charger_id, slot_index)] += 1
        start_min = horizon_start_min + slot_index * timestep_min
        events.append(
            _event(
                event_id=event_id,
                vehicle_id=vehicle_id,
                event_type="charging",
                start_min=start_min,
                end_min=start_min + timestep_min,
                start_location=str(charger.depot_id),
                end_location=str(charger.depot_id),
                energy_kwh=charge_kw * timestep_min / 60.0,
                power_kw=charge_kw,
                power_limit_kw=allowed_power,
                charger_id=charger_id,
                depot_id=str(charger.depot_id),
                source_artifact="executed_charging_schedule",
            )
        )

    for (charger_id, slot_index), count in charger_slot_usage.items():
        ports = max(int(charger_by_id[charger_id].simultaneous_ports or 1), 1)
        if count > ports:
            _record_violation(
                violations,
                code="charger_concurrency_violation",
                detail=(
                    f"charger_id={charger_id},slot_index={slot_index},"
                    f"count={count},ports={ports}"
                ),
            )

    for index, row in enumerate(
        list(serialized_result.get("refueling_schedule") or ())
    ):
        vehicle_id = str(row.get("vehicle_id") or "").strip()
        slot_index = int(row.get("slot_index") or 0)
        start_min = horizon_start_min + slot_index * timestep_min
        location_id = str(row.get("location_id") or "").strip()
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle is None:
            _record_violation(
                violations,
                code="unknown_vehicle",
                vehicle_id=vehicle_id,
                detail=f"refueling row {index} references an unknown vehicle",
            )
        elif _vehicle_powertrain(problem, vehicle) != "ICE":
            _record_violation(
                violations,
                code="refueling_powertrain_violation",
                vehicle_id=vehicle_id,
                detail=f"refueling row {index} is assigned to a non-ICE vehicle",
            )
        if not location_id:
            _record_violation(
                violations,
                code="refueling_location_violation",
                vehicle_id=vehicle_id,
                detail=f"refueling row {index} has no physical location",
            )
        events.append(
            _event(
                event_id=f"{vehicle_id}:refueling:{slot_index}:{index}",
                vehicle_id=vehicle_id,
                event_type="refueling",
                start_min=start_min,
                end_min=start_min + timestep_min,
                start_location=location_id,
                end_location=location_id,
                fuel_l=-max(_finite_float(row.get("refuel_liters")), 0.0),
                depot_id=location_id,
                source_artifact="executed_refueling_schedule",
            )
        )

    events_by_vehicle: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    for item in events:
        if item["event_type"] in _EXCLUSIVE_EVENT_TYPES:
            events_by_vehicle[item["vehicle_id"]].append(item)
    for vehicle_id, vehicle_events in events_by_vehicle.items():
        ordered = sorted(
            vehicle_events,
            key=lambda item: (
                int(item["start_min"]),
                int(item["end_min"]),
                str(item["event_id"]),
            ),
        )
        for left, right in zip(ordered, ordered[1:]):
            if int(left["end_min"]) > int(right["start_min"]):
                _record_violation(
                    violations,
                    code="vehicle_time_overlap",
                    vehicle_id=vehicle_id,
                    event_id=str(right["event_id"]),
                    detail=f"{left['event_id']} overlaps {right['event_id']}",
                )

    movement_event_types = {
        "startup_deadhead",
        "service_trip",
        "connection_deadhead",
        "terminal_return",
    }
    for vehicle_id, vehicle_events in events_by_vehicle.items():
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle is None:
            continue
        movement_events = sorted(
            (
                item
                for item in vehicle_events
                if item["event_type"] in movement_event_types
            ),
            key=lambda item: (
                int(item["start_min"]),
                int(item["end_min"]),
                str(item["event_id"]),
            ),
        )
        resource_events = (
            item
            for item in vehicle_events
            if item["event_type"] in {"charging", "refueling"}
        )
        for resource_event in resource_events:
            resource_start = int(resource_event["start_min"])
            resource_end = int(resource_event["end_min"])
            before = [
                item
                for item in movement_events
                if int(item["end_min"]) <= resource_start
            ]
            after = [
                item
                for item in movement_events
                if int(item["start_min"]) >= resource_end
            ]
            location_before = (
                str(before[-1]["end_location"])
                if before
                else str(vehicle.home_depot_id)
            )
            location_after = (
                str(after[0]["start_location"])
                if after
                else location_before
            )
            resource_location = str(resource_event["depot_id"])
            before_at_resource = problem.dispatch_context.locations_equivalent(
                location_before,
                resource_location,
            )
            after_at_resource = problem.dispatch_context.locations_equivalent(
                location_after,
                resource_location,
            )
            if not before_at_resource or not after_at_resource:
                violation_code = (
                    "charging_location_violation"
                    if resource_event["event_type"] == "charging"
                    else "refueling_location_violation"
                )
                _record_violation(
                    violations,
                    code=violation_code,
                    vehicle_id=vehicle_id,
                    event_id=str(resource_event["event_id"]),
                    detail=(
                        f"before={location_before},resource={resource_location},"
                        f"after={location_after}"
                    ),
                )

    all_trip_ids = set(trip_by_id)
    assigned_counts = Counter(assigned_trip_ids)
    unassigned = sorted(all_trip_ids.difference(assigned_counts))
    duplicates = sorted(
        trip_id for trip_id, count in assigned_counts.items() if count > 1
    )

    # Independent resource balances from the event ledger.
    charging_efficiency = _finite_float(
        problem.metadata.get("charging_efficiency"),
        0.95,
    )
    if not 0.0 < charging_efficiency <= 1.0:
        charging_efficiency = 0.95
    vehicle_soc_events: list[Dict[str, Any]] = []
    for vehicle_id, vehicle in vehicle_by_id.items():
        vehicle_events = sorted(
            events_by_vehicle.get(vehicle_id, ()),
            key=lambda item: (int(item["start_min"]), str(item["event_id"])),
        )
        powertrain = _vehicle_powertrain(problem, vehicle)
        if powertrain == "BEV":
            initial_soc = _finite_float(vehicle.initial_soc)
            soc = initial_soc
            capacity = _finite_float(vehicle.battery_capacity_kwh)
            reserve = _finite_float(vehicle.reserve_soc)
            vehicle_soc_events.append(
                {
                    "vehicle_id": vehicle_id,
                    "event_id": f"{vehicle_id}:initial_state",
                    "event_type": "initial_state",
                    "time_min": int(horizon_start_min),
                    "soc_before_kwh": initial_soc,
                    "soc_after_kwh": initial_soc,
                    "soc_before_percent": (
                        100.0 * initial_soc / capacity
                        if capacity > 0.0
                        else 0.0
                    ),
                    "soc_after_percent": (
                        100.0 * initial_soc / capacity
                        if capacity > 0.0
                        else 0.0
                    ),
                    "reserve_soc_kwh": reserve,
                    "reserve_soc_percent": (
                        100.0 * reserve / capacity
                        if capacity > 0.0
                        else 0.0
                    ),
                    "battery_capacity_kwh": capacity,
                    "charging_efficiency": charging_efficiency,
                    "source_artifact": "scenario_fleet_contract",
                }
            )
            for item in vehicle_events:
                soc_before = soc
                if item["event_type"] == "charging":
                    soc += float(item["energy_kwh"]) * charging_efficiency
                else:
                    soc -= max(float(item["energy_kwh"]), 0.0)
                vehicle_soc_events.append(
                    {
                        "vehicle_id": vehicle_id,
                        "event_id": str(item["event_id"]),
                        "event_type": str(item["event_type"]),
                        "time_min": int(item["end_min"]),
                        "soc_before_kwh": soc_before,
                        "soc_after_kwh": soc,
                        "soc_before_percent": (
                            100.0 * soc_before / capacity
                            if capacity > 0.0
                            else 0.0
                        ),
                        "soc_after_percent": (
                            100.0 * soc / capacity
                            if capacity > 0.0
                            else 0.0
                        ),
                        "reserve_soc_kwh": reserve,
                        "reserve_soc_percent": (
                            100.0 * reserve / capacity
                            if capacity > 0.0
                            else 0.0
                        ),
                        "battery_capacity_kwh": capacity,
                        "charging_efficiency": charging_efficiency,
                        "source_artifact": str(item["source_artifact"]),
                    }
                )
                if soc < reserve - 1.0e-6:
                    _record_violation(
                        violations,
                        code="ev_soc_lower_violation",
                        vehicle_id=vehicle_id,
                        event_id=str(item["event_id"]),
                        detail=f"soc={soc},reserve={reserve}",
                    )
                if soc > capacity + 1.0e-6:
                    _record_violation(
                        violations,
                        code="ev_soc_upper_violation",
                        vehicle_id=vehicle_id,
                        event_id=str(item["event_id"]),
                        detail=f"soc={soc},capacity={capacity}",
                    )
            terminal_policy = normalize_bev_terminal_soc_policy(
                problem.metadata.get("bev_terminal_soc_policy"),
                has_explicit_target=(
                    problem.metadata.get("final_soc_target_percent")
                    is not None
                ),
            )
            if terminal_policy is BevTerminalSocPolicy.RETURN_TO_INITIAL:
                terminal_contract = bev_terminal_numeric_acceptance_contract(
                    problem.metadata,
                    gurobi_feasibility_tol=None,
                )
                scientific_tolerance = float(
                    terminal_contract["scientific_tolerance_kwh"]
                )
                numeric_margin = float(
                    terminal_contract["numeric_comparison_margin_kwh"]
                )
                terminal_tolerance = scientific_tolerance + numeric_margin
                terminal_deviation = soc - initial_soc
                if abs(terminal_deviation) > terminal_tolerance:
                    _record_violation(
                        violations,
                        code="bev_terminal_soc_violation",
                        vehicle_id=vehicle_id,
                        detail=(
                            f"terminal_deviation_kwh={terminal_deviation},"
                            f"scientific_tolerance_kwh={scientific_tolerance},"
                            f"numeric_margin_kwh={numeric_margin},"
                            f"acceptance_limit_kwh={terminal_tolerance}"
                        ),
                    )
        elif powertrain == "ICE":
            fuel = _finite_float(vehicle.initial_fuel_l)
            reserve = _finite_float(vehicle.fuel_reserve_l)
            tank_capacity = _finite_float(vehicle.fuel_tank_capacity_l)
            for item in vehicle_events:
                fuel -= float(item["fuel_l"])
                if fuel < reserve - 1.0e-6:
                    _record_violation(
                        violations,
                        code="fuel_lower_violation",
                        vehicle_id=vehicle_id,
                        event_id=str(item["event_id"]),
                        detail=f"fuel={fuel},reserve={reserve}",
                    )
                if tank_capacity > 0.0 and fuel > tank_capacity + 1.0e-6:
                    _record_violation(
                        violations,
                        code="fuel_upper_violation",
                        vehicle_id=vehicle_id,
                        event_id=str(item["event_id"]),
                        detail=f"fuel={fuel},capacity={tank_capacity}",
                    )

    violation_counts = Counter(str(item["code"]) for item in violations)
    metrics = {
        "unassigned_trip_count": len(unassigned),
        "duplicate_trip_count": len(duplicates),
        "unknown_vehicle_count": violation_counts["unknown_vehicle"],
        "vehicle_time_overlap_count": violation_counts["vehicle_time_overlap"],
        "infeasible_transition_count": (
            violation_counts["infeasible_transition"]
            + violation_counts["startup_transition_infeasible"]
            + violation_counts["terminal_return_infeasible"]
        ),
        "location_discontinuity_count": violation_counts[
            "location_discontinuity"
        ],
        "unknown_operator_count": violation_counts["unknown_operator"],
        "blank_charger_id_count": violation_counts["blank_charger_id"],
        "unknown_charger_id_count": violation_counts["unknown_charger_id"],
        "charger_depot_mismatch_count": violation_counts[
            "charger_depot_mismatch"
        ],
        "charging_location_violation_count": violation_counts[
            "charging_location_violation"
        ],
        "charger_compatibility_violation_count": violation_counts[
            "charger_compatibility_violation"
        ],
        "charger_power_violation_count": violation_counts[
            "charger_power_violation"
        ],
        "charger_concurrency_violation_count": violation_counts[
            "charger_concurrency_violation"
        ],
        "refueling_location_violation_count": violation_counts[
            "refueling_location_violation"
        ],
        "refueling_powertrain_violation_count": violation_counts[
            "refueling_powertrain_violation"
        ],
        "ev_soc_lower_violation_count": violation_counts[
            "ev_soc_lower_violation"
        ],
        "ev_soc_upper_violation_count": violation_counts[
            "ev_soc_upper_violation"
        ],
        "bev_terminal_soc_violation_count": violation_counts[
            "bev_terminal_soc_violation"
        ],
        "fuel_lower_violation_count": violation_counts["fuel_lower_violation"],
        "fuel_upper_violation_count": violation_counts["fuel_upper_violation"],
    }
    accepted = all(int(metrics[key]) == 0 for key in REQUIRED_ZERO_METRICS)
    return {
        "schema_version": PHYSICAL_EVENT_VALIDATION_SCHEMA_VERSION,
        "accepted": accepted,
        "status": "VALID" if accepted else "INVALID",
        "metrics": metrics,
        "unassigned_trip_ids": unassigned,
        "duplicate_trip_ids": duplicates,
        "events": sorted(
            events,
            key=lambda item: (
                str(item["vehicle_id"]),
                int(item["start_min"]),
                str(item["event_id"]),
            ),
        ),
        "vehicle_soc_events": sorted(
            vehicle_soc_events,
            key=lambda item: (
                str(item["vehicle_id"]),
                int(item["time_min"]),
                str(item["event_id"]),
            ),
        ),
        "violations": violations,
        "semantics": (
            "Independent event reconstruction from canonical problem inputs "
            "and serialized assignment/charging/refueling decisions."
        ),
    }
