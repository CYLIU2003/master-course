"""Merge explicit Phase 1 and Phase 4 runs into an audited M0--M3 comparison.

The ordinary frontend job deliberately executes one solver phase.  M1 and M3
therefore come from separate frontend jobs.  This module proves that both jobs
used the same prepared input, clean frozen code, and canonical mathematical
input before selecting M0/M1/M2/M3 from their day-ahead candidate artifacts.
It never invokes a solver and never mixes Rolling accounting into the method
comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from bff.services.optimization_run.input_provenance import (
    validate_run_input_provenance,
)


SCHEMA_VERSION = "thesis_day_ahead_ablation_comparison_v1"
SOURCE_CANDIDATE_PATH = Path(
    "thesis_ablation/day_ahead_method_candidates.json"
)
METHOD_ORDER = ("M0", "M1", "M2", "M3")


@dataclass(frozen=True)
class _RunEvidence:
    run_dir: Path
    candidates: Mapping[str, Any]
    parameters: Mapping[str, Any]
    prepare_audit: Mapping[str, Any]
    code_provenance: Mapping[str, Any]
    input_validation: Mapping[str, Any]
    solver_settings: Mapping[str, Any]
    summary: Mapping[str, Any]
    run_manifest: Mapping[str, Any]
    artifact_completeness: Mapping[str, Any]


def build_complete_day_ahead_ablation_comparison(
    *,
    phase1_run_dir: Path,
    phase4_run_dir: Path,
) -> dict[str, Any]:
    """Return a fail-closed same-input M0--M3 comparison artifact."""

    phase1 = _load_run(Path(phase1_run_dir))
    phase4 = _load_run(Path(phase4_run_dir))
    phase1_methods = _methods_by_id(phase1.candidates)
    phase4_methods = _methods_by_id(phase4.candidates)
    checks = _comparison_checks(
        phase1=phase1,
        phase4=phase4,
        phase1_methods=phase1_methods,
        phase4_methods=phase4_methods,
    )
    failed_checks = [name for name, passed in checks.items() if not passed]
    verified = not failed_checks

    selected_sources = {
        "M0": (phase4, phase4_methods.get("M0")),
        "M1": (phase1, phase1_methods.get("M1")),
        "M2": (phase4, phase4_methods.get("M2")),
        "M3": (phase4, phase4_methods.get("M3")),
    }
    methods: list[dict[str, Any]] = []
    for method_id in METHOD_ORDER:
        evidence, method = selected_sources[method_id]
        row = dict(method or {})
        row["method_id"] = method_id
        row["source_run_dir"] = str(evidence.run_dir.resolve())
        row["source_candidate_payload_sha256"] = evidence.candidates.get(
            "payload_sha256"
        )
        row["source_git_sha"] = evidence.code_provenance.get("git_sha")
        methods.append(row)

    dimensions = dict(
        phase4.parameters.get("canonical_input_dimensions") or {}
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "READY_FOR_DAY_AHEAD_METHOD_COMPARISON"
            if verified
            else "BLOCKED"
        ),
        "comparison_scope": "same_canonical_problem_day_ahead",
        "cost_basis": "canonical_cost_evaluator_day_ahead",
        "rolling_costs_mixed_into_comparison": False,
        "additional_solver_invoked_by_comparison_builder": False,
        "explicit_source_phases": {
            "M1": "phase1_charging_only",
            "M3": "phase4_integrated",
        },
        "prepared_input_id": _prepared_input_id(phase4),
        "prepared_source_sha256": _prepared_source_sha(phase4),
        "canonical_ablation_input_sha256": dimensions.get(
            "canonical_ablation_input_sha256"
        ),
        "git_sha": phase4.code_provenance.get("git_sha"),
        "checks": checks,
        "failed_checks": failed_checks,
        "complete_four_method_comparison_available": verified,
        "available_method_ids": (
            list(METHOD_ORDER) if verified else []
        ),
        "day_ahead_comparable_method_ids": [
            method_id
            for method_id, row in zip(METHOD_ORDER, methods)
            if bool(row.get("day_ahead_comparison_eligible", False))
        ],
        "research_conclusion_eligible": verified,
        "research_claim_scope": (
            "same-input day-ahead M0-M3 method comparison only; source "
            "solver quality remains as recorded and Rolling costs are excluded"
        ),
        "source_runs": {
            "phase1": _source_summary(phase1),
            "phase4": _source_summary(phase4),
        },
        "methods": methods,
    }
    payload["payload_sha256"] = _payload_sha(payload)
    return payload


def comparison_csv_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a complete comparison to stable method-level reporting rows."""

    rows: list[dict[str, Any]] = []
    for method in list(payload.get("methods") or []):
        cost = dict(method.get("cost_breakdown") or {})
        rows.append(
            {
                "method_id": method.get("method_id"),
                "label": method.get("label"),
                "source_run_dir": method.get("source_run_dir"),
                "candidate_available": method.get("candidate_available"),
                "physical_feasible": method.get("physical_feasible"),
                "day_ahead_comparison_eligible": method.get(
                    "day_ahead_comparison_eligible"
                ),
                "used_bev_count": method.get("used_bev_count"),
                "used_ice_count": method.get("used_ice_count"),
                "bev_trip_count": method.get("bev_trip_count"),
                "ice_trip_count": method.get("ice_trip_count"),
                "electricity_cost_jpy": cost.get("electricity_cost_final"),
                "fuel_cost_jpy": cost.get("fuel_cost_final"),
                "vehicle_usage_cost_jpy": cost.get("vehicle_usage_cost"),
                "total_cost_jpy": cost.get("total_cost"),
                "total_co2_kg": cost.get("total_co2_kg"),
                "grid_import_kwh": cost.get("grid_import_kwh"),
                "pv_to_bus_kwh": cost.get("pv_to_bus_kwh"),
                "pv_to_bess_kwh": cost.get("pv_to_bess_kwh"),
                "bess_to_bus_kwh": cost.get("bess_to_bus_kwh"),
            }
        )
    return rows


