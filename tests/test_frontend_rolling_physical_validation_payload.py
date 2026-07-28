from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from bff.services.optimization_run import rolling_chain
from bff.services.optimization_run.rolling_chain import RollingChainExecutionError
from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    ChargerDefinition,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.optimization.rolling.acceptance import (
    ROLLING_CHAIN_REQUIRED_ACCEPTANCE_CHECKS,
)
from src.optimization.validation.physical_event_schedule import (
    PHYSICAL_EVENT_VALIDATION_SCHEMA_VERSION,
    REQUIRED_ZERO_METRICS,
    validate_physical_event_schedule,
)


def _problem() -> CanonicalOptimizationProblem:
    dispatch_trips = (
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
    )
    context = DispatchContext(
        service_date="2025-08-05",
        trips=list(dispatch_trips),
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
            scenario_id="physical-validation-payload",
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
                compatible_charger_ids=("charger-1",),
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


def _canonical_result() -> dict[str, object]:
    return {
        "feasible": True,
        "trip_count_unserved": 0,
        "vehicle_paths": {"bev-1": ["trip-1", "trip-2"]},
        "served_trip_ids": ["trip-1", "trip-2"],
        "unserved_trip_ids": [],
        "charging_schedule": [
            {
                "vehicle_id": "bev-1",
                "charger_id": "charger-1",
                "charging_depot_id": "depot-a",
                "slot_index": 40,
                "charge_kw": 1.0,
                "discharge_kw": 0.0,
            }
        ],
        "refueling_schedule": [],
        "solver_metadata": {
            "validation_metrics": {
                "all_required_validation_checks_passed": True,
            }
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_executed_charging(path: Path, *, charge_kw: float = 20.0) -> list[dict[str, object]]:
    rows = [
        {
            "vehicle_id": "bev-1",
            "charger_id": "charger-1",
            "charging_depot_id": "depot-a",
            "slot_index": 40,
            "charge_kw": charge_kw,
            "discharge_kw": 0.0,
        }
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _chain_for(canonical_path: Path) -> dict[str, object]:
    return {
        "chain_accepted": True,
        "acceptance_checks": {
            key: True for key in ROLLING_CHAIN_REQUIRED_ACCEPTANCE_CHECKS
        },
        "day_ahead_result_sha256": hashlib.sha256(
            canonical_path.read_bytes()
        ).hexdigest(),
        "day_ahead_assignment_hash": "a" * 64,
        "trip_input_hash": "b" * 64,
        "vehicle_input_hash": "c" * 64,
        "scenario_fleet_contract_hash": "d" * 64,
        "active_vehicle_id_hash": "e" * 64,
        "vehicle_parameter_hash": "f" * 64,
        "initial_state_hash": "1" * 64,
        "initial_soc_input_hash": "2" * 64,
        "charger_configuration_hash": "3" * 64,
        "service_date": "2025-08-05",
    }


def _write_finalizer_inputs(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    canonical = _canonical_result()
    canonical_path = tmp_path / "canonical_solver_result.json"
    _write_json(canonical_path, canonical)
    chain = _chain_for(canonical_path)
    _write_json(
        tmp_path / "rolling_hourly_chain" / "rolling_chain_summary.json", chain
    )
    _write_json(
        tmp_path / "rolling_hourly_chain" / "executed_day_accounting.json",
        {"eligible": True},
    )
    _write_json(tmp_path / "input_audit.json", {"service_id": "WEEKDAY"})
    _write_executed_charging(
        tmp_path / "rolling_hourly_chain" / "charging_schedule.csv"
    )
    return canonical, chain


def test_finalizer_passes_canonical_assignment_to_independent_validator(
    tmp_path: Path,
) -> None:
    """Reproduce the wrapper/schema boundary that hid every service trip."""

    canonical, _chain = _write_finalizer_inputs(tmp_path)
    wrapper = {
        "scenario_id": "scenario-1",
        "canonical_solver_result": canonical,
    }
    captured: dict[str, object] = {}
    metrics = {key: 0 for key in REQUIRED_ZERO_METRICS}
    metrics["unassigned_trip_count"] = 2

    def capture_payload(*, problem: object, serialized_result: object) -> dict[str, object]:
        captured["payload"] = dict(serialized_result)
        return {
            "schema_version": PHYSICAL_EVENT_VALIDATION_SCHEMA_VERSION,
            "accepted": False,
            "metrics": metrics,
            "events": [],
            "vehicle_soc_events": [],
            "violations": [],
        }

    with mock.patch.object(
        rolling_chain,
        "validate_physical_event_schedule",
        side_effect=capture_payload,
    ):
        with pytest.raises(
            RollingChainExecutionError,
            match="Physical schedule validation failed",
        ) as raised:
            rolling_chain.finalize_frontend_rolling_evidence(
                run_dir=tmp_path,
                scenario={"simulation_config": {}},
                problem=_problem(),
                optimization_result=wrapper,
            )

    assert '"unassigned_trip_count": 2' in str(raised.value)
    payload = dict(captured["payload"])
    assert payload["vehicle_paths"] == canonical["vehicle_paths"]
    assert payload["refueling_schedule"] == canonical["refueling_schedule"]
    manifest = json.loads(
        (tmp_path / "physical_validation_input_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["assignment_source"] == "canonical_solver_result.json"
    assert manifest["charging_source"] == (
        "rolling_hourly_chain/charging_schedule.csv"
    )


def test_executed_validation_payload_uses_canonical_assignment_and_rolling_charging(
    tmp_path: Path,
) -> None:
    canonical, chain = _write_finalizer_inputs(tmp_path)
    executed_rows = _write_executed_charging(
        tmp_path / "rolling_hourly_chain" / "charging_schedule.csv",
        charge_kw=20.0,
    )

    payload, manifest = rolling_chain._build_executed_physical_validation_payload(
        run_dir=tmp_path,
        problem=_problem(),
        chain=chain,
    )
    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=payload,
    )

    assert payload["vehicle_paths"] == canonical["vehicle_paths"]
    assert payload["refueling_schedule"] == canonical["refueling_schedule"]
    assert payload["charging_schedule"] == [
        {key: str(value) for key, value in row.items()} for row in executed_rows
    ]
    assert payload["charging_schedule"] != canonical["charging_schedule"]
    assert manifest["assignment_source"] == "canonical_solver_result.json"
    assert manifest["charging_source"] == "rolling_hourly_chain/charging_schedule.csv"
    assert manifest["assigned_trip_occurrence_count"] == 2
    assert manifest["problem_trip_count"] == 2
    assert validation["metrics"]["unassigned_trip_count"] == 0
    assert [event["event_type"] for event in validation["events"]].count(
        "service_trip"
    ) == 2


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda canonical: canonical.update({"vehicle_paths": {}}),
            "empty vehicle_paths",
        ),
        (
            lambda canonical: canonical.update({"vehicle_paths": "invalid"}),
            "missing vehicle_paths",
        ),
        (
            lambda canonical: canonical.update({"served_trip_ids": ["trip-1"]}),
            "disagree",
        ),
    ],
)
def test_executed_validation_payload_rejects_bad_canonical_assignment(
    tmp_path: Path,
    mutate: object,
    error: str,
) -> None:
    canonical, _chain = _write_finalizer_inputs(tmp_path)
    mutate(canonical)
    canonical_path = tmp_path / "canonical_solver_result.json"
    _write_json(canonical_path, canonical)
    chain = _chain_for(canonical_path)

    with pytest.raises(RollingChainExecutionError, match=error):
        rolling_chain._build_executed_physical_validation_payload(
            run_dir=tmp_path,
            problem=_problem(),
            chain=chain,
        )


def test_executed_validation_payload_rejects_canonical_sha_mismatch(
    tmp_path: Path,
) -> None:
    _canonical, chain = _write_finalizer_inputs(tmp_path)
    chain["day_ahead_result_sha256"] = "0" * 64

    with pytest.raises(RollingChainExecutionError, match="SHA-256 does not match"):
        rolling_chain._build_executed_physical_validation_payload(
            run_dir=tmp_path,
            problem=_problem(),
            chain=chain,
        )


@pytest.mark.parametrize(
    ("terminal_deviation_kwh", "accepted"),
    [
        (1.0000005e-6, True),
        (1.0011e-6, False),
    ],
)
def test_physical_validator_uses_shared_terminal_numeric_contract(
    terminal_deviation_kwh: float,
    accepted: bool,
) -> None:
    problem = replace(
        _problem(),
        metadata={
            "bev_terminal_soc_policy": "return_to_initial",
            "bev_terminal_soc_scientific_tolerance_kwh": 1.0e-6,
            "bev_terminal_soc_numeric_margin_kwh": 1.0e-9,
            "stage2_gurobi_feasibility_tol": 1.0e-9,
        },
    )
    charge_kw = (20.0 + terminal_deviation_kwh) / (0.25 * 0.95)
    serialized_result = _canonical_result()
    serialized_result["charging_schedule"] = [
        {
            "vehicle_id": "bev-1",
            "charger_id": "charger-1",
            "charging_depot_id": "depot-a",
            "slot_index": 40,
            "charge_kw": charge_kw,
            "discharge_kw": 0.0,
        }
    ]

    validation = validate_physical_event_schedule(
        problem=problem,
        serialized_result=serialized_result,
    )

    assert validation["accepted"] is accepted
    assert validation["metrics"]["bev_terminal_soc_violation_count"] == (
        0 if accepted else 1
    )


def test_physical_validator_keeps_genuine_charger_violation() -> None:
    """The canonical payload source must not suppress real violations."""

    serialized_result = _canonical_result()
    serialized_result["charging_schedule"] = [
        {
            "vehicle_id": "bev-1",
            "charger_id": "charger-1",
            "charging_depot_id": "wrong-depot",
            "slot_index": 40,
            "charge_kw": 20.0,
            "discharge_kw": 0.0,
        }
    ]

    validation = validate_physical_event_schedule(
        problem=_problem(),
        serialized_result=serialized_result,
    )

    assert validation["accepted"] is False
    assert validation["metrics"]["charger_depot_mismatch_count"] == 1


@pytest.mark.parametrize("invalid_count", (0.5, -0.5, float("nan")))
def test_hard_validation_zero_check_rejects_nonzero_or_nonfinite_counts(
    invalid_count: float,
) -> None:
    metrics = {key: 0 for key in REQUIRED_ZERO_METRICS}
    metrics["unassigned_trip_count"] = invalid_count

    assert rolling_chain._zero_hard_validation_counts(metrics) is False
