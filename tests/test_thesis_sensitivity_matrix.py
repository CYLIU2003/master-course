from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

from bff.routers.simulation import PrepareSimulationSettingsBody
from scripts import run_thesis_sensitivity_matrix as sensitivity_runner
from scripts.build_thesis_experiment_matrix import build_experiment_matrix
from scripts.run_thesis_sensitivity_matrix import (
    _artifact_snapshot_matches,
    _case_parameter_matches,
    _declared_controls_match,
    _submitted_request_matches_provenance,
    _stable_control_fingerprint,
    _verified_prepared_trip_input_hash,
    _successor_limits_match,
    _snapshotted_artifact_paths,
    _write_manifest,
    build_case_requests,
)


def _case(case_id: str) -> dict:
    matrix = build_experiment_matrix()
    return next(row for row in matrix["cases"] if row["case_id"] == case_id)


def test_pv_scale_is_a_validated_prepare_api_parameter() -> None:
    settings = PrepareSimulationSettingsBody(pv_scale=0.25)

    assert settings.pv_scale == 0.25


def test_case_request_compiler_uses_fresh_prepare_and_declared_overrides() -> None:
    prepare, optimization = build_case_requests(
        case=_case("ROUTE_BAND_OFF"),
        base_prepare_request={
            "selected_depot_ids": ["dep-1"],
            "selected_route_ids": ["route-1"],
            "allow_intra_depot_route_swap": False,
            "simulation_settings": {"custom_control": "preserved"},
        },
        base_optimization_request={
            "prepared_input_id": "stale-id",
            "run_hourly_rolling": True,
            "custom_control": "preserved",
        },
    )

    assert prepare["allow_intra_depot_route_swap"] is True
    assert prepare["simulation_settings"]["fixed_route_band_mode"] is False
    assert prepare["simulation_settings"]["custom_control"] == "preserved"
    assert "prepared_input_id" not in optimization
    assert optimization["mode"] == "phase4_integrated"
    assert optimization["research_run"] is True
    assert optimization["custom_control"] == "preserved"


def test_time_case_compiles_matching_prepare_optimization_and_rolling_steps() -> None:
    prepare, optimization = build_case_requests(
        case=_case("TIME_15"),
        base_prepare_request={"simulation_settings": {}},
        base_optimization_request={},
    )

    assert prepare["simulation_settings"]["time_step_min"] == 15
    assert prepare["simulation_settings"]["timestep_min"] == 15
    assert optimization["time_step_min"] == 15
    assert optimization["timestep_min"] == 15
    assert optimization["rolling_execution_minutes"] == 60


def test_parameter_audit_distinguishes_pv_scale_and_route_band_lock() -> None:
    assert _case_parameter_matches(
        case=_case("PV_0.25"),
        parameters={
            "effective_model_metadata": {
                "pv_supply_scale_by_depot": {"dep-1": 0.25}
            }
        },
        economic_audit={},
    )
    assert not _case_parameter_matches(
        case=_case("PV_0.25"),
        parameters={
            "effective_model_metadata": {
                "pv_supply_scale_by_depot": {"dep-1": 1.0}
            }
        },
        economic_audit={},
    )
    assert _case_parameter_matches(
        case=_case("ROUTE_BAND_OFF"),
        parameters={
            "effective_model_metadata": {
                "fixed_route_band_mode": False,
                "allow_intra_depot_route_swap": True,
            }
        },
        economic_audit={},
    )


def test_declared_control_audit_rejects_hidden_prepare_override() -> None:
    case = _case("PV_0.25")
    expected = case["prepare_settings"]
    parameters = {
        "frontend_request": {
            "effective_rolling_controls": {
                "run_hourly_rolling": True,
                "rolling_execution_minutes": 60,
            }
        },
        "effective_problem_scenario": {
            "objective_mode": expected["objective_mode"]
        },
        "effective_model_metadata": {
            "objective_preset": expected["objective_preset"],
            "trip_energy_model": expected["trip_energy_model"],
            "charging_power_model": expected["charging_power_model"],
            "charge_setup_minutes": expected["charge_setup_minutes"],
            "charge_teardown_minutes": expected["charge_teardown_minutes"],
            "minimum_charge_session_minutes": expected[
                "minimum_charge_session_minutes"
            ],
            "allow_partial_service": expected["allow_partial_service"],
            "milp_max_successors_per_trip": expected[
                "milp_max_successors_per_trip"
            ],
            "vehicle_usage_cost_semantics": expected[
                "vehicle_usage_cost_semantics"
            ],
        },
    }
    economic_audit = {
        "pv_input_semantics_by_depot": {
            "dep-1": expected["pv_input_semantics"]
        }
    }

    assert _declared_controls_match(
        case=case,
        parameters=parameters,
        economic_audit=economic_audit,
    )

    parameters["effective_model_metadata"]["charging_power_model"] = (
        "constant_power_v0"
    )
    assert not _declared_controls_match(
        case=case,
        parameters=parameters,
        economic_audit=economic_audit,
    )