def _comparison_checks(
    *,
    phase1: _RunEvidence,
    phase4: _RunEvidence,
    phase1_methods: Mapping[str, Mapping[str, Any]],
    phase4_methods: Mapping[str, Mapping[str, Any]],
) -> dict[str, bool]:
    phase1_dimensions = dict(
        phase1.parameters.get("canonical_input_dimensions") or {}
    )
    phase4_dimensions = dict(
        phase4.parameters.get("canonical_input_dimensions") or {}
    )
    phase1_hash = str(
        phase1_dimensions.get("canonical_ablation_input_sha256") or ""
    )
    phase4_hash = str(
        phase4_dimensions.get("canonical_ablation_input_sha256") or ""
    )
    phase1_git = str(phase1.code_provenance.get("git_sha") or "")
    phase4_git = str(phase4.code_provenance.get("git_sha") or "")
    return {
        "phase1_candidate_payload_valid": _candidate_payload_valid(
            phase1.candidates
        ),
        "phase4_candidate_payload_valid": _candidate_payload_valid(
            phase4.candidates
        ),
        "phase1_structure_is_charging_only": (
            phase1.candidates.get("primary_optimization_structure")
            == "charging_only"
        ),
        "phase4_structure_is_integrated": (
            phase4.candidates.get("primary_optimization_structure")
            == "integrated"
        ),
        "phase1_execution_is_explicit_charging_only": (
            _recorded_execution_phase_matches(
                phase1,
                expected="phase1_charging_only",
            )
        ),
        "phase4_execution_is_explicit_integrated": (
            _recorded_execution_phase_matches(
                phase4,
                expected="phase4_integrated",
            )
        ),
        "same_nonempty_prepared_input_id": bool(
            _prepared_input_id(phase1)
            and _prepared_input_id(phase1) == _prepared_input_id(phase4)
        ),
        "same_nonempty_prepared_source_sha256": bool(
            _prepared_source_sha(phase1)
            and _prepared_source_sha(phase1) == _prepared_source_sha(phase4)
        ),
        "same_nonempty_canonical_ablation_input_sha256": bool(
            phase1_hash and phase1_hash == phase4_hash
        ),
        "same_nonempty_git_sha": bool(
            phase1_git and phase1_git == phase4_git
        ),
        "both_git_states_available": bool(
            phase1.code_provenance.get("git_state_available") is True
            and phase4.code_provenance.get("git_state_available") is True
        ),
        "both_git_states_clean": bool(
            phase1.code_provenance.get("git_dirty") is False
            and phase4.code_provenance.get("git_dirty") is False
        ),
        "both_run_input_bundles_valid": bool(
            phase1.input_validation.get("valid") is True
            and phase4.input_validation.get("valid") is True
        ),
        "both_run_input_bundles_research_ready": bool(
            phase1.input_validation.get("research_ready") is True
            and phase4.input_validation.get("research_ready") is True
        ),
        "both_finalized_artifact_snapshots_valid": bool(
            _finalized_artifact_snapshot_valid(phase1)
            and _finalized_artifact_snapshot_valid(phase4)
        ),
        "both_requested_as_research_runs": bool(
            _research_run_requested(phase1)
            and _research_run_requested(phase4)
        ),
        "both_source_solutions_research_accepted": bool(
            _source_solution_research_accepted(phase1)
            and _source_solution_research_accepted(phase4)
        ),
        "both_source_mip_gap_targets_met": bool(
            phase1.summary.get("mip_gap_target_met") is True
            and phase4.summary.get("mip_gap_target_met") is True
            and phase1.solver_settings.get("mip_gap_target_met") is True
            and phase4.solver_settings.get("mip_gap_target_met") is True
        ),
        "m0_candidates_identical": bool(
            phase1_methods.get("M0")
            and _method_sha(phase1_methods["M0"])
            == _method_sha(phase4_methods.get("M0") or {})
        ),
        "m1_candidate_eligible": _method_eligible(
            phase1_methods.get("M1")
        ),
        "m2_candidate_eligible": _method_eligible(
            phase4_methods.get("M2")
        ),
        "m3_candidate_eligible": _method_eligible(
            phase4_methods.get("M3")
        ),
        "m0_candidate_eligible": _method_eligible(
            phase4_methods.get("M0")
        ),
    }


