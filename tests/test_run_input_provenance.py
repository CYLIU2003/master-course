from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from bff.routers import optimization as optimization_router

from bff.services.optimization_run.input_provenance import (
    CODE_PROVENANCE_FILE,
    ENERGY_ASSET_CONTROL_INPUT_SCHEMA,
    MANIFEST_FILE,
    PARAMETERS_FILE,
    PREPARE_AUDIT_FILE,
    SCENARIO_SNAPSHOT_FILE,
    SUMMARY_FILE,
    VALIDATION_FILE,
    _optimization_parameters,
    _trip_structure_input,
    persist_run_input_provenance,
    validate_run_input_provenance,
)
from bff.routers.optimization import (
    _require_clean_research_git_state,
    _validate_git_state_after_solve,
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
        code_provenance={
            "schema_version": "git_provenance_v1",
            "captured_at_utc": "2026-07-24T00:00:00+00:00",
            "repository_root": str(tmp_path),
            "git_sha": "abc123",
            "git_dirty": False,
            "git_state_available": True,
            "git_state_error": None,
        },
    )

    assert result["status"] == "OK"
    assert result["research_ready"] is True
    for name in (
        SCENARIO_SNAPSHOT_FILE,
        PREPARE_AUDIT_FILE,
        PARAMETERS_FILE,
        SUMMARY_FILE,
        CODE_PROVENANCE_FILE,
        MANIFEST_FILE,
        VALIDATION_FILE,
    ):
        assert (run_dir / name).is_file()

    validation = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=True,
    )
    assert validation["valid"] is True
    assert validation["research_ready"] is True
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
    assert prepare_audit["prepared_trip_count"] == 1
    assert prepare_audit["prepared_trip_input_sha256"]
    assert "trips" in prepare_audit["omitted_large_payload_fields"]
    parameters = json.loads(
        (run_dir / PARAMETERS_FILE).read_text(encoding="utf-8")
    )
    assert parameters["frontend_request"]["mip_gap"] == 0.025
    assert parameters["effective_problem_scenario"]["timestep_min"] == 15
    assert parameters["runtime_environment"]["python_version"]
    assert parameters["runtime_environment"]["schema_version"] == (
        "runtime_environment_v3"
    )
    assert parameters["runtime_environment"]["cpu_logical_count"]
    assert "memory_total_bytes" in parameters["runtime_environment"]
    assert "memory_probe_source" in parameters["runtime_environment"]
    if os.name == "nt":
        assert parameters["runtime_environment"]["memory_total_bytes"] > 0
        assert parameters["runtime_environment"]["memory_probe_source"] in {
            "psutil",
            "windows_GlobalMemoryStatusEx",
        }
    assert "gurobipy_version" in parameters["runtime_environment"]
    assert parameters["canonical_input_dimensions"]["trip_input_sha256"]
    assert parameters["canonical_input_dimensions"][
        "trip_structure_input_sha256"
    ]
    assert parameters["canonical_input_dimensions"][
        "trip_structure_input_schema"
    ] == "canonical_trip_structure_v2_energy_demand_excluded"
    assert parameters["canonical_input_dimensions"]["vehicle_input_sha256"]
    assert parameters["canonical_input_dimensions"]["charger_input_sha256"]
    assert parameters["canonical_input_dimensions"]["price_input_sha256"]
    assert parameters["canonical_input_dimensions"]["price_value_set_sha256"]
    assert parameters["canonical_input_dimensions"][
        "energy_asset_control_input_sha256"
    ]
    assert parameters["canonical_input_dimensions"][
        "energy_asset_control_input_schema"
    ] == ENERGY_ASSET_CONTROL_INPUT_SCHEMA
    assert parameters["canonical_input_dimensions"]["objective_weights_sha256"]
    assert parameters["canonical_input_dimensions"]["pv_profile_sha256"]
    assert parameters["canonical_input_dimensions"][
        "canonical_ablation_input_sha256"
    ]
    code_provenance = json.loads(
        (run_dir / CODE_PROVENANCE_FILE).read_text(encoding="utf-8")
    )
    assert code_provenance["git_sha"] == "abc123"
    manifest = json.loads((run_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["git_state_available"] is True
    assert manifest["git_dirty"] is False

    manifest["git_sha"] = "posthoc-different-sha"
    (run_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    mismatched_git_provenance = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=True,
    )
    assert mismatched_git_provenance["valid"] is False
    assert "code_provenance_matches_manifest" in mismatched_git_provenance[
        "failed_checks"
    ]

    prepared_path.write_text('{"modified":true}', encoding="utf-8")
    changed_source = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=True,
    )
    assert changed_source["valid"] is False
    assert "prepared_source_sha256" in changed_source["failed_checks"]


def test_energy_asset_control_hash_excludes_only_weather_linked_pv_payloads() -> None:
    def parameters_for(asset: dict) -> dict:
        problem = _problem()
        problem.depot_energy_assets = {"depot-a": asset}
        return _optimization_parameters(
            scenario_id="scenario-test",
            prepared_input_id="prepared-test",
            frontend_request={},
            optimization_config=OptimizationConfig(),
            canonical_problem=problem,
            code_provenance={},
        )

    fixed_controls = {
        "pv_enabled": True,
        "pv_capacity_kw": 1000.0,
        "pv_slot_minutes": 60,
        "bess_enabled": True,
        "bess_power_kw": 250.0,
        "bess_energy_kwh": 500.0,
        "bess_charge_efficiency": 0.95,
    }
    sunny = parameters_for(
        {
            **fixed_controls,
            "capacity_factor_by_slot": [0.0, 0.8],
            "pv_generation_kwh_by_slot": [0.0, 800.0],
            "pv_capacity_factor_by_date": [
                {"date": "2025-08-05", "capacity_factor_by_slot": [0.0, 0.8]}
            ],
            "pv_generation_kwh_by_date": [
                {"date": "2025-08-05", "pv_generation_kwh_by_slot": [0.0, 800.0]}
            ],
            "pv_case_id": "sunny",
            "pv_profile_dates": ["2025-08-05"],
            "pv_profile_source": "tsurumaki_2025-08-05_60min",
            "pv_source_date": "2025-08-05",
        }
    )
    rain = parameters_for(
        {
            **fixed_controls,
            "capacity_factor_by_slot": [0.0, 0.1],
            "pv_generation_kwh_by_slot": [0.0, 100.0],
            "pv_capacity_factor_by_date": [
                {"date": "2025-08-10", "capacity_factor_by_slot": [0.0, 0.1]}
            ],
            "pv_generation_kwh_by_date": [
                {"date": "2025-08-10", "pv_generation_kwh_by_slot": [0.0, 100.0]}
            ],
            "pv_case_id": "rain",
            "pv_profile_dates": ["2025-08-10"],
            "pv_profile_source": "tsurumaki_2025-08-10_60min",
            "pv_source_date": "2025-08-10",
        }
    )
    changed_bess = parameters_for(
        {
            **fixed_controls,
            "bess_power_kw": 300.0,
            "capacity_factor_by_slot": [0.0, 0.8],
            "pv_generation_kwh_by_slot": [0.0, 800.0],
        }
    )

    sunny_dimensions = sunny["canonical_input_dimensions"]
    rain_dimensions = rain["canonical_input_dimensions"]
    changed_bess_dimensions = changed_bess["canonical_input_dimensions"]
    assert (
        sunny_dimensions["energy_asset_control_input_schema"]
        == ENERGY_ASSET_CONTROL_INPUT_SCHEMA
    )
    assert (
        sunny_dimensions["energy_asset_control_input_sha256"]
        == rain_dimensions["energy_asset_control_input_sha256"]
    )
    assert (
        sunny_dimensions["pv_profile_sha256"]
        != rain_dimensions["pv_profile_sha256"]
    )
    assert (
        sunny_dimensions["energy_asset_control_input_sha256"]
        != changed_bess_dimensions["energy_asset_control_input_sha256"]
    )


def test_trip_structure_hash_input_excludes_energy_derived_soc_requirement() -> None:
    common = {
        "trip_id": "trip-a",
        "route_id": "route-a",
        "departure_min": 60,
        "arrival_min": 90,
        "distance_km": 5.0,
        "allowed_vehicle_types": ["BEV", "ICE"],
    }
    low = {
        **common,
        "energy_kwh": 5.0,
        "fuel_l": 1.0,
        "required_soc_departure_percent": 12.0,
        "energy_model_provenance": {"sensitivity_scale": 0.8},
    }
    high = {
        **common,
        "energy_kwh": 7.5,
        "fuel_l": 1.5,
        "required_soc_departure_percent": 18.0,
        "energy_model_provenance": {"sensitivity_scale": 1.2},
    }

    assert _trip_structure_input([low]) == _trip_structure_input([high])


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


def test_frontend_run_input_bundle_rejects_missing_manifest_artifact(
    tmp_path: Path,
) -> None:
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
    (run_dir / PARAMETERS_FILE).unlink()

    validation = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=False,
    )

    assert validation["valid"] is False
    assert validation["research_ready"] is False
    assert f"{PARAMETERS_FILE}:exists" in validation["failed_checks"]


