"""Build fail-closed reporting data for the 0.8--1.2 demand tranche."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


REPORTING_SCHEMA_VERSION = "trip_energy_sensitivity_reporting_v1"
REQUIRED_CASE_SCALES = {
    "ENERGY_0.8": 0.8,
    "ENERGY_0.9": 0.9,
    "ENERGY_1.0": 1.0,
    "ENERGY_1.1": 1.1,
    "ENERGY_1.2": 1.2,
}
REQUIRED_TRUE_CHECKS = (
    "frontend_job_completed",
    "run_input_valid",
    "run_input_research_ready",
    "artifact_bundle_complete",
    "finalized_artifact_hashes_match",
    "explicit_phase4_integrated",
    "research_run_accepted",
    "no_successor_pruning",
    "physical_schedule_valid",
    "rolling_accounting_eligible",
    "rolling_soc_evidence_verified",
    "declared_case_parameter_effective",
    "declared_common_controls_effective",
    "submitted_request_provenance_matches",
    "prepared_trip_structure_verified",
    "source_run_matches_original_frozen_git_sha",
)


def build_trip_energy_sensitivity_report(
    source_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one completed five-case tranche and return its snapshot."""

    failed_checks: list[str] = []
    source_payload_hash = str(source_manifest.get("payload_sha256") or "")
    unsigned_source = _json_copy(source_manifest)
    unsigned_source.pop("payload_sha256", None)
    _record(
        failed_checks,
        "source_manifest_payload_sha256_valid",
        bool(source_payload_hash)
        and source_payload_hash == _canonical_hash(unsigned_source),
    )
    _record(
        failed_checks,
        "source_manifest_schema_supported",
        source_manifest.get("schema_version")
        == "thesis_sensitivity_execution_v2",
    )
    expected_ids = set(REQUIRED_CASE_SCALES)
    _record(
        failed_checks,
        "required_cases_selected",
        set(source_manifest.get("selected_case_ids") or []) == expected_ids,
    )
    _record(
        failed_checks,
        "required_cases_completed",
        set(source_manifest.get("completed_case_ids") or []) == expected_ids
        and source_manifest.get("all_selected_cases_completed") is True,
    )
    _record(
        failed_checks,
        "stable_nonvaried_controls_match",
        source_manifest.get("stable_nonvaried_controls_match") is True,
    )

    outcomes = list(source_manifest.get("outcomes") or [])
    by_id = {
        str(outcome.get("case_id") or ""): outcome
        for outcome in outcomes
        if isinstance(outcome, Mapping)
    }
    _record(
        failed_checks,
        "one_outcome_per_required_case",
        len(outcomes) == len(expected_ids) and set(by_id) == expected_ids,
    )
    source_git_sha = str(source_manifest.get("frozen_git_sha") or "")
    audit_builder_sha = str(
        source_manifest.get("audit_builder_git_sha") or ""
    )
    _record(failed_checks, "source_git_sha_recorded", bool(source_git_sha))
    _record(
        failed_checks,
        "audit_builder_git_sha_recorded",
        bool(audit_builder_sha),
    )

    fingerprints: set[str] = set()
    prepared_trip_hashes: set[str] = set()
    rows: list[dict[str, Any]] = []
    for case_id, scale in REQUIRED_CASE_SCALES.items():
        outcome = by_id.get(case_id)
        if outcome is None:
            continue
        case_failures = _validate_case(outcome)
        failed_checks.extend(f"{case_id}:{name}" for name in case_failures)
        fingerprints.add(str(outcome.get("stable_control_fingerprint") or ""))
        prepared_trip_hashes.add(
            str(outcome.get("prepared_trip_input_sha256") or "")
        )
        rows.append(_reporting_row(outcome, scale=scale))

    _record(
        failed_checks,
        "single_nonempty_stable_control_fingerprint",
        len(fingerprints) == 1 and "" not in fingerprints,
    )
    _record(
        failed_checks,
        "single_nonempty_prepared_trip_hash",
        len(prepared_trip_hashes) == 1 and "" not in prepared_trip_hashes,
    )
    rows.sort(key=lambda row: float(row["trip_energy_scale"]))
    reference = next(
        (row for row in rows if row["trip_energy_scale"] == 1.0),
        None,
    )
    _record(failed_checks, "reference_case_available", reference is not None)
    if reference is not None:
        _add_reference_deltas(rows, reference=reference)

    all_gap_targets_met = bool(rows) and all(
        row["mip_gap_target_met"] is True for row in rows
    )
    only_gap_gate_failed = bool(rows) and not failed_checks and all(
        set(row["failed_checks"]).issubset({"mip_gap_target_met"})
        for row in rows
    )
    status = (
        "BLOCKED_INVALID_SOURCE_EVIDENCE"
        if failed_checks
        else "READY_FOR_TRIP_ENERGY_SENSITIVITY"
        if all_gap_targets_met
        else "DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED"
        if only_gap_gate_failed
        else "BLOCKED_UNCLASSIFIED_CASE_FAILURE"
    )
    transitions = _observed_dispatch_transitions(rows)
    dispatch_nonincreasing = bool(rows) and all(
        left["bev_trip_count"] >= right["bev_trip_count"]
        for left, right in zip(rows, rows[1:])
    )
    reporting_eligible = bool(rows) and status in {
        "READY_FOR_TRIP_ENERGY_SENSITIVITY",
        "DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED",
    }
    payload: dict[str, Any] = {
        "schema_version": REPORTING_SCHEMA_VERSION,
        "status": status,
        "reporting_eligible": reporting_eligible,
        "research_conclusion_eligible": (
            all_gap_targets_met and not failed_checks
        ),
        "transition_boundary_certified": (
            all_gap_targets_met and not failed_checks
        ),
        "claim_scope": (
            "Physical, executed-Rolling, and accounting comparison of "
            "feasible incumbents only. Every day-ahead solve missed the "
            "predeclared 1% MIP-gap target, so the observed dispatch steps "
            "do not certify an exact demand transition boundary or global "
            "optimality."
            if not all_gap_targets_met and not failed_checks
            else "Certified five-level trip-energy demand sensitivity."
            if all_gap_targets_met and not failed_checks
            else "No research claim is permitted because source evidence failed."
        ),
        "failed_checks": failed_checks,
        "source_execution_payload_sha256": source_payload_hash,
        "source_execution_manifest_sha256": source_manifest.get(
            "source_execution_manifest_sha256"
        ),
        "source_run_git_sha": source_git_sha,
        "source_audit_builder_git_sha": audit_builder_sha,
        "stable_control_fingerprint": (
            next(iter(fingerprints))
            if len(fingerprints) == 1 and "" not in fingerprints
            else None
        ),
        "prepared_trip_input_sha256": (
            next(iter(prepared_trip_hashes))
            if len(prepared_trip_hashes) == 1 and "" not in prepared_trip_hashes
            else None
        ),
        "rolling_execution_minutes": 60,
        "observed_bev_trip_count_nonincreasing": dispatch_nonincreasing,
        "observed_dispatch_transition_intervals": transitions,
        "rows": rows,
    }
    payload["payload_sha256"] = _canonical_hash(payload)
    return payload