def _load_run(run_dir: Path) -> _RunEvidence:
    resolved = run_dir.resolve()
    return _RunEvidence(
        run_dir=resolved,
        candidates=_load_json(resolved / SOURCE_CANDIDATE_PATH),
        parameters=_load_json(resolved / "optimization_parameters.json"),
        prepare_audit=_load_json(resolved / "prepare_input_audit.json"),
        code_provenance=_load_json(resolved / "code_provenance.json"),
        input_validation=validate_run_input_provenance(
            resolved,
            verify_prepared_source=True,
        ),
        solver_settings=_load_json(resolved / "solver_settings.json"),
        summary=_load_json(resolved / "summary.json"),
        run_manifest=_load_json(resolved / "run_manifest.json"),
        artifact_completeness=_load_json(
            resolved / "artifact_completeness.json"
        ),
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required ablation source artifact missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"ablation source artifact must be a JSON object: {path}")
    return payload


def _methods_by_id(
    payload: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("method_id") or ""): row
        for row in list(payload.get("methods") or [])
        if isinstance(row, Mapping)
    }


def _candidate_payload_valid(payload: Mapping[str, Any]) -> bool:
    if payload.get("schema_version") != (
        "thesis_day_ahead_ablation_candidates_v1"
    ):
        return False
    declared = str(payload.get("payload_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("payload_sha256", None)
    return bool(declared and declared == _payload_sha(unsigned))


def _prepared_input_id(evidence: _RunEvidence) -> str:
    return str(evidence.prepare_audit.get("prepared_input_id") or "")


def _prepared_source_sha(evidence: _RunEvidence) -> str:
    source = dict(evidence.prepare_audit.get("source_artifact") or {})
    return str(source.get("sha256") or "")


def _research_run_requested(evidence: _RunEvidence) -> bool:
    request = dict(evidence.parameters.get("frontend_request") or {})
    config = dict(evidence.parameters.get("effective_optimization_config") or {})
    return bool(
        request.get("research_run") is True
        and config.get("research_run") is True
        and evidence.solver_settings.get("research_run") is True
        and evidence.run_manifest.get("research_run") is True
    )


def _recorded_execution_phase_matches(
    evidence: _RunEvidence,
    *,
    expected: str,
) -> bool:
    recorded = (
        evidence.run_manifest.get("requested_phase"),
        evidence.run_manifest.get("resolved_phase"),
        evidence.run_manifest.get("executed_phase"),
        evidence.solver_settings.get("requested_phase"),
        evidence.solver_settings.get("resolved_phase"),
        evidence.solver_settings.get("executed_phase"),
    )
    return all(str(value or "").strip().lower() == expected for value in recorded)


def _source_solution_research_accepted(evidence: _RunEvidence) -> bool:
    validity = dict(evidence.summary.get("solution_validity") or {})
    return bool(
        validity.get("validated_feasible") is True
        and validity.get("research_acceptance_status") == "ACCEPTED"
        and not list(validity.get("research_acceptance_failed_checks") or [])
        and evidence.solver_settings.get("research_run_accepted") is True
        and evidence.run_manifest.get("research_run_accepted") is True
    )


def _finalized_artifact_snapshot_valid(evidence: _RunEvidence) -> bool:
    """Verify the immutable hashes recorded when the frontend run finalized."""

    audit = evidence.artifact_completeness
    if not (
        audit.get("status") == "OK"
        and audit.get("accepted") is True
        and audit.get("research_run") is True
    ):
        return False
    artifacts = dict(audit.get("artifacts") or {})
    required_paths = (
        SOURCE_CANDIDATE_PATH.as_posix(),
        "summary.json",
        "solver_settings.json",
        "run_manifest.json",
    )
    for relative_path in required_paths:
        record = dict(artifacts.get(relative_path) or {})
        path = evidence.run_dir / relative_path
        if not path.is_file():
            return False
        try:
            size_bytes = path.stat().st_size
            actual_sha = sha256(path.read_bytes()).hexdigest()
        except OSError:
            return False
        if record.get("size_bytes") != size_bytes:
            return False
        declared_sha = str(record.get("sha256") or "")
        if not declared_sha or declared_sha != actual_sha:
            return False
    return True


def _method_eligible(method: Mapping[str, Any] | None) -> bool:
    return bool(
        method
        and method.get("candidate_available") is True
        and method.get("physical_feasible") is True
        and method.get("day_ahead_comparison_eligible") is True
    )


def _method_sha(method: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            method,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _source_summary(evidence: _RunEvidence) -> dict[str, Any]:
    return {
        "run_dir": str(evidence.run_dir),
        "prepared_input_id": _prepared_input_id(evidence),
        "prepared_source_sha256": _prepared_source_sha(evidence),
        "git_sha": evidence.code_provenance.get("git_sha"),
        "git_dirty": evidence.code_provenance.get("git_dirty"),
        "candidate_payload_sha256": evidence.candidates.get("payload_sha256"),
        "primary_optimization_structure": evidence.candidates.get(
            "primary_optimization_structure"
        ),
        "solver_status": evidence.summary.get("solver_status"),
        "finalized_artifact_snapshot_valid": (
            _finalized_artifact_snapshot_valid(evidence)
        ),
        "solution_validity": evidence.summary.get("solution_validity"),
    }


def _payload_sha(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
