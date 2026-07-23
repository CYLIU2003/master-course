from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from bff.services.optimization_run.input_provenance import (
    MANIFEST_FILE,
    PARAMETERS_FILE,
    PREPARE_AUDIT_FILE,
    SCENARIO_SNAPSHOT_FILE,
    SUMMARY_FILE,
    VALIDATION_FILE,
    persist_run_input_provenance,
    validate_run_input_provenance,
)
from src.optimization.common.problem import OptimizationConfig, OptimizationScenario


def _prepared_input() -> dict:
    return {
        "prepared_input_id": "prepared-test",
        "prepared_input_schema_version": "v2",
        "scenario_id": "scenario-test",
        "dataset_id": "dataset-test",
        "dataset_version": "2026-07-23",
        "random_seed": 42,
        "scenario_hash": "scenario-hash",
        "scope_hash": "scope-hash",
        "prepared_at": "2026-07-23T00:00:00+00:00",
        "solver_mode_requested": "mode_milp_only",
        "solver_mode_effective": "mode_milp_only",
        "prepare_profile": {"profile": "milp_exact"},
        "depot_ids": ["depot-a"],
        "route_ids": ["route-a"],
        "service_ids": ["WEEKDAY"],
        "service_date": "2025-08-05",
        "service_dates": ["2025-08-05"],
        "planning_days": 1,
        "primary_depot_id": "depot-a",
        "trip_count": 1,
        "timetable_row_count": 1,
        "scope": {"allow_partial_service": False},
        "counts": {"trips": 1, "vehicles": 1},
        "dispatch_scope": {"serviceId": "WEEKDAY", "depotId": "depot-a"},
        "prepared_scope_audit": {
            "trip_distance_audit": {"zero_or_missing_count": 0}
        },
        "vehicles": [{"vehicle_id": "bev-1", "vehicle_type": "BEV"}],
        "chargers": [{"charger_id": "charger-1", "power_kw": 90.0}],
        "depots": [{"depot_id": "depot-a"}],
        "routes": [{"route_id": "route-a", "route_code": "A"}],
        "trips": [{"trip_id": "trip-a", "distance_km": 5.0}],
        "stop_time_sequences": [{"trip_id": "trip-a", "rows": [1, 2, 3]}],
    }


def _problem() -> SimpleNamespace:
    return SimpleNamespace(
        scenario=OptimizationScenario(
            scenario_id="scenario-test",
            timestep_min=15,
            horizon_duration_min=1440,
            service_coverage_mode="strict",
        ),
        metadata={
            "service_date": "2025-08-05",
            "cost_component_flags": {"electricity_cost": True},
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
            "grid_co2_kg_per_kwh": {0: 0.5},
        },
        trips=(SimpleNamespace(trip_id="trip-a"),),
        vehicles=(SimpleNamespace(vehicle_id="bev-1"),),
        chargers=(SimpleNamespace(charger_id="charger-1"),),
        price_slots=(SimpleNamespace(slot_index=0),),
        pv_slots=(SimpleNamespace(slot_index=0),),
    )


def test_frontend_run_input_bundle_is_self_verifying(tmp_path: Path) -> None:
    prepared = _prepared_input()
    prepared_path = tmp_path / "prepared-test.json"
    prepared_path.write_text(
        json.dumps(prepared, ensure_ascii=False),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"

    result = persist_run_input_provenance(
        run_dir=run_dir,
        base_scenario={
            "scenario_id": "scenario-test",
            "name": "test scenario",
            "simulation_config": {"time_step_min": 60},
            "timetable_rows": [{"trip_id": "must-not-be-duplicated"}],
        },
        effective_scenario={
            "scenario_id": "scenario-test",
            "simulation_config": {"time_step_min": 15},
            "scenario_overlay": {"fleet": {"n_bev": 1}},
            "dispatch_scope": {"serviceId": "WEEKDAY"},
            "prepare_profile": {"profile": "milp_exact"},
            "scope_hash": "scope-hash",
        },
        prepared_input=prepared,
        prepared_input_path=prepared_path,
        requested_prepared_input_id="prepared-test",
        frontend_request={
            "mode": "mode_milp_only",
            "time_limit_seconds": 300,
            "mip_gap": 0.025,
            "random_seed": 42,
            "timestep_min": 15,
        },
        optimization_config=OptimizationConfig(
            time_limit_sec=300,
            mip_gap=0.025,
            random_seed=42,
            phase="phase3_two_stage",
            executed_phase="phase3_two_stage",
        ),
        canonical_problem=_problem(),
    )

    assert result["status"] == "OK"
    for name in (
        SCENARIO_SNAPSHOT_FILE,
        PREPARE_AUDIT_FILE,
        PARAMETERS_FILE,
        SUMMARY_FILE,
        MANIFEST_FILE,
        VALIDATION_FILE,
    ):
        assert (run_dir / name).is_file()

    validation = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=True,
    )
    assert validation["valid"] is True
    scenario_snapshot = json.loads(
        (run_dir / SCENARIO_SNAPSHOT_FILE).read_text(encoding="utf-8")
    )
    assert "timetable_rows" not in scenario_snapshot["persisted_scenario"]
    assert {
        item["field"] for item in scenario_snapshot["persisted_scenario_omissions"]
    } == {"timetable_rows"}
    prepare_audit = json.loads(
        (run_dir / PREPARE_AUDIT_FILE).read_text(encoding="utf-8")
    )
    assert prepare_audit["source_artifact"]["sha256"]
    assert "trips" in prepare_audit["omitted_large_payload_fields"]
    parameters = json.loads(
        (run_dir / PARAMETERS_FILE).read_text(encoding="utf-8")
    )
    assert parameters["frontend_request"]["mip_gap"] == 0.025
    assert parameters["effective_problem_scenario"]["timestep_min"] == 15

    prepared_path.write_text('{"modified":true}', encoding="utf-8")
    changed_source = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=True,
    )
    assert changed_source["valid"] is False
    assert "prepared_source_sha256" in changed_source["failed_checks"]


def test_frontend_run_input_bundle_rejects_posthoc_tampering(tmp_path: Path) -> None:
    prepared = _prepared_input()
    prepared_path = tmp_path / "prepared-test.json"
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
    run_dir = tmp_path / "run"
    persist_run_input_provenance(
        run_dir=run_dir,
        base_scenario={"scenario_id": "scenario-test"},
        effective_scenario={"scenario_id": "scenario-test"},
        prepared_input=prepared,
        prepared_input_path=prepared_path,
        requested_prepared_input_id="prepared-test",
        frontend_request={"mode": "mode_milp_only"},
        optimization_config=OptimizationConfig(),
        canonical_problem=_problem(),
    )
    (run_dir / SCENARIO_SNAPSHOT_FILE).write_text(
        '{"scenario_id":"tampered"}',
        encoding="utf-8",
    )

    validation = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=False,
    )

    assert validation["valid"] is False
    assert f"{SCENARIO_SNAPSHOT_FILE}:sha256" in validation["failed_checks"]
