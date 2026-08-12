from __future__ import annotations

import csv
from hashlib import sha256
from pathlib import Path

from bff.routers.simulation import PrepareSimulationSettingsBody
from scripts.build_thesis_experiment_matrix import build_experiment_matrix
from scripts.run_thesis_sensitivity_matrix import (
    _artifact_snapshot_matches,
    _case_parameter_matches,
    _declared_controls_match,
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
    assert optimization["rolling_execution_minutes"] == 15


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
