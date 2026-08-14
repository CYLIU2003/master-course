from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from bff.services.optimization_run import thesis_phase_gate_audit as audit_module


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _payload_sha(payload: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def ready_input_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audit_module,
        "validate_run_input_provenance",
        lambda *_args, **_kwargs: {
            "valid": True,
            "research_ready": True,
            "failed_checks": [],
        },
    )


def _run_fixture(root: Path, *, git_sha: str = "a" * 40) -> Path:
    run_dir = root / "run"
    _write_json(
        run_dir / "assignment_economic_audit.json",
        {
            "trip_energy_model": "literature_proxy_v1",
            "objective_preset": "research_lexicographic_v1",
            "charging_power_model": "piecewise_soc_taper_v1",
            "vehicle_usage_cost_semantics_classified": True,
            "vehicle_usage_cost_semantics_research_eligible": True,
            "co2_emissions_cap_kg": None,
        },
    )
    _write_json(
        run_dir / "code_provenance.json",
        {
            "git_sha": git_sha,
            "git_state_available": True,
            "git_dirty": False,
        },
    )
    _write_json(
        run_dir / "final_cost_reconciliation.json",
        {"status": "OK", "failed_artifacts": []},
    )
    _write_json(
        run_dir / "optimization_parameters.json",
        {
            "effective_model_metadata": {
                "charge_setup_minutes": 5,
                "charge_teardown_minutes": 5,
                "minimum_charge_session_minutes": 15,
            }
        },
    )
    prepared_scope_audit = {
        "formal_transition_network_ready": True,
        "route_band_off_transition_audit_checked": True,
        "route_band_off_deadhead_missing_count": 0,
        "route_band_off_transition_audit": {
            "checked": True,
            "blocked_transition_reason_counts": {
                "insufficient_transition_time": 2
            },
        },
        "formal_turnaround_sensitivity_ready": True,
        "turnaround_buffer_sensitivity_audit": {
            "status": "VALID",
            "levels_minutes": [5, 10, 15],
            "transition_graph_evaluated_all_levels": True,
        },
        "formal_vehicle_trip_compatibility_ready": True,
        "vehicle_trip_compatibility_audit": {
            "implicit_fallback_trip_count": 0,
            "solver_powertrain_projection_exact": True,
            "compatibility_matrix_sha256": "b" * 64,
        },
    }
    _write_json(
        run_dir / "optimization_result.json",
        {
            "prepared_scope_audit": prepared_scope_audit,
            "solver_metadata": {
                "fallback_applied": False,
                "postsolve_soc_repair_applied": False,
                "postsolve_modified_solution": False,
                "objective_semantics": (
                    "lexicographic_vehicle_days_then_canonical_cost_then_"
                    "deadhead_and_charge_sessions"
                ),
            },
        },
    )
    _write_json(
        run_dir / "physical_schedule_validation.json",
        {
            "schema_version": "physical_schedule_validation_v2",
            "status": "VALID",
            "accepted": True,
            "failed_checks": [],
            "checks": {"independent_event_schedule_accepted": True},
            "validation_metrics": {"infeasible_transition_count": 0},
        },
    )
    _write_json(
        run_dir / "prepare_input_audit.json",
        {"prepared_input_id": "prepared-1", "prepared_trip_count": 4},
    )
    _write_json(
        run_dir / "run_manifest.json",
        {
            "git_sha": git_sha,
            "research_run": True,
            "research_run_accepted": True,
            "requested_phase": "phase4_integrated",
            "resolved_phase": "phase4_integrated",
            "executed_phase": "phase4_integrated",
        },
    )
    _write_json(
        run_dir / "solver_settings.json",
        {
            "git_sha": git_sha,
            "git_state_unchanged_during_solve": True,
            "research_run": True,
            "research_run_accepted": True,
            "successor_pruning_enabled": False,
            "fallback_applied": False,
            "mip_gap_target_met": True,
            "integrated_primary_objective_kind": (
                "minimum_used_vehicle_days_lexicographic"
            ),
            "actual_cost_objective_structural_contract_passed": True,
            "requested_phase": "phase4_integrated",
            "resolved_phase": "phase4_integrated",
            "executed_phase": "phase4_integrated",
        },
    )
    _write_json(
        run_dir / "summary.json",
        {
            "trip_count_served": 4,
            "trip_count_unserved": 0,
            "mip_gap_target_met": True,
        },
    )
    _write_json(
        run_dir / "rolling_hourly_chain/executed_day_accounting.json",
        {"eligible": True},
    )
    _write_json(
        run_dir / "rolling_hourly_chain/rolling_chain_summary.json",
        {
            "chain_accepted": True,
            "all_steps_feasible": True,
            "step_count": 24,
            "expected_step_count": 24,
        },
    )
    summary_path = run_dir / "summary.json"
    _write_json(
        run_dir / "artifact_completeness.json",
        {
            "status": "OK",
            "accepted": True,
            "research_run": True,
            "artifacts": {
                "summary.json": {
                    "size_bytes": summary_path.stat().st_size,
                    "sha256": _file_sha(summary_path),
                }
            },
        },
    )
    return run_dir


