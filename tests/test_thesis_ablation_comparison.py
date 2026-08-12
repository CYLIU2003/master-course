from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from bff.services.optimization_run.thesis_ablation_comparison import (
    build_complete_day_ahead_ablation_comparison,
    comparison_csv_rows,
)


def _payload_sha(payload: dict) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _method(method_id: str, *, source: str) -> dict:
    return {
        "method_id": method_id,
        "label": method_id,
        "construction_status": source,
        "candidate_available": True,
        "physical_feasible": True,
        "day_ahead_comparison_eligible": True,
        "used_bev_count": 1,
        "used_ice_count": 0,
        "bev_trip_count": 1,
        "ice_trip_count": 0,
        "cost_breakdown": {
            "electricity_cost_final": 100.0,
            "fuel_cost_final": 0.0,
            "vehicle_usage_cost": 0.0,
            "total_cost": 100.0,
            "total_co2_kg": 5.0,
            "grid_import_kwh": 5.0,
            "pv_to_bus_kwh": 0.0,
            "pv_to_bess_kwh": 0.0,
            "bess_to_bus_kwh": 0.0,
        },
    }


def _candidate_payload(*, structure: str) -> dict:
    if structure == "charging_only":
        methods = [
            _method("M0", source="RULE_ADAPTER_COMPLETED"),
            _method("M1", source="PRIMARY_PHASE1_DAY_AHEAD_RESULT"),
            {
                "method_id": "M2",
                "candidate_available": False,
                "construction_status": "OPTIMIZED_DISPATCH_RUN_REQUIRED",
            },
            {
                "method_id": "M3",
                "candidate_available": False,
                "construction_status": (
                    "SEPARATE_PHASE4_INTEGRATED_RUN_REQUIRED"
                ),
            },
        ]
    else:
        methods = [
            _method("M0", source="RULE_ADAPTER_COMPLETED"),
            {
                "method_id": "M1",
                "candidate_available": False,
                "construction_status": "SEPARATE_PHASE1_RUN_REQUIRED",
            },
            _method("M2", source="RULE_ADAPTER_COMPLETED"),
            _method("M3", source="PRIMARY_PHASE4_DAY_AHEAD_RESULT"),
        ]
    payload = {
        "schema_version": "thesis_day_ahead_ablation_candidates_v1",
        "status": "PARTIAL_CANDIDATE_SET",
        "comparison_scope": "same_canonical_problem_day_ahead",
        "primary_optimization_structure": structure,
        "primary_optimization_structure_source": (
            "engine_result.solver_metadata"
        ),
        "rolling_costs_mixed_into_comparison": False,
        "additional_solver_invoked_by_postprocessor": False,
        "research_conclusion_eligible": False,
        "methods": methods,
    }
    payload["payload_sha256"] = _payload_sha(payload)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_run(
    run_dir: Path,
    *,
    structure: str,
    prepared_input_id: str = "prepared-1",
    prepared_sha: str = "prepared-sha",
    canonical_sha: str = "canonical-sha",
    git_sha: str = "git-sha",
    recorded_phase: str | None = None,
) -> None:
    scenario_id = "scenario-1"
    phase = recorded_phase or (
        "phase1_charging_only"
        if structure == "charging_only"
        else "phase4_integrated"
    )
    prepared_path = run_dir.parent / f"{prepared_input_id}-{prepared_sha}.json"
    prepared_path.write_text(
        json.dumps(
            {"prepared_input_id": prepared_input_id, "marker": prepared_sha}
        ),
        encoding="utf-8",
    )
    actual_prepared_sha = _file_sha(prepared_path)
    _write_json(
        run_dir / "thesis_ablation/day_ahead_method_candidates.json",
        _candidate_payload(structure=structure),
    )
    _write_json(
        run_dir / "optimization_parameters.json",
        {
            "schema_version": "frontend_run_input_provenance_v2",
            "scenario_id": scenario_id,
            "prepared_input_id": prepared_input_id,
            "frontend_request": {
                "research_run": True,
                "scenario_id": scenario_id,
                "prepared_input_id": prepared_input_id,
            },
            "effective_optimization_config": {"research_run": True},
            "canonical_input_dimensions": {
                "canonical_ablation_input_sha256": canonical_sha,
            },
        },
    )
    _write_json(
        run_dir / "prepare_input_audit.json",
        {
            "schema_version": "frontend_run_input_provenance_v2",
            "scenario_id": scenario_id,
            "prepared_input_id": prepared_input_id,
            "source_artifact": {
                "absolute_path": str(prepared_path.resolve()),
                "repository_relative_path": None,
                "size_bytes": prepared_path.stat().st_size,
                "sha256": actual_prepared_sha,
            },
        },
    )
    _write_json(
        run_dir / "code_provenance.json",
        {
            "git_sha": git_sha,
            "git_dirty": False,
            "git_state_available": True,
            "git_state_error": None,
        },
    )
    _write_json(
        run_dir / "run_input_validation.json",
        {"valid": True, "research_ready": True},
    )
    _write_json(
        run_dir / "summary.json",
        {
            "solver_status": "optimal",
            "mip_gap_target_met": True,
            "solution_validity": {
                "validated_feasible": True,
                "research_acceptance_status": "ACCEPTED",
                "research_acceptance_failed_checks": [],
            },
        },
    )
    _write_json(
        run_dir / "solver_settings.json",
        {
            "research_run": True,
            "research_run_accepted": True,
            "mip_gap_target_met": True,
            "requested_phase": phase,
            "resolved_phase": phase,
            "executed_phase": phase,
        },
    )
    _write_json(
        run_dir / "scenario_input_snapshot.json",
        {
            "schema_version": "frontend_run_input_provenance_v2",
            "scenario_id": scenario_id,
        },
    )
    (run_dir / "run_input_summary.md").write_text(
        "# test input summary\n",
        encoding="utf-8",
    )
    core_names = (
        "scenario_input_snapshot.json",
        "prepare_input_audit.json",
        "optimization_parameters.json",
        "run_input_summary.md",
        "code_provenance.json",
    )
    artifacts = {
        name: {
            "size_bytes": (run_dir / name).stat().st_size,
            "sha256": _file_sha(run_dir / name),
        }
        for name in core_names
    }
    _write_json(
        run_dir / "run_input_manifest.json",
        {
            "schema_version": "frontend_run_input_provenance_v2",
            "scenario_id": scenario_id,
            "prepared_input_id": prepared_input_id,
            "prepared_source_sha256": actual_prepared_sha,
            "git_sha": git_sha,
            "git_dirty": False,
            "git_state_available": True,
            "artifacts": artifacts,
        },
    )
    _write_json(
        run_dir / "run_manifest.json",
        {
            "research_run": True,
            "research_run_accepted": True,
            "requested_phase": phase,
            "resolved_phase": phase,
            "executed_phase": phase,
        },
    )
    snapshot_names = (
        "thesis_ablation/day_ahead_method_candidates.json",
        "summary.json",
        "solver_settings.json",
        "run_manifest.json",
    )
    _write_json(
        run_dir / "artifact_completeness.json",
        {
            "schema_version": "frontend_run_artifact_contract_v1",
            "status": "OK",
            "accepted": True,
            "research_run": True,
            "artifacts": {
                name: {
                    "size_bytes": (run_dir / name).stat().st_size,
                    "sha256": _file_sha(run_dir / name),
                }
                for name in snapshot_names
            },
        },
    )