def render_trip_energy_sensitivity_markdown(
    report: Mapping[str, Any],
) -> str:
    """Render a concise progress-report table with an explicit claim limit."""

    rows = list(report.get("rows") or [])
    certified = report.get("transition_boundary_certified") is True
    notice = (
        "> All five cases met the declared MIP-gap target; the sensitivity "
        "may be used within its recorded assumptions."
        if certified
        else "> These are physically valid, accounting-eligible feasible "
        "incumbents. The 1% MIP-gap target was not met, so the observed "
        "dispatch steps are diagnostic and do not certify exact transition "
        "boundaries or global optima."
    )
    lines = [
        "# Trip-energy demand sensitivity (low-PV case)",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source run SHA: `{report.get('source_run_git_sha')}`",
        f"- Re-audit builder SHA: `{report.get('source_audit_builder_git_sha')}`",
        "- Varied parameter: deterministic BEV-kWh and ICE-liter trip demand scale",
        "- Fixed controls: timetable, fleet, chargers, PV/BESS, tariff, solver and Rolling controls",
        "",
        notice,
        "",
        "| Demand scale | BEV / ICE trips | Used BEV / ICE | Cost (JPY) | Delta vs 1.0 | CO2 (kg) | Grid (kWh) | Min executed SOC | Certified gap | Wall time |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {trip_energy_scale:.1f} | {bev_trip_count}/{ice_trip_count} | "
            "{used_bev_count}/{used_ice_count} | {total_cost_jpy:,.2f} | "
            "{cost_delta_vs_1_0_jpy:+,.2f} | {total_co2_kg:,.3f} | "
            "{grid_import_kwh:,.3f} | {rolling_min_bev_soc_percent:.3f}% "
            "({rolling_min_bev_soc_time}) | "
            "{certified_mip_gap_percent:.3f}% | "
            "{wall_time_seconds:,.1f} s |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Observed incumbent response",
            "",
        ]
    )
    transitions = list(report.get("observed_dispatch_transition_intervals") or [])
    if transitions:
        for transition in transitions:
            lines.append(
                "- Between {lower_scale:.1f} and {upper_scale:.1f}, the "
                "feasible incumbent changed from {lower_bev_trip_count} to "
                "{upper_bev_trip_count} BEV trips.".format(**transition)
            )
    else:
        lines.append("- No adjacent feasible incumbent changed BEV trip count.")
    lines.extend(
        [
            "",
            "The BEV-trip count is nonincreasing across the sampled demand "
            f"levels: `{str(bool(report.get('observed_bev_trip_count_nonincreasing'))).lower()}`. "
            "This is an observed incumbent pattern, not a proof of monotonic "
            "optimal solutions.",
            "",
            f"Source re-audit manifest SHA-256: `{report.get('source_execution_payload_sha256')}`",
            f"Reporting snapshot SHA-256: `{report.get('payload_sha256')}`",
            "",
        ]
    )
    return "\n".join(lines)