def _sensitivity_manifest(
    path: Path,
    *,
    family: str,
    case_ids: tuple[str, ...],
    git_sha: str = "a" * 40,
) -> Path:
    payload: dict[str, Any] = {
        "schema_version": "thesis_sensitivity_execution_v2",
        "frozen_git_sha": git_sha,
        "audit_builder_git_sha": git_sha,
        "selected_case_ids": list(case_ids),
        "completed_case_ids": list(case_ids),
        "all_selected_cases_completed": True,
        "all_selected_cases_accepted": True,
        "stable_nonvaried_controls_match": True,
        "status": "COMPLETED_SUBSET",
        "outcomes": [
            {
                "case_id": case_id,
                "family": family,
                "case_accepted": True,
                "checks": {"source_run_accepted": True},
                "failed_checks": [],
            }
            for case_id in case_ids
        ],
    }
    payload["payload_sha256"] = _payload_sha(payload)
    _write_json(path, payload)
    return path


def test_phase0_completes_but_phase1_requires_optimized_evidence(
    tmp_path: Path,
    ready_input_provenance: None,
) -> None:
    run_dir = _run_fixture(tmp_path)

    result = audit_module.build_thesis_phase_gate_audit(
        run_dir=run_dir,
        expected_trip_count=4,
    )

    assert result["highest_complete_phase"] == "phase0"
    assert result["next_blocked_phase"] == "phase1"
    assert result["phases"]["phase0"]["status"] == "COMPLETE"
    assert result["phases"]["phase1"]["status"] == "BLOCKED"
    assert result["phases"]["phase1"]["checks"][
        "route_band_on_off_optimized_comparison_accepted"
    ] is False
    assert result["status"] == "BLOCKED"


def test_phase1_completes_with_same_sha_accepted_family_manifests(
    tmp_path: Path,
    ready_input_provenance: None,
) -> None:
    run_dir = _run_fixture(tmp_path)
    route_band = _sensitivity_manifest(
        tmp_path / "route-band.json",
        family="route_band_ablation",
        case_ids=("ROUTE_BAND_ON", "ROUTE_BAND_OFF"),
    )
    turnaround = _sensitivity_manifest(
        tmp_path / "turnaround.json",
        family="turnaround_buffer_sensitivity",
        case_ids=(
            "TURNAROUND_BUFFER_5",
            "TURNAROUND_BUFFER_10",
            "TURNAROUND_BUFFER_15",
        ),
    )

    result = audit_module.build_thesis_phase_gate_audit(
        run_dir=run_dir,
        sensitivity_manifest_paths=(route_band, turnaround),
        expected_trip_count=4,
    )

    assert result["highest_complete_phase"] == "phase1"
    assert result["phases"]["phase1"]["status"] == "COMPLETE"
    assert result["phases"]["phase2"]["status"] == "BLOCKED"