def test_complete_comparison_requires_explicit_same_input_phase1_and_phase4(
    tmp_path: Path,
) -> None:
    phase1_dir = tmp_path / "phase1"
    phase4_dir = tmp_path / "phase4"
    _write_run(phase1_dir, structure="charging_only")
    _write_run(phase4_dir, structure="integrated")

    payload = build_complete_day_ahead_ablation_comparison(
        phase1_run_dir=phase1_dir,
        phase4_run_dir=phase4_dir,
    )
    methods = {row["method_id"]: row for row in payload["methods"]}

    assert payload["status"] == "READY_FOR_DAY_AHEAD_METHOD_COMPARISON"
    assert payload["failed_checks"] == []
    assert payload["complete_four_method_comparison_available"] is True
    assert payload["research_conclusion_eligible"] is True
    assert payload["available_method_ids"] == ["M0", "M1", "M2", "M3"]
    assert methods["M1"]["source_run_dir"] == str(phase1_dir.resolve())
    assert methods["M3"]["source_run_dir"] == str(phase4_dir.resolve())
    assert len(comparison_csv_rows(payload)) == 4
    assert len(payload["payload_sha256"]) == 64


def test_comparison_blocks_a_changed_tariff_or_other_canonical_input(
    tmp_path: Path,
) -> None:
    phase1_dir = tmp_path / "phase1"
    phase4_dir = tmp_path / "phase4"
    _write_run(
        phase1_dir,
        structure="charging_only",
        canonical_sha="phase1-input",
    )
    _write_run(
        phase4_dir,
        structure="integrated",
        canonical_sha="phase4-input",
    )

    payload = build_complete_day_ahead_ablation_comparison(
        phase1_run_dir=phase1_dir,
        phase4_run_dir=phase4_dir,
    )

    assert payload["status"] == "BLOCKED"
    assert payload["research_conclusion_eligible"] is False
    assert payload["available_method_ids"] == []
    assert "same_nonempty_canonical_ablation_input_sha256" in payload[
        "failed_checks"
    ]


