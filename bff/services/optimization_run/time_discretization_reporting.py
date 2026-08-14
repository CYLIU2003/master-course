"""Build fail-closed reporting data for the 60/30/15-minute tranche."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from bff.services.optimization_run.sensitivity_execution_contract import (
    is_supported_sensitivity_execution_schema,
)


REPORTING_SCHEMA_VERSION = "time_discretization_reporting_v1"
REQUIRED_CASE_TIMESTEPS = {
    "TIME_60": 60,
    "TIME_30": 30,
    "TIME_15": 15,
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
    "declared_case_parameter_effective",
    "declared_common_controls_effective",
    "submitted_request_provenance_matches",
)


def build_time_discretization_report(
    source_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one completed tranche and return its reporting snapshot."""

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
        is_supported_sensitivity_execution_schema(
            source_manifest.get("schema_version")
        ),
    )
    expected_ids = set(REQUIRED_CASE_TIMESTEPS)
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
    _record(failed_checks, "source_git_sha_recorded", bool(source_git_sha))

    fingerprints: set[str] = set()
    rows: list[dict[str, Any]] = []
    for case_id, timestep in REQUIRED_CASE_TIMESTEPS.items():
        outcome = by_id.get(case_id)
        if outcome is None:
            continue
        case_failures = _validate_case(outcome, timestep=timestep)
        failed_checks.extend(f"{case_id}:{name}" for name in case_failures)
        fingerprints.add(str(outcome.get("stable_control_fingerprint") or ""))
        rows.append(_reporting_row(outcome))

    _record(
        failed_checks,
        "single_nonempty_stable_control_fingerprint",
        len(fingerprints) == 1 and "" not in fingerprints,
    )
    rows.sort(key=lambda row: int(row["timestep_min"]), reverse=True)
    if any(row["timestep_min"] == 60 for row in rows):
        _add_reference_deltas(rows)

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
        else "READY_FOR_TIME_DISCRETIZATION_CONVERGENCE"
        if all_gap_targets_met
        else "DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED"
        if only_gap_gate_failed
        else "BLOCKED_UNCLASSIFIED_CASE_FAILURE"
    )
    payload: dict[str, Any] = {
        "schema_version": REPORTING_SCHEMA_VERSION,
        "status": status,
        "reporting_eligible": not failed_checks and bool(rows),
        "research_conclusion_eligible": all_gap_targets_met
        and not failed_checks,
        "discretization_convergence_certified": all_gap_targets_met
        and not failed_checks,
        "claim_scope": (
            "Physical and accounting comparison of feasible incumbents only; "
            "the 1% MIP-gap target was not established."
            if not all_gap_targets_met and not failed_checks
            else "Certified 60/30/15-minute time-discretization comparison."
            if all_gap_targets_met and not failed_checks
            else "No research claim is permitted because source evidence failed."
        ),
        "failed_checks": failed_checks,
        "source_execution_payload_sha256": source_payload_hash,
        "source_run_git_sha": source_git_sha,
        "stable_control_fingerprint": (
            next(iter(fingerprints))
            if len(fingerprints) == 1 and "" not in fingerprints
            else None
        ),
        "rolling_execution_minutes": 60,
        "observed_dispatch_stable": bool(rows)
        and len(
            {
                (
                    row["vehicle_count_used"],
                    row["bev_trip_count"],
                    row["ice_trip_count"],
                )
                for row in rows
            }
        )
        == 1,
        "rows": rows,
    }
    payload["payload_sha256"] = _canonical_hash(payload)
    return payload


def render_time_discretization_markdown(
    report: Mapping[str, Any],
) -> str:
    """Render one concise, thesis-facing diagnostic table."""

    rows = list(report.get("rows") or [])
    gap_certified = report.get("discretization_convergence_certified") is True
    evidence_notice = (
        "> All three cases met the predeclared MIP-gap target. The table may "
        "be used for the declared time-discretization comparison."
        if gap_certified
        else "> These are physically valid, accounting-eligible feasible "
        "incumbents. The predeclared 1% MIP-gap target was not met, so this "
        "tranche does not certify discretization convergence or global "
        "optimality."
    )
    lines = [
        "# Time-discretization sensitivity (low-PV case)",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source execution SHA: `{report.get('source_run_git_sha')}`",
        "- Day-ahead internal time step: 60 / 30 / 15 minutes",
        "- Rolling execution interval: 60 minutes for every case",
        f"- Dispatch stable across cases: `{str(bool(report.get('observed_dispatch_stable'))).lower()}`",
        "",
        evidence_notice,
        "",
        "| Internal step | Cost (JPY) | Delta vs 60 (JPY) | Grid (kWh) | CO2 (kg) | BEV/ICE trips | Certified gap | Wall time |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {timestep_min} min | {total_cost_jpy:,.2f} | "
            "{cost_delta_vs_60_jpy:+,.2f} | {grid_import_kwh:,.3f} | "
            "{total_co2_kg:,.3f} | {bev_trip_count}/{ice_trip_count} | "
            "{certified_mip_gap_percent:.3f}% | {wall_time_seconds:,.1f} s |".format(
                **row
            )
        )
    dispatch_text = ""
    if rows and report.get("observed_dispatch_stable") is True:
        first = rows[0]
        dispatch_text = (
            f"The cases retained the same {first['vehicle_count_used']}-bus, "
            f"{first['bev_trip_count']}-BEV-trip / "
            f"{first['ice_trip_count']}-ICE-trip dispatch. "
        )
    interpretation = (
        dispatch_text
        + "The finer models slightly changed executed grid energy, cost, and "
        "CO2. The predeclared gap criterion was met, so the declared "
        "discretization comparison is certified."
        if gap_certified
        else dispatch_text
        + "The finer models slightly changed executed grid energy, cost, and "
        "CO2. Because every solve stopped above the predeclared gap target, "
        "those differences cannot yet establish a converged optimum."
    )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            interpretation,
            "",
            f"Source manifest SHA-256: `{report.get('source_execution_payload_sha256')}`",
            f"Reporting snapshot SHA-256: `{report.get('payload_sha256')}`",
            "",
        ]
    )
    return "\n".join(lines)


