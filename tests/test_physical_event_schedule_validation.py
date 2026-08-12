from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import csv
from pathlib import Path

from bff.services.optimization_run.rolling_chain import (
    _persist_physical_event_artifacts,
    _zero_hard_validation_counts,
)
from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    ChargerDefinition,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.optimization.validation.physical_event_schedule import (
    PHYSICAL_EVENT_VALIDATION_SCHEMA_VERSION,
    REQUIRED_ZERO_METRICS,
    validate_physical_event_schedule,
)


def _problem(
    *,
    compatible_charger_ids: tuple[str, ...] = ("charger-1",),
) -> CanonicalOptimizationProblem:
    dispatch_trips = [
        Trip(
            trip_id="trip-1",
            route_id="route-1",
            origin="depot-a",
            destination="stop-1",
            departure_time="08:00",
            arrival_time="08:30",
            distance_km=10.0,
            allowed_vehicle_types=("BEV",),
            operator_id="operator-1",
        ),
        Trip(
            trip_id="trip-2",
            route_id="route-1",
            origin="stop-1",
            destination="depot-a",
            departure_time="09:00",
            arrival_time="09:30",
            distance_km=10.0,
            allowed_vehicle_types=("BEV",),
            operator_id="operator-1",
        ),
    ]
    context = DispatchContext(
        service_date="2025-08-05",
        trips=dispatch_trips,
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        default_turnaround_min=0,
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="physical-validation",
            timestep_min=15,
            horizon_start="00:00",
        ),
        dispatch_context=context,
        trips=tuple(
            ProblemTrip(
                trip_id=trip.trip_id,
                route_id=trip.route_id,
                origin=trip.origin,
                destination=trip.destination,
                departure_min=trip.departure_min,
                arrival_min=trip.arrival_min,
                distance_km=trip.distance_km,
                allowed_vehicle_types=trip.allowed_vehicle_types,
                energy_kwh=trip.distance_km,
            )
            for trip in dispatch_trips
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="depot-a",
                initial_soc=200.0,
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
                energy_consumption_kwh_per_km=1.0,
                charge_power_max_kw=90.0,
                compatible_charger_ids=compatible_charger_ids,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        ),
        chargers=(
            ChargerDefinition(
                charger_id="charger-1",
                depot_id="depot-a",
                power_kw=90.0,
                simultaneous_ports=1,
            ),
        ),
    )


def _result() -> dict:
    return {
        "vehicle_paths": {"bev-1": ["trip-1", "trip-2"]},
        "charging_schedule": [],
        "refueling_schedule": [],
    }


def _charging_row(**overrides: object) -> dict:
    row = {
        "vehicle_id": "bev-1",
        "charger_id": "charger-1",
        "charging_depot_id": "depot-a",
        "slot_index": 32,
        "charge_kw": 60.0,
        "discharge_kw": 0.0,
    }
    row.update(overrides)
    return row


def test_valid_schedule_is_reconstructed_independently() -> None:
    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=_result(),
    )

    assert validation["schema_version"] == PHYSICAL_EVENT_VALIDATION_SCHEMA_VERSION
    assert validation["accepted"] is True
    assert validation["status"] == "VALID"
    assert set(validation["metrics"]) == set(REQUIRED_ZERO_METRICS)
    assert all(value == 0 for value in validation["metrics"].values())
    assert [
        event["event_type"] for event in validation["events"]
    ] == ["service_trip", "waiting", "service_trip"]
    assert [
        event["event_type"] for event in validation["vehicle_soc_events"]
    ] == ["initial_state", "service_trip", "service_trip"]
    assert validation["vehicle_soc_events"][0]["soc_after_kwh"] == 200.0
    assert validation["vehicle_soc_events"][-1]["soc_after_kwh"] == 180.0


def test_trip_specific_bev_demand_is_the_independent_soc_source() -> None:
    problem = _problem()
    trips = tuple(
        replace(
            trip,
            energy_kwh_by_vehicle_type={"BEV": 15.0},
            energy_model_id="literature_proxy_v1",
        )
        for trip in problem.trips
    )

    validation = validate_physical_event_schedule(
        problem=replace(problem, trips=trips),
        serialized_result=_result(),
    )

    service_events = [
        event
        for event in validation["events"]
        if event["event_type"] == "service_trip"
    ]
    assert [event["energy_kwh"] for event in service_events] == [15.0, 15.0]
    assert validation["vehicle_soc_events"][-1]["soc_after_kwh"] == 170.0