def test_formal_research_run_requires_clean_versioned_git_state() -> None:
    with pytest.raises(ValueError, match="clean Git worktree"):
        _require_clean_research_git_state(
            research_run=True,
            git_state={
                "git_state_available": True,
                "git_sha": "commit",
                "git_dirty": True,
                "worktree_patch_sha256": "patch-sha",
            },
        )
    with pytest.raises(ValueError, match="clean Git worktree"):
        _require_clean_research_git_state(
            research_run=True,
            git_state={
                "git_state_available": False,
                "git_dirty": None,
            },
        )
    with pytest.raises(ValueError, match="clean Git worktree"):
        _require_clean_research_git_state(
            research_run=True,
            git_state={
                "git_state_available": True,
                "git_dirty": False,
                "git_sha": "",
            },
        )
    _require_clean_research_git_state(
        research_run=True,
        git_state={
            "git_state_available": True,
            "git_sha": "commit",
            "git_dirty": False,
        },
    )
    _require_clean_research_git_state(
        research_run=False,
        git_state={
            "git_state_available": True,
            "git_sha": "commit",
            "git_dirty": True,
        },
    )


def test_research_run_rejects_source_change_during_solve() -> None:
    before = {
        "git_state_available": True,
        "git_sha": "commit-a",
        "git_dirty": False,
        "worktree_patch_sha256": None,
    }
    with mock.patch.object(
        optimization_router,
        "_BFF_RUNTIME_GIT_STATE",
        before,
    ):
        assert (
            _validate_git_state_after_solve(
                research_run=True,
                before=before,
                after=dict(before),
            )
            is True
        )
        with pytest.raises(ValueError, match="source state changed during solve"):
            _validate_git_state_after_solve(
                research_run=True,
                before=before,
                after={**before, "git_sha": "commit-b"},
            )


