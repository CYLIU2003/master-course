from __future__ import annotations

from hashlib import sha256
import json

from bff.services.optimization_run.time_discretization_reporting import (
    build_time_discretization_report,
    render_time_discretization_markdown,
)
from bff.services.optimization_run.sensitivity_execution_contract import (
    LATEST_SENSITIVITY_EXECUTION_SCHEMA_VERSION,
)


def _hash(payload: dict) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _outcome(case_id: str, timestep: int, *, gap_met: bool = False) -> dict:
    checks = {
        name: True
        for name in (
            "frontend_job_completed",
            "run_input_valid",
            "run_input_research_ready",
            "artifact_bundle_complete",
            "finalized_artifact_hashes_match",
            "explicit_phase4_integrated",
            "research_run_accepted",
            "mip_gap_target_met",
            "no_successor_pruning",
            "physical_schedule_valid",
            "rolling_accounting_eligible",
            "declared_case_parameter_effective",
            "declared_common_controls_effective",
            "submitted_request_provenance_matches",
        )
    }
    checks["mip_gap_target_met"] = gap_met
    return {
        "case_id": case_id,
        "family": "time_discretization",
        "case_accepted": gap_met,
        "checks": checks,
        "failed_checks": [] if gap_met else ["mip_gap_target_met"],
        "stable_control_fingerprint": "stable",
        "solver_status": "optimal" if gap_met else "time_limit",
        "mip_gap_target_met": gap_met,
        "certified_mip_gap_percent": 0.5 if gap_met else 6.0,
        "solve_time_seconds": 3600.0,
        "wall_time_seconds": 4800.0 + timestep,
        "timestep_min": timestep,
        "rolling_execution_minutes_submitted": 60,
        "rolling_execution_minutes_requested": 60,
        "rolling_execution_minutes_effective": 60,
        "trip_count_served": 264,
        "trip_count_unserved": 0,
        "vehicle_count_used": 32,
        "bev_trip_count": 91,
        "ice_trip_count": 173,
        "total_cost_jpy": 58_000.0 + timestep,
        "total_co2_kg": 980.0 + timestep / 10,
        "grid_import_kwh": 125.0 + timestep / 10,
        "pv_generated_kwh": 996.2,
        "pv_to_bus_kwh": 300.0,
        "pv_to_bess_kwh": 696.2,
        "bess_to_bus_kwh": 620.0,
        "prepared_input_id": f"prepared-{timestep}",
        "job_id": f"job-{timestep}",
        "source_run_dir": f"run-{timestep}",
        "git_sha_unchanged": True,
    }


def _manifest(
    *,
    gap_met: bool = False,
    schema_version: str = "thesis_sensitivity_execution_v2",
) -> dict:
    payload = {
        "schema_version": schema_version,
        "frozen_git_sha": "abc123",
        "selected_case_ids": ["TIME_15", "TIME_30", "TIME_60"],
        "completed_case_ids": ["TIME_15", "TIME_30", "TIME_60"],
        "all_selected_cases_completed": True,
        "stable_nonvaried_controls_match": True,
        "outcomes": [
            _outcome("TIME_60", 60, gap_met=gap_met),
            _outcome("TIME_30", 30, gap_met=gap_met),
            _outcome("TIME_15", 15, gap_met=gap_met),
        ],
    }
    payload["payload_sha256"] = _hash(payload)
    return payload


def test_reports_physically_valid_gap_limited_cases_as_diagnostic() -> None:
    report = build_time_discretization_report(_manifest())

    assert report["status"] == "DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED"
    assert report["reporting_eligible"] is True
    assert report["research_conclusion_eligible"] is False
    assert report["discretization_convergence_certified"] is False
    assert report["failed_checks"] == []
    assert report["observed_dispatch_stable"] is True
    assert [row["timestep_min"] for row in report["rows"]] == [60, 30, 15]
    assert report["rows"][0]["cost_delta_vs_60_jpy"] == 0.0
    assert report["rows"][2]["cost_delta_vs_60_jpy"] == -45.0
    assert "does not certify" in render_time_discretization_markdown(report)


def test_accepts_latest_powertrain_coefficient_execution_schema() -> None:
    report = build_time_discretization_report(
        _manifest(
            schema_version=LATEST_SENSITIVITY_EXECUTION_SCHEMA_VERSION
        )
    )

    assert report["failed_checks"] == []
    assert report["reporting_eligible"] is True


def test_blocks_tampered_source_manifest() -> None:
    manifest = _manifest()
    manifest["outcomes"][0]["total_cost_jpy"] = 1.0

    report = build_time_discretization_report(manifest)

    assert report["status"] == "BLOCKED_INVALID_SOURCE_EVIDENCE"
    assert report["reporting_eligible"] is False
    assert "source_manifest_payload_sha256_valid" in report["failed_checks"]


def test_blocks_non_gap_case_failure() -> None:
    manifest = _manifest()
    outcome = manifest["outcomes"][1]
    outcome["checks"]["physical_schedule_valid"] = False
    outcome["failed_checks"] = ["physical_schedule_valid", "mip_gap_target_met"]
    unsigned = dict(manifest)
    unsigned.pop("payload_sha256")
    manifest["payload_sha256"] = _hash(unsigned)

    report = build_time_discretization_report(manifest)

    assert report["status"] == "BLOCKED_INVALID_SOURCE_EVIDENCE"
    assert "TIME_30:physical_schedule_valid" in report["failed_checks"]
    assert "TIME_30:only_mip_gap_may_block_reporting" in report["failed_checks"]


def test_certifies_only_when_all_gap_targets_are_met() -> None:
    report = build_time_discretization_report(_manifest(gap_met=True))

    assert report["status"] == "READY_FOR_TIME_DISCRETIZATION_CONVERGENCE"
    assert report["research_conclusion_eligible"] is True
    assert report["discretization_convergence_certified"] is True
    assert "may be used" in render_time_discretization_markdown(report)


def test_missing_reference_case_is_blocked_without_reference_lookup_error() -> None:
    manifest = _manifest()
    manifest["outcomes"] = [
        outcome
        for outcome in manifest["outcomes"]
        if outcome["case_id"] != "TIME_60"
    ]
    manifest["completed_case_ids"] = ["TIME_15", "TIME_30"]
    unsigned = dict(manifest)
    unsigned.pop("payload_sha256")
    manifest["payload_sha256"] = _hash(unsigned)

    report = build_time_discretization_report(manifest)

    assert report["status"] == "BLOCKED_INVALID_SOURCE_EVIDENCE"
    assert "required_cases_completed" in report["failed_checks"]
    assert "one_outcome_per_required_case" in report["failed_checks"]