def test_successor_control_normalizes_only_unlimited_sentinels() -> None:
    assert _successor_limits_match(0, None)
    assert _successor_limits_match(None, 0)
    assert _successor_limits_match(32, 32)
    assert not _successor_limits_match(0, 32)
    assert not _successor_limits_match(32, None)


def test_energy_stable_fingerprint_excludes_intentional_demand_hash() -> None:
    case = _case("ENERGY_1.0")
    common = {
        "scenario_id": "scenario-a",
        "canonical_input_dimensions": {
            "trip_ids_sha256": "trips",
            "vehicle_ids_sha256": "vehicles",
            "vehicle_input_sha256": "vehicle-input",
            "charger_input_sha256": "chargers",
            "vehicle_type_input_sha256": "vehicle-types",
            "depot_input_sha256": "depots",
            "price_value_set_sha256": "prices",
            "energy_asset_control_input_sha256": "assets",
            "objective_weights_sha256": "objective",
        },
        "effective_model_metadata": {
            "service_date": "2025-08-05",
            "scenario_fleet_contract_hash": "fleet",
        },
        "effective_problem_scenario": {},
    }
    low = json.loads(json.dumps(common))
    high = json.loads(json.dumps(common))
    low["canonical_input_dimensions"]["trip_structure_input_sha256"] = "low"
    high["canonical_input_dimensions"]["trip_structure_input_sha256"] = "high"

    low_hash = _stable_control_fingerprint(
        case=case,
        parameters=low,
        economic_audit={},
        prepared_trip_input_sha256="prepared-trips",
    )
    high_hash = _stable_control_fingerprint(
        case=case,
        parameters=high,
        economic_audit={},
        prepared_trip_input_sha256="prepared-trips",
    )

    assert low_hash == high_hash
    high["canonical_input_dimensions"]["vehicle_input_sha256"] = "drift"
    assert low_hash != _stable_control_fingerprint(
        case=case,
        parameters=high,
        economic_audit={},
        prepared_trip_input_sha256="prepared-trips",
    )


def test_legacy_prepared_trip_hash_requires_verified_source(tmp_path: Path) -> None:
    source = tmp_path / "prepared-test.json"
    source.write_text(
        json.dumps({"trips": [{"trip_id": "trip-a"}]}),
        encoding="utf-8",
    )
    prepare_audit = {"prepare_snapshot": {"trip_count": 1}}
    validation = {
        "valid": True,
        "checks": {
            "prepared_source_exists": True,
            "prepared_source_size": True,
            "prepared_source_sha256": True,
        },
        "details": {"prepared_source_path_checked": str(source)},
    }

    value, provenance = _verified_prepared_trip_input_hash(
        prepare_audit=prepare_audit,
        input_validation=validation,
    )

    assert value
    assert provenance == "verified_prepared_source_legacy_fallback"
    validation["checks"]["prepared_source_sha256"] = False
    assert _verified_prepared_trip_input_hash(
        prepare_audit=prepare_audit,
        input_validation=validation,
    ) == (None, None)


def test_persisted_prepared_trip_hash_requires_schema_and_count_match() -> None:
    prepare_audit = {
        "prepared_trip_input_schema": "prepared_trip_rows_v1",
        "prepared_trip_count": 1,
        "prepared_trip_input_sha256": "a" * 64,
        "prepare_snapshot": {"trip_count": 1},
    }

    assert _verified_prepared_trip_input_hash(
        prepare_audit=prepare_audit,
        input_validation={},
    ) == ("a" * 64, "prepare_input_audit")
    prepare_audit["prepared_trip_count"] = 2
    assert _verified_prepared_trip_input_hash(
        prepare_audit=prepare_audit,
        input_validation={},
    ) == (None, None)


def test_submitted_request_provenance_detects_server_overwrite() -> None:
    submitted = {
        "mode": "phase4_integrated",
        "rolling_execution_minutes": 30,
        "mip_gap": 0.01,
    }
    parameters = {
        "frontend_request": {
            "raw_frontend_body": {
                "mode": "phase4_integrated",
                "rolling_execution_minutes": 30,
                "mip_gap": 0.01,
                "server_default": "allowed-extra-field",
            }
        }
    }

    assert _submitted_request_matches_provenance(
        submitted_request=submitted,
        parameters=parameters,
    )
    parameters["frontend_request"]["raw_frontend_body"][
        "rolling_execution_minutes"
    ] = 60
    assert not _submitted_request_matches_provenance(
        submitted_request=submitted,
        parameters=parameters,
    )