def test_trip_specific_ice_demand_is_the_independent_fuel_source() -> None:
    problem = _problem()
    ice_vehicle = replace(
        problem.vehicles[0],
        vehicle_type="ICE",
        initial_soc=None,
        battery_capacity_kwh=None,
        reserve_soc=None,
        initial_fuel_l=50.0,
        fuel_tank_capacity_l=100.0,
        fuel_reserve_l=0.0,
        fuel_consumption_l_per_km=0.2,
    )
    ice_type = replace(
        problem.vehicle_types[0],
        vehicle_type_id="ICE",
        powertrain_type="ICE",
        battery_capacity_kwh=None,
        energy_consumption_kwh_per_km=None,
        fuel_tank_capacity_l=100.0,
        fuel_consumption_l_per_km=0.2,
    )
    trips = tuple(
        replace(
            trip,
            allowed_vehicle_types=("ICE",),
            fuel_l_by_vehicle_type={"ICE": 3.0},
            energy_model_id="literature_proxy_v1",
        )
        for trip in problem.trips
    )
    result = _result()
    result["vehicle_paths"] = {"bev-1": ["trip-1", "trip-2"]}

    validation = validate_physical_event_schedule(
        problem=replace(
            problem,
            trips=trips,
            vehicles=(ice_vehicle,),
            vehicle_types=(ice_type,),
        ),
        serialized_result=result,
    )

    service_events = [
        event
        for event in validation["events"]
        if event["event_type"] == "service_trip"
    ]
    assert [event["fuel_l"] for event in service_events] == [3.0, 3.0]


def test_service_and_charging_overlap_fails() -> None:
    result = _result()
    result["charging_schedule"] = [_charging_row()]

    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=result,
    )

    assert validation["accepted"] is False
    assert validation["metrics"]["vehicle_time_overlap_count"] == 1


def test_blank_and_unknown_chargers_fail_closed() -> None:
    for charger_id, expected_metric in (
        ("", "blank_charger_id_count"),
        ("missing-charger", "unknown_charger_id_count"),
    ):
        result = _result()
        result["charging_schedule"] = [
            _charging_row(charger_id=charger_id, slot_index=40)
        ]

        validation = validate_physical_event_schedule(
            problem=_problem(),
            serialized_result=result,
        )

        assert validation["accepted"] is False
        assert validation["metrics"][expected_metric] == 1


def test_charger_depot_compatibility_and_power_are_independent_checks() -> None:
    result = _result()
    result["charging_schedule"] = [
        _charging_row(
            charging_depot_id="depot-b",
            charge_kw=91.0,
            slot_index=40,
        )
    ]

    validation = validate_physical_event_schedule(
        problem=_problem(compatible_charger_ids=("other-charger",)),
        serialized_result=result,
    )

    assert validation["metrics"]["charger_depot_mismatch_count"] == 1
    assert validation["metrics"]["charger_compatibility_violation_count"] == 1
    assert validation["metrics"]["charger_power_violation_count"] == 1


def test_source_split_rows_are_one_physical_charging_session() -> None:
    result = _result()
    result["charging_schedule"] = [
        _charging_row(
            slot_index=40,
            charge_kw=20.0,
            energy_source="grid",
        ),
        _charging_row(
            slot_index=40,
            charge_kw=30.0,
            energy_source="pv",
        ),
    ]

    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=result,
    )

    charging_events = [
        event
        for event in validation["events"]
        if event["event_type"] == "charging"
    ]
    assert validation["accepted"] is True
    assert len(charging_events) == 1
    assert charging_events[0]["energy_kwh"] == 12.5
    assert charging_events[0]["power_kw"] == 50.0
    assert charging_events[0]["power_limit_kw"] == 90.0
    charging_soc_event = next(
        event
        for event in validation["vehicle_soc_events"]
        if event["event_type"] == "charging"
    )
    assert charging_soc_event["soc_after_kwh"] == 180.0 + 12.5 * 0.95


