"""Normalize one completed RAIN profile directory into a fail-closed result."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_SOURCE_FILES = (
    "stage1_stage2_candidate_evaluation.json",
    "physical_schedule_validation.json",
    "rolling_hourly_chain/rolling_chain_summary.json",
    "rolling_hourly_chain/executed_day_accounting.json",
    "final_cost_reconciliation.json",
    "summary.json",
    "optimization_parameters.json",
    "code_provenance.json",
    "input_audit.json",
    "effective_controls.json",
)


def _read_json(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(f"missing required profile artifact: {relative}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"profile artifact must be an object: {relative}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assignment_powertrain_hash(row: Mapping[str, Any]) -> str | None:
    assignments = row.get("vehicle_trip_assignments")
    if not isinstance(assignments, list) or not assignments:
        return None
    normalized = sorted(
        (
            {
                "trip_id": str(item.get("trip_id") or ""),
                "vehicle_type": str(item.get("powertrain") or "").upper(),
            }
            for item in assignments
            if isinstance(item, Mapping)
        ),
        key=lambda item: (item["trip_id"], item["vehicle_type"]),
    )
    if len(normalized) != len(assignments) or any(
        not item["trip_id"] or not item["vehicle_type"] for item in normalized
    ):
        return None
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _physical_assignment_hash(row: Mapping[str, Any]) -> str | None:
    assignments = row.get("vehicle_trip_assignments")
    if not isinstance(assignments, list) or not assignments:
        return None
    pairs = sorted(
        (
            str(item.get("vehicle_id") or ""),
            str(item.get("trip_id") or ""),
        )
        for item in assignments
        if isinstance(item, Mapping)
    )
    if len(pairs) != len(assignments) or any(not vehicle or not trip for vehicle, trip in pairs):
        return None
    return hashlib.sha256(
        json.dumps(pairs, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _candidate_assignment_audit(row: Mapping[str, Any]) -> dict[str, Any]:
    assignments = row.get("vehicle_trip_assignments")
    if not isinstance(assignments, list):
        return {
            "assignment_count": None,
            "unique_trip_count": None,
            "unique_vehicle_count": None,
            "covers_264_unique_trips": False,
        }
    trip_ids = [
        str(item.get("trip_id") or "")
        for item in assignments
        if isinstance(item, Mapping)
    ]
    vehicle_ids = {
        str(item.get("vehicle_id") or "")
        for item in assignments
        if isinstance(item, Mapping) and item.get("vehicle_id")
    }
    complete_rows = len(trip_ids) == len(assignments) and all(trip_ids)
    return {
        "assignment_count": len(assignments),
        "unique_trip_count": len(set(trip_ids)) if complete_rows else None,
        "unique_vehicle_count": len(vehicle_ids) if complete_rows else None,
        "covers_264_unique_trips": bool(
            complete_rows and len(assignments) == 264 and len(set(trip_ids)) == 264
        ),
    }


def _candidate_gate(
    raw: Mapping[str, Any],
    *,
    assignment_hash: str,
    computed_assignment_hash: str | None,
    used_vehicle_count: int | None,
    assignment_audit: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    """Evaluate only evidence persisted for this candidate; never borrow run gates."""

    checks = {
        "persisted_selectable_true": raw.get("selectable") is True,
        "stage2_feasible_true": raw.get("stage2_feasible") is True,
        "canonical_evaluation_feasible_true": (
            raw.get("canonical_evaluation_feasible") is True
        ),
        "candidate_accounting_passed": (
            raw.get("accounting_reconciliation_passed") is True
        ),
        "candidate_physical_validation_passed": (
            raw.get("physical_validation_feasible") is True
        ),
        "candidate_served_264": raw.get("trip_count_served") == 264,
        "candidate_unserved_zero": raw.get("trip_count_unserved") == 0,
        "candidate_fallback_absent": raw.get("fallback_used") is False,
        "candidate_repair_absent": raw.get("repair_used") is False,
        "candidate_proxy_absent": raw.get("proxy_used") is False,
        "canonical_cost_finite": _finite(raw.get("stage2_actual_canonical_cost_jpy")),
        "assignment_hash_valid": bool(_SHA256_RE.fullmatch(assignment_hash)),
        "assignment_hash_verified": computed_assignment_hash == assignment_hash,
        "covers_264_unique_trips": assignment_audit.get("covers_264_unique_trips") is True,
        "used_vehicle_count_consistent": bool(
            used_vehicle_count is not None
            and assignment_audit.get("unique_vehicle_count") == used_vehicle_count
        ),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return not blockers, blockers


def normalize_profile_result(
    case_dir: Path,
    *,
    profile_name: str,
    requested_controls: Mapping[str, Any],
    expected_code_sha: str,
) -> dict[str, Any]:
    """Build the only analyzer input accepted from a completed profile run."""

    artifacts = {name: _read_json(case_dir, name) for name in _REQUIRED_SOURCE_FILES}
    candidates_payload = artifacts["stage1_stage2_candidate_evaluation.json"]
    physical = artifacts["physical_schedule_validation.json"]
    rolling = artifacts["rolling_hourly_chain/rolling_chain_summary.json"]
    accounting = artifacts["rolling_hourly_chain/executed_day_accounting.json"]
    reconciliation = artifacts["final_cost_reconciliation.json"]
    summary = artifacts["summary.json"]
    parameters = artifacts["optimization_parameters.json"]
    provenance = artifacts["code_provenance.json"]
    input_audit = artifacts["input_audit.json"]
    control_audit = artifacts["effective_controls.json"]

    selected_index = candidates_payload.get("selected_candidate_index")
    raw_candidates = list(candidates_payload.get("candidates") or ())
    selected_raw = next(
        (
            row for row in raw_candidates
            if isinstance(row, Mapping) and row.get("candidate_index") == selected_index
        ),
        None,
    )
    validity = dict(summary.get("solution_validity") or {})
    acceptance = dict(validity.get("research_acceptance_checks") or {})
    formal_gates = {
        "served_264": summary.get("trip_count_served") == 264,
        "unserved_zero": summary.get("trip_count_unserved") == 0,
        "physical_validation_passed": (
            physical.get("accepted") is True and not physical.get("failed_checks")
        ),
        "rolling_24_of_24": bool(
            rolling.get("chain_accepted") is True
            and rolling.get("all_steps_feasible") is True
            and rolling.get("expected_step_count") == 24
            and rolling.get("step_count") == 24
        ),
        "accounting_reconciliation_passed": bool(
            accounting.get("eligible") is True
            and reconciliation.get("status") == "OK"
            and not reconciliation.get("failed_artifacts")
        ),
        "fallback_absent": acceptance.get("no_fallback") is True,
        "repair_absent": acceptance.get("no_postsolve_modification") is True,
        "code_sha_matches": bool(
            _SHA40_RE.fullmatch(expected_code_sha)
            and provenance.get("git_sha") == expected_code_sha
            and provenance.get("git_dirty") is False
            and rolling.get("day_ahead_git_sha") == expected_code_sha
        ),
        "selected_candidate_present": selected_raw is not None,
        "selected_candidate_hash_matches": bool(
            selected_raw is not None
            and candidates_payload.get("selected_candidate_hash")
            == selected_raw.get("candidate_hash")
        ),
        "selected_candidate_cost_matches": bool(
            selected_raw is not None
            and _finite(candidates_payload.get("selected_canonical_actual_cost_jpy"))
            and float(candidates_payload["selected_canonical_actual_cost_jpy"])
            == float(selected_raw.get("stage2_actual_canonical_cost_jpy"))
        ),
        "requested_effective_controls_matched": control_audit.get("matched") is True,
    }
    normalized_candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            continue
        assignment_hash = str(raw.get("assignment_hash") or "")
        computed_assignment_hash = _physical_assignment_hash(raw)
        candidate_is_selected = raw.get("candidate_index") == selected_index
        assignment_audit = _candidate_assignment_audit(raw)
        used_vehicle_count = (
            int(raw.get("used_bev")) + int(raw.get("used_ice"))
            if raw.get("used_bev") is not None and raw.get("used_ice") is not None
            else None
        )
        candidate_selectable, candidate_blockers = _candidate_gate(
            raw,
            assignment_hash=assignment_hash,
            computed_assignment_hash=computed_assignment_hash,
            used_vehicle_count=used_vehicle_count,
            assignment_audit=assignment_audit,
        )
        row = dict(raw)
        row.update(
            {
                "persisted_selectable": raw.get("selectable"),
                "assignment_powertrain_hash": _assignment_powertrain_hash(raw),
                "computed_assignment_hash": computed_assignment_hash,
                "assignment_hash_verified": computed_assignment_hash == assignment_hash,
                "used_vehicle_count": used_vehicle_count,
                **assignment_audit,
                "selectable": candidate_selectable,
                "candidate_formal_status": (
                    "FULLY_SELECTABLE" if candidate_selectable
                    else "GENERATED_NOT_EVALUATED"
                    if raw.get("canonical_evaluation_feasible") is None
                    else "EVALUATED_BUT_NOT_FORMALLY_SELECTABLE"
                ),
                "candidate_gate_blockers": candidate_blockers,
                "is_selected_candidate": candidate_is_selected,
            }
        )
        normalized_candidates.append(row)

    selected = next(
        (row for row in normalized_candidates if row.get("candidate_index") == selected_index),
        None,
    )
    generated = {
        str(row.get("assignment_hash")) for row in normalized_candidates
        if row.get("assignment_hash_verified") is True
        and _SHA256_RE.fullmatch(str(row.get("assignment_hash") or ""))
    }
    evaluated = {
        str(row.get("assignment_hash")) for row in normalized_candidates
        if row.get("assignment_hash_verified") is True
        and row.get("canonical_evaluation_feasible") is not None
        and _SHA256_RE.fullmatch(str(row.get("assignment_hash") or ""))
    }
    selectable = {
        str(row["assignment_hash"]) for row in normalized_candidates if row["selectable"]
    }
    selected_run_formally_accepted = bool(
        selected
        and all(formal_gates.values())
        and selected.get("stage2_feasible") is True
        and selected.get("canonical_evaluation_feasible") is True
        and selected.get("physical_validation_feasible") is True
        and selected.get("assignment_hash_verified") is True
        and selected.get("covers_264_unique_trips") is True
        and _finite(selected.get("stage2_actual_canonical_cost_jpy"))
    )
    evidence_incomplete = [
        int(row["candidate_index"])
        for row in normalized_candidates
        if row.get("canonical_evaluation_feasible") is not None
        and row.get("candidate_formal_status") != "FULLY_SELECTABLE"
    ]
    evaluated_count_matches_source = bool(
        evaluated
        and len(evaluated) == candidates_payload.get("candidate_count_evaluated")
    )
    source_hashes = {
        name: _sha256(case_dir / name) for name in _REQUIRED_SOURCE_FILES
    }
    effective = dict(parameters.get("effective_optimization_config") or {})
    result = {
        "schema_version": "rain_profile_result_v1",
        "status": "ACCEPTED" if selected_run_formally_accepted else "REJECTED",
        "profile_name": profile_name,
        "scenario_id": summary.get("scenario_id") or parameters.get("scenario_id"),
        "prepared_input_id": parameters.get("prepared_input_id") or rolling.get("prepared_input_id"),
        "code_sha": expected_code_sha,
        "requested_controls": dict(requested_controls),
        "effective_controls": dict(control_audit.get("effective") or effective),
        "stage1_gap": summary.get("stage1_certified_mip_gap_ratio"),
        "stage1_raw_gap": summary.get("stage1_gurobi_raw_mip_gap_ratio"),
        "runtime_seconds": summary.get("solve_time_seconds"),
        "termination_reason": summary.get("stage1_termination_reason"),
        "trip_count_served": summary.get("trip_count_served"),
        "trip_count_unserved": summary.get("trip_count_unserved"),
        "physical_validation_status": (
            "PASS" if formal_gates["physical_validation_passed"] else "FAIL"
        ),
        "rolling_status": (
            "24_OF_24_ACCEPTED" if formal_gates["rolling_24_of_24"] else "FAILED"
        ),
        "accounting_status": (
            "PASS" if formal_gates["accounting_reconciliation_passed"] else "FAIL"
        ),
        "fallback_used": not formal_gates["fallback_absent"],
        "repair_used": not formal_gates["repair_absent"],
        "proxy_used": selected.get("proxy_used") if selected else None,
        "candidate_counts": {
            "generated": len(generated),
            "evaluated": len(evaluated),
            "fully_selectable": len(selectable),
        },
        "generated_assignment_hashes": sorted(generated),
        "evaluated_assignment_hashes": sorted(evaluated),
        "fully_selectable_assignment_hashes": sorted(selectable),
        "candidate_stability_evidence_status": (
            "COMPLETE"
            if not evidence_incomplete and evaluated_count_matches_source
            else "INSUFFICIENT"
        ),
        "candidate_stability_blocker": (
            None
            if not evidence_incomplete and evaluated_count_matches_source
            else "BLOCKED_CANDIDATE_LEVEL_EVIDENCE_INSUFFICIENT"
        ),
        "candidate_indices_with_incomplete_formal_evidence": evidence_incomplete,
        "candidates": normalized_candidates,
        "selected_candidate": selected,
        "selected_run_formally_accepted": selected_run_formally_accepted,
        "formal_gates": formal_gates,
        "source_artifact_hashes": source_hashes,
        "canonical_fixed_input_hashes": {
            key: (
                input_audit.get(key)
                if key in input_audit
                else rolling.get(key)
            )
            for key in (
                "prepared_input_sha256", "effective_scenario_sha256", "trip_input_hash",
                "vehicle_input_hash", "scenario_fleet_contract_hash",
                "active_vehicle_id_hash", "vehicle_parameter_hash", "initial_state_hash",
                "charger_configuration_hash", "initial_soc_input_hash",
                "effective_pv_profiles_sha256", "depot_energy_assets_fixed_hash",
            )
        },
    }
    return result


def write_profile_result(path: Path, result: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