def test_manifest_never_labels_a_partial_matrix_complete(tmp_path: Path) -> None:
    matrix = {
        "schema_version": "test",
        "cases": [
            {"case_id": "A", "family": "one"},
            {"case_id": "B", "family": "two"},
        ],
    }
    outcome = {
        "case_id": "A",
        "family": "one",
        "case_accepted": True,
        "stable_control_fingerprint": "stable",
    }

    payload = _write_manifest(
        output_dir=tmp_path,
        matrix=matrix,
        frozen_sha="sha",
        selected_ids={"A"},
        outcomes=[outcome],
    )

    assert payload["status"] == "COMPLETED_SUBSET"
    assert payload["research_matrix_complete"] is False
    assert payload["stable_nonvaried_controls_match"] is True
    with (tmp_path / "sensitivity_results.csv").open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["case_id"] == "A"


def test_artifact_snapshot_detects_posthoc_source_edit(tmp_path: Path) -> None:
    source = tmp_path / "summary.json"
    source.write_text('{"status":"accepted"}', encoding="utf-8")
    record = {
        "summary.json": {
            "size_bytes": source.stat().st_size,
            "sha256": sha256(source.read_bytes()).hexdigest(),
        }
    }

    assert _artifact_snapshot_matches(
        run_dir=tmp_path,
        completeness={"artifacts": record},
        relative_paths=("summary.json",),
    )
    source.write_text('{"status":"edited"}', encoding="utf-8")
    assert not _artifact_snapshot_matches(
        run_dir=tmp_path,
        completeness={"artifacts": record},
        relative_paths=("summary.json",),
    )


def test_artifact_snapshot_excludes_its_own_container() -> None:
    assert _snapshotted_artifact_paths(
        (
            "summary.json",
            "artifact_completeness.json",
            "solver_settings.json",
        )
    ) == ("summary.json", "solver_settings.json")


def test_manifest_blocks_cross_case_control_drift(tmp_path: Path) -> None:
    matrix = {
        "schema_version": "test",
        "cases": [
            {"case_id": "A", "family": "one"},
            {"case_id": "B", "family": "two"},
        ],
    }
    outcomes = [
        {
            "case_id": "A",
            "case_accepted": True,
            "stable_control_fingerprint": "control-a",
        },
        {
            "case_id": "B",
            "case_accepted": True,
            "stable_control_fingerprint": "control-b",
        },
    ]

    payload = _write_manifest(
        output_dir=tmp_path,
        matrix=matrix,
        frozen_sha="sha",
        selected_ids={"A", "B"},
        outcomes=outcomes,
    )

    assert payload["status"] == "BLOCKED"
    assert payload["stable_nonvaried_controls_match"] is False
    assert payload["research_matrix_complete"] is False


def test_reaudit_preserves_source_sha_and_records_builder_sha(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "reaudit"
    case_dir = source / "cases" / "A"
    run_dir = case_dir / "source_run"
    run_dir.mkdir(parents=True)
    matrix = {
        "schema_version": "test-matrix",
        "cases": [{"case_id": "A", "family": "time_discretization"}],
    }
    source_manifest = {
        "schema_version": "old",
        "frozen_git_sha": "source-sha",
        "selected_case_ids": ["A"],
        "outcomes": [
            {
                "case_id": "A",
                "job_id": "job-a",
                "prepared_input_id": "prepared-a",
                "wall_time_seconds": 12.5,
            }
        ],
    }
    source_manifest["payload_sha256"] = sensitivity_runner._canonical_hash(
        source_manifest
    )
    for path, payload in (
        (source / "experiment_matrix.json", matrix),
        (source / "sensitivity_execution_manifest.json", source_manifest),
        (case_dir / "frontend_job_terminal_response.json", {"status": "completed"}),
        (case_dir / "frontend_optimization_request.json", {"mode": "phase4_integrated"}),
        (
            run_dir / "solver_settings.json",
            {
                "git_sha": "source-sha",
                "git_sha_after_solve": "source-sha",
                "git_dirty": False,
                "git_dirty_after_solve": False,
                "git_state_unchanged_during_solve": True,
            },
        ),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        sensitivity_runner,
        "_assert_clean_frozen_repository",
        lambda: "builder-sha",
    )
    monkeypatch.setattr(
        sensitivity_runner,
        "_audit_case",
        lambda **_kwargs: {
            "case_id": "A",
            "family": "time_discretization",
            "case_accepted": True,
            "checks": {"base_audit": True},
            "failed_checks": [],
            "stable_control_fingerprint": "stable",
        },
    )

    payload = sensitivity_runner.rebuild_existing_sensitivity_audit(
        source_execution_dir=source,
        output_dir=destination,
    )

    assert payload["frozen_git_sha"] == "source-sha"
    assert payload["audit_builder_git_sha"] == "builder-sha"
    assert payload["source_execution_dir"] == str(source.resolve())
    assert payload["outcomes"][0]["job_id"] == "job-a"
    assert payload["outcomes"][0]["checks"][
        "source_run_matches_original_frozen_git_sha"
    ] is True