def test_dirty_input_bundle_is_integrity_valid_but_not_research_ready(
    tmp_path: Path,
) -> None:
    prepared = _prepared_input()
    prepared_path = tmp_path / "prepared-test.json"
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
    result = persist_run_input_provenance(
        run_dir=tmp_path / "run",
        base_scenario={"scenario_id": "scenario-test"},
        effective_scenario={"scenario_id": "scenario-test"},
        prepared_input=prepared,
        prepared_input_path=prepared_path,
        requested_prepared_input_id="prepared-test",
        frontend_request={"mode": "mode_milp_only"},
        optimization_config=OptimizationConfig(),
        canonical_problem=_problem(),
        code_provenance={
            "schema_version": "git_provenance_v1",
            "captured_at_utc": "2026-07-26T00:00:00+00:00",
            "repository_root": str(tmp_path),
            "git_sha": "dirty-sha",
            "git_dirty": True,
            "worktree_patch_sha256": "patch-sha",
            "git_state_available": True,
            "git_state_error": None,
        },
    )

    assert result["status"] == "OK"
    assert result["research_ready"] is False
    validation = json.loads(
        (tmp_path / "run" / VALIDATION_FILE).read_text(encoding="utf-8")
    )
    assert validation["valid"] is True
    assert validation["research_ready"] is False
    assert validation["research_readiness_reasons"] == ["git_worktree_dirty"]