@pytest.mark.parametrize("failure", ["hash", "git_sha"])
def test_sensitivity_manifest_fails_closed_on_tamper_or_wrong_sha(
    tmp_path: Path,
    ready_input_provenance: None,
    failure: str,
) -> None:
    run_dir = _run_fixture(tmp_path)
    manifest = _sensitivity_manifest(
        tmp_path / "route-band.json",
        family="route_band_ablation",
        case_ids=("ROUTE_BAND_ON", "ROUTE_BAND_OFF"),
        git_sha=("c" * 40 if failure == "git_sha" else "a" * 40),
    )
    if failure == "hash":
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["status"] = "READY_FOR_SENSITIVITY_ANALYSIS"
        _write_json(manifest, payload)

    result = audit_module.build_thesis_phase_gate_audit(
        run_dir=run_dir,
        sensitivity_manifest_paths=(manifest,),
    )

    assert result["sensitivity_evidence"]["families"][
        "route_band_ablation"
    ]["passed"] is False
    assert result["phases"]["phase1"]["status"] == "BLOCKED"


def test_post_snapshot_mutation_blocks_phase0_and_all_later_phases(
    tmp_path: Path,
    ready_input_provenance: None,
) -> None:
    run_dir = _run_fixture(tmp_path)
    summary_path = run_dir / "summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["extra"] = "post-hoc mutation"
    _write_json(summary_path, payload)

    result = audit_module.build_thesis_phase_gate_audit(run_dir=run_dir)

    assert result["phases"]["phase0"]["status"] == "BLOCKED"
    assert result["phases"]["phase0"]["checks"][
        "finalized_artifact_hashes_match"
    ] is False
    assert result["phases"]["phase1"]["status"] == "BLOCKED"
    assert result["highest_complete_phase"] is None


def test_sensitivity_manifest_rejects_inconsistent_case_identity(
    tmp_path: Path,
    ready_input_provenance: None,
) -> None:
    run_dir = _run_fixture(tmp_path)
    manifest = _sensitivity_manifest(
        tmp_path / "route-band.json",
        family="route_band_ablation",
        case_ids=("ROUTE_BAND_ON", "ROUTE_BAND_OFF"),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["completed_case_ids"] = ["ROUTE_BAND_ON"]
    payload.pop("payload_sha256")
    payload["payload_sha256"] = _payload_sha(payload)
    _write_json(manifest, payload)

    result = audit_module.build_thesis_phase_gate_audit(
        run_dir=run_dir,
        sensitivity_manifest_paths=(manifest,),
    )

    manifest_row = result["sensitivity_evidence"]["manifests"][0]
    assert manifest_row["payload_hash_valid"] is True
    assert manifest_row["case_identity_consistent"] is False
    assert manifest_row["valid"] is False


def test_expected_trip_count_is_an_independent_fail_closed_check(
    tmp_path: Path,
    ready_input_provenance: None,
) -> None:
    run_dir = _run_fixture(tmp_path)

    result = audit_module.build_thesis_phase_gate_audit(
        run_dir=run_dir,
        expected_trip_count=264,
    )

    assert result["phases"]["phase0"]["checks"][
        "independent_expected_trip_count_matches"
    ] is False
    assert result["phases"]["phase0"]["status"] == "BLOCKED"


def test_run_manifest_git_sha_mismatch_blocks_phase0(
    tmp_path: Path,
    ready_input_provenance: None,
) -> None:
    run_dir = _run_fixture(tmp_path)
    manifest_path = run_dir / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["git_sha"] = "d" * 40
    _write_json(manifest_path, payload)

    result = audit_module.build_thesis_phase_gate_audit(run_dir=run_dir)

    assert result["phases"]["phase0"]["checks"][
        "same_git_sha_across_run_artifacts"
    ] is False
    assert result["phases"]["phase0"]["status"] == "BLOCKED"


def test_prepared_trip_count_supports_compact_prepare_snapshot(
    tmp_path: Path,
    ready_input_provenance: None,
) -> None:
    run_dir = _run_fixture(tmp_path)
    prepare_path = run_dir / "prepare_input_audit.json"
    payload = json.loads(prepare_path.read_text(encoding="utf-8"))
    payload.pop("prepared_trip_count")
    payload["prepare_snapshot"] = {"trip_count": 4}
    _write_json(prepare_path, payload)

    result = audit_module.build_thesis_phase_gate_audit(
        run_dir=run_dir,
        expected_trip_count=4,
    )

    assert result["reference_prepared_trip_count"] == 4
    assert result["phases"]["phase0"]["checks"][
        "all_prepared_trips_served_once"
    ] is True