def csv_columns() -> Sequence[str]:
    return (
        "case_id",
        "trip_energy_scale",
        "solver_status",
        "mip_gap_target_met",
        "certified_mip_gap_percent",
        "solve_time_seconds",
        "wall_time_seconds",
        "trip_count_served",
        "trip_count_unserved",
        "vehicle_count_used",
        "used_bev_count",
        "used_ice_count",
        "bev_trip_count",
        "ice_trip_count",
        "total_cost_jpy",
        "cost_delta_vs_1_0_jpy",
        "cost_delta_vs_1_0_percent",
        "total_co2_kg",
        "co2_delta_vs_1_0_kg",
        "grid_import_kwh",
        "grid_delta_vs_1_0_kwh",
        "pv_generated_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "bess_to_bus_kwh",
        "rolling_min_bev_soc_kwh",
        "rolling_min_bev_soc_percent",
        "rolling_min_bev_soc_margin_percent",
        "rolling_min_bev_soc_vehicle_id",
        "rolling_min_bev_soc_time",
        "case_accepted",
        "failed_checks",
        "prepared_input_id",
        "job_id",
        "source_run_dir",
    )


def _validate_case(outcome: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    _record(
        failures,
        "family_is_trip_energy_sensitivity",
        outcome.get("family") == "trip_energy_sensitivity",
    )
    checks = outcome.get("checks")
    _record(failures, "checks_mapping_present", isinstance(checks, Mapping))
    if isinstance(checks, Mapping):
        for check_name in REQUIRED_TRUE_CHECKS:
            _record(failures, check_name, checks.get(check_name) is True)
    _record(
        failures,
        "git_sha_unchanged",
        outcome.get("git_sha_unchanged") is True,
    )
    for field in (
        "rolling_execution_minutes_submitted",
        "rolling_execution_minutes_requested",
        "rolling_execution_minutes_effective",
    ):
        _record(failures, f"{field}_is_60", outcome.get(field) == 60)
    _record(
        failures,
        "all_264_trips_served",
        _number(outcome.get("trip_count_served")) == 264.0
        and _number(outcome.get("trip_count_unserved")) == 0.0,
    )
    _record(
        failures,
        "powertrain_trip_counts_reconcile",
        _number(outcome.get("bev_trip_count"))
        + _number(outcome.get("ice_trip_count"))
        == 264.0,
    )
    _record(
        failures,
        "stable_control_fingerprint_recorded",
        bool(outcome.get("stable_control_fingerprint")),
    )
    _record(
        failures,
        "prepared_trip_hash_recorded",
        bool(outcome.get("prepared_trip_input_sha256")),
    )
    soc = outcome.get("rolling_soc_evidence")
    _record(failures, "rolling_soc_mapping_present", isinstance(soc, Mapping))
    if isinstance(soc, Mapping):
        active_bev_count = int(_number(soc.get("active_bev_count")))
        vehicle_count = int(_number(outcome.get("vehicle_count_used")))
        _record(
            failures,
            "rolling_soc_sources_verified",
            soc.get("source_artifacts_verified") is True,
        )
        _record(failures, "rolling_soc_applicable", soc.get("applicable") is True)
        _record(failures, "active_bev_count_positive", active_bev_count > 0)
        _record(
            failures,
            "active_bev_count_within_used_fleet",
            active_bev_count <= vehicle_count,
        )
        _record(
            failures,
            "rolling_soc_has_25_timepoints",
            int(_number(soc.get("timepoint_count"))) == 25,
        )
        _record(
            failures,
            "rolling_soc_sample_count_reconciles",
            int(_number(soc.get("sample_count")))
            == active_bev_count * int(_number(soc.get("timepoint_count"))),
        )
        _record(
            failures,
            "rolling_min_soc_above_vehicle_limit",
            _number(outcome.get("rolling_min_bev_soc_margin_percent"))
            >= -1.0e-6,
        )
        _record(
            failures,
            "rolling_min_soc_matches_evidence",
            _numbers_equal(
                outcome.get("rolling_min_bev_soc_percent"),
                soc.get("minimum_soc_percent"),
            )
            and _numbers_equal(
                outcome.get("rolling_min_bev_soc_margin_percent"),
                soc.get("minimum_margin_above_vehicle_limit_percent"),
            ),
        )
        _record(
            failures,
            "rolling_soc_source_bundle_hash_recorded",
            bool(soc.get("source_bundle_sha256")),
        )
    declared_failures = set(outcome.get("failed_checks") or [])
    case_accepted = outcome.get("case_accepted") is True
    gap_met = outcome.get("mip_gap_target_met") is True
    _record(failures, "acceptance_matches_gap_gate", case_accepted == gap_met)
    _record(
        failures,
        "only_mip_gap_may_block_reporting",
        not declared_failures
        if case_accepted
        else declared_failures == {"mip_gap_target_met"},
    )
    return failures


def _reporting_row(
    outcome: Mapping[str, Any], *, scale: float
) -> dict[str, Any]:
    rolling_soc = dict(outcome.get("rolling_soc_evidence") or {})
    used_bev_count = int(_number(rolling_soc.get("active_bev_count")))
    vehicle_count = int(_number(outcome.get("vehicle_count_used")))
    return {
        "case_id": str(outcome.get("case_id") or ""),
        "trip_energy_scale": scale,
        "solver_status": str(outcome.get("solver_status") or ""),
        "mip_gap_target_met": outcome.get("mip_gap_target_met") is True,
        "certified_mip_gap_percent": _number(
            outcome.get("certified_mip_gap_percent")
        ),
        "solve_time_seconds": _number(outcome.get("solve_time_seconds")),
        "wall_time_seconds": _number(outcome.get("wall_time_seconds")),
        "trip_count_served": int(_number(outcome.get("trip_count_served"))),
        "trip_count_unserved": int(
            _number(outcome.get("trip_count_unserved"))
        ),
        "vehicle_count_used": vehicle_count,
        "used_bev_count": used_bev_count,
        "used_ice_count": vehicle_count - used_bev_count,
        "bev_trip_count": int(_number(outcome.get("bev_trip_count"))),
        "ice_trip_count": int(_number(outcome.get("ice_trip_count"))),
        "total_cost_jpy": _number(outcome.get("total_cost_jpy")),
        "total_co2_kg": _number(outcome.get("total_co2_kg")),
        "grid_import_kwh": _number(outcome.get("grid_import_kwh")),
        "pv_generated_kwh": _number(outcome.get("pv_generated_kwh")),
        "pv_to_bus_kwh": _number(outcome.get("pv_to_bus_kwh")),
        "pv_to_bess_kwh": _number(outcome.get("pv_to_bess_kwh")),
        "bess_to_bus_kwh": _number(outcome.get("bess_to_bus_kwh")),
        "rolling_min_bev_soc_kwh": _number(
            outcome.get("rolling_min_bev_soc_kwh")
        ),
        "rolling_min_bev_soc_percent": _number(
            outcome.get("rolling_min_bev_soc_percent")
        ),
        "rolling_min_bev_soc_margin_percent": _number(
            outcome.get("rolling_min_bev_soc_margin_percent")
        ),
        "rolling_min_bev_soc_vehicle_id": str(
            outcome.get("rolling_min_bev_soc_vehicle_id") or ""
        ),
        "rolling_min_bev_soc_time": str(
            outcome.get("rolling_min_bev_soc_time") or ""
        ),
        "rolling_soc_source_bundle_sha256": str(
            rolling_soc.get("source_bundle_sha256") or ""
        ),
        "case_accepted": outcome.get("case_accepted") is True,
        "failed_checks": list(outcome.get("failed_checks") or []),
        "prepared_input_id": str(outcome.get("prepared_input_id") or ""),
        "job_id": str(outcome.get("job_id") or ""),
        "source_run_dir": str(outcome.get("source_run_dir") or ""),
    }


def _add_reference_deltas(
    rows: list[dict[str, Any]], *, reference: Mapping[str, Any]
) -> None:
    for row in rows:
        for metric, delta_name in (
            ("total_cost_jpy", "cost_delta_vs_1_0_jpy"),
            ("total_co2_kg", "co2_delta_vs_1_0_kg"),
            ("grid_import_kwh", "grid_delta_vs_1_0_kwh"),
            ("bev_trip_count", "bev_trip_delta_vs_1_0"),
            (
                "rolling_min_bev_soc_percent",
                "minimum_soc_delta_vs_1_0_percent_points",
            ),
        ):
            row[delta_name] = row[metric] - reference[metric]
        row["cost_delta_vs_1_0_percent"] = (
            100.0
            * row["cost_delta_vs_1_0_jpy"]
            / reference["total_cost_jpy"]
            if reference["total_cost_jpy"]
            else 0.0
        )


def _observed_dispatch_transitions(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "lower_case_id": left["case_id"],
            "upper_case_id": right["case_id"],
            "lower_scale": left["trip_energy_scale"],
            "upper_scale": right["trip_energy_scale"],
            "lower_bev_trip_count": left["bev_trip_count"],
            "upper_bev_trip_count": right["bev_trip_count"],
            "bev_trip_change": (
                right["bev_trip_count"] - left["bev_trip_count"]
            ),
            "evidence_label": "observed_gap_limited_feasible_incumbents",
        }
        for left, right in zip(rows, rows[1:])
        if left["bev_trip_count"] != right["bev_trip_count"]
    ]


def _record(failures: list[str], name: str, condition: bool) -> None:
    if not condition:
        failures.append(name)


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"expected finite numeric reporting value, got {value!r}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"expected finite numeric reporting value, got {value!r}")
    return number


def _numbers_equal(left: Any, right: Any) -> bool:
    try:
        return abs(_number(left) - _number(right)) <= 1.0e-9
    except (TypeError, ValueError):
        return False


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _canonical_hash(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