def csv_columns() -> Sequence[str]:
    return (
        "case_id",
        "timestep_min",
        "rolling_execution_minutes",
        "solver_status",
        "mip_gap_target_met",
        "certified_mip_gap_percent",
        "solve_time_seconds",
        "wall_time_seconds",
        "trip_count_served",
        "trip_count_unserved",
        "vehicle_count_used",
        "bev_trip_count",
        "ice_trip_count",
        "total_cost_jpy",
        "cost_delta_vs_60_jpy",
        "cost_delta_vs_60_percent",
        "total_co2_kg",
        "co2_delta_vs_60_kg",
        "grid_import_kwh",
        "grid_delta_vs_60_kwh",
        "pv_generated_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "bess_to_bus_kwh",
        "case_accepted",
        "failed_checks",
        "prepared_input_id",
        "job_id",
        "source_run_dir",
    )


def _validate_case(
    outcome: Mapping[str, Any], *, timestep: int
) -> list[str]:
    failures: list[str] = []
    _record(
        failures,
        "family_is_time_discretization",
        outcome.get("family") == "time_discretization",
    )
    _record(
        failures,
        "timestep_matches_case",
        outcome.get("timestep_min") == timestep,
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
        "all_trips_served",
        _number(outcome.get("trip_count_unserved")) == 0.0
        and _number(outcome.get("trip_count_served")) > 0.0,
    )
    _record(
        failures,
        "stable_control_fingerprint_recorded",
        bool(outcome.get("stable_control_fingerprint")),
    )
    declared_failures = set(outcome.get("failed_checks") or [])
    case_accepted = outcome.get("case_accepted") is True
    gap_met = outcome.get("mip_gap_target_met") is True
    _record(
        failures,
        "acceptance_matches_gap_gate",
        case_accepted == gap_met,
    )
    _record(
        failures,
        "only_mip_gap_may_block_reporting",
        not declared_failures
        if case_accepted
        else declared_failures == {"mip_gap_target_met"},
    )
    return failures


def _reporting_row(outcome: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(outcome.get("case_id") or ""),
        "timestep_min": int(_number(outcome.get("timestep_min"))),
        "rolling_execution_minutes": int(
            _number(outcome.get("rolling_execution_minutes_effective"))
        ),
        "solver_status": str(outcome.get("solver_status") or ""),
        "mip_gap_target_met": outcome.get("mip_gap_target_met") is True,
        "certified_mip_gap_percent": _number(
            outcome.get("certified_mip_gap_percent")
        ),
        "solve_time_seconds": _number(outcome.get("solve_time_seconds")),
        "wall_time_seconds": _number(outcome.get("wall_time_seconds")),
        "trip_count_served": int(_number(outcome.get("trip_count_served"))),
        "trip_count_unserved": int(_number(outcome.get("trip_count_unserved"))),
        "vehicle_count_used": int(_number(outcome.get("vehicle_count_used"))),
        "bev_trip_count": int(_number(outcome.get("bev_trip_count"))),
        "ice_trip_count": int(_number(outcome.get("ice_trip_count"))),
        "total_cost_jpy": _number(outcome.get("total_cost_jpy")),
        "total_co2_kg": _number(outcome.get("total_co2_kg")),
        "grid_import_kwh": _number(outcome.get("grid_import_kwh")),
        "pv_generated_kwh": _number(outcome.get("pv_generated_kwh")),
        "pv_to_bus_kwh": _number(outcome.get("pv_to_bus_kwh")),
        "pv_to_bess_kwh": _number(outcome.get("pv_to_bess_kwh")),
        "bess_to_bus_kwh": _number(outcome.get("bess_to_bus_kwh")),
        "case_accepted": outcome.get("case_accepted") is True,
        "failed_checks": list(outcome.get("failed_checks") or []),
        "prepared_input_id": str(outcome.get("prepared_input_id") or ""),
        "job_id": str(outcome.get("job_id") or ""),
        "source_run_dir": str(outcome.get("source_run_dir") or ""),
    }


def _add_reference_deltas(rows: list[dict[str, Any]]) -> None:
    reference = next(row for row in rows if row["timestep_min"] == 60)
    for row in rows:
        for metric, delta_name in (
            ("total_cost_jpy", "cost_delta_vs_60_jpy"),
            ("total_co2_kg", "co2_delta_vs_60_kg"),
            ("grid_import_kwh", "grid_delta_vs_60_kwh"),
        ):
            row[delta_name] = row[metric] - reference[metric]
        row["cost_delta_vs_60_percent"] = (
            100.0 * row["cost_delta_vs_60_jpy"] / reference["total_cost_jpy"]
            if reference["total_cost_jpy"]
            else 0.0
        )


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