def test_charging_while_vehicle_waits_away_from_depot_fails() -> None:
    result = _result()
    result["charging_schedule"] = [
        _charging_row(slot_index=34, charge_kw=20.0)
    ]

    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=result,
    )

    assert validation["accepted"] is False
    assert validation["metrics"]["vehicle_time_overlap_count"] == 0
    assert validation["metrics"]["charging_location_violation_count"] == 1


def test_refueling_requires_ice_vehicle_and_physical_location() -> None:
    result = _result()
    result["refueling_schedule"] = [
        {
            "vehicle_id": "bev-1",
            "slot_index": 40,
            "location_id": "",
            "refuel_liters": 10.0,
        }
    ]

    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=result,
    )

    assert validation["accepted"] is False
    assert validation["metrics"]["refueling_powertrain_violation_count"] == 1
    assert validation["metrics"]["refueling_location_violation_count"] >= 1


def test_refueling_unknown_vehicle_fails_closed() -> None:
    result = _result()
    result["refueling_schedule"] = [
        {
            "vehicle_id": "missing-vehicle",
            "slot_index": 40,
            "location_id": "depot-a",
            "refuel_liters": 10.0,
        }
    ]

    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=result,
    )

    assert validation["accepted"] is False
    assert validation["metrics"]["unknown_vehicle_count"] == 1


def test_duplicate_trip_and_low_soc_fail() -> None:
    problem = _problem()
    low_soc_vehicle = replace(problem.vehicles[0], initial_soc=35.0)
    problem = replace(problem, vehicles=(low_soc_vehicle,))
    result = _result()
    result["vehicle_paths"]["bev-1"] = ["trip-1", "trip-1"]

    validation = validate_physical_event_schedule(
        problem=problem,
        serialized_result=result,
    )

    assert validation["metrics"]["duplicate_trip_count"] == 1
    assert validation["metrics"]["unassigned_trip_count"] == 1
    assert validation["metrics"]["ev_soc_lower_violation_count"] >= 1


def test_return_to_initial_terminal_soc_is_independently_checked() -> None:
    problem = _problem()
    problem = replace(
        problem,
        metadata={
            "bev_terminal_soc_policy": "return_to_initial",
            "bev_terminal_soc_equality_tolerance_kwh": 1.0e-6,
        },
    )

    validation = validate_physical_event_schedule(
        problem=problem,
        serialized_result=_result(),
    )

    assert validation["accepted"] is False
    assert validation["metrics"]["bev_terminal_soc_violation_count"] == 1


def test_required_physical_metric_missing_or_wrong_type_is_not_zero() -> None:
    complete = {key: 0 for key in REQUIRED_ZERO_METRICS}

    assert _zero_hard_validation_counts(complete) is True

    missing = deepcopy(complete)
    missing.pop("unknown_charger_id_count")
    assert _zero_hard_validation_counts(missing) is False

    wrong_type = deepcopy(complete)
    wrong_type["unknown_charger_id_count"] = "0"
    assert _zero_hard_validation_counts(wrong_type) is False


def test_persists_event_soc_and_charger_csv_evidence(
    tmp_path: Path,
) -> None:
    result = _result()
    result["charging_schedule"] = [
        _charging_row(slot_index=40, charge_kw=45.0)
    ]
    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=result,
    )

    _persist_physical_event_artifacts(
        run_dir=tmp_path,
        event_validation=validation,
    )

    with (
        tmp_path / "graph" / "vehicle_soc_event_timeline.csv"
    ).open(encoding="utf-8-sig", newline="") as handle:
        soc_rows = list(csv.DictReader(handle))
    with (
        tmp_path / "graph" / "charger_occupancy_timeline.csv"
    ).open(encoding="utf-8-sig", newline="") as handle:
        charger_rows = list(csv.DictReader(handle))
    assert soc_rows[0]["event_type"] == "initial_state"
    assert any(row["event_type"] == "charging" for row in soc_rows)
    assert charger_rows[0]["power_kw"] == "45.0"
    assert charger_rows[0]["power_limit_kw"] == "90.0"