def test_comparison_blocks_wrong_recorded_execution_phase(
    tmp_path: Path,
) -> None:
    phase1_dir = tmp_path / "phase1"
    phase4_dir = tmp_path / "phase4"
    _write_run(
        phase1_dir,
        structure="charging_only",
        recorded_phase="phase3_two_stage",
    )
    _write_run(phase4_dir, structure="integrated")

    payload = build_complete_day_ahead_ablation_comparison(
        phase1_run_dir=phase1_dir,
        phase4_run_dir=phase4_dir,
    )

    assert payload["status"] == "BLOCKED"
    assert "phase1_execution_is_explicit_charging_only" in payload[
        "failed_checks"
    ]


def test_comparison_blocks_tampered_source_candidate_payload(
    tmp_path: Path,
) -> None:
    phase1_dir = tmp_path / "phase1"
    phase4_dir = tmp_path / "phase4"
    _write_run(phase1_dir, structure="charging_only")
    _write_run(phase4_dir, structure="integrated")
    candidate_path = (
        phase1_dir / "thesis_ablation/day_ahead_method_candidates.json"
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["methods"][1]["cost_breakdown"]["total_cost"] = 1.0
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    payload = build_complete_day_ahead_ablation_comparison(
        phase1_run_dir=phase1_dir,
        phase4_run_dir=phase4_dir,
    )

    assert payload["status"] == "BLOCKED"
    assert "phase1_candidate_payload_valid" in payload["failed_checks"]


def test_comparison_revalidates_source_manifest_at_merge_time(
    tmp_path: Path,
) -> None:
    phase1_dir = tmp_path / "phase1"
    phase4_dir = tmp_path / "phase4"
    _write_run(phase1_dir, structure="charging_only")
    _write_run(phase4_dir, structure="integrated")
    parameters_path = phase1_dir / "optimization_parameters.json"
    parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
    parameters["canonical_input_dimensions"][
        "canonical_ablation_input_sha256"
    ] = "posthoc-edit"
    parameters_path.write_text(json.dumps(parameters), encoding="utf-8")

    payload = build_complete_day_ahead_ablation_comparison(
        phase1_run_dir=phase1_dir,
        phase4_run_dir=phase4_dir,
    )

    assert payload["status"] == "BLOCKED"
    assert "both_run_input_bundles_valid" in payload["failed_checks"]


def test_comparison_blocks_posthoc_summary_edit(
    tmp_path: Path,
) -> None:
    phase1_dir = tmp_path / "phase1"
    phase4_dir = tmp_path / "phase4"
    _write_run(phase1_dir, structure="charging_only")
    _write_run(phase4_dir, structure="integrated")
    summary_path = phase1_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["mip_gap_target_met"] = False
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    payload = build_complete_day_ahead_ablation_comparison(
        phase1_run_dir=phase1_dir,
        phase4_run_dir=phase4_dir,
    )

    assert payload["status"] == "BLOCKED"
    assert "both_finalized_artifact_snapshots_valid" in payload[
        "failed_checks"
    ]
    assert "both_source_mip_gap_targets_met" in payload["failed_checks"]
