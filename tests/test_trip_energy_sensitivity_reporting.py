from __future__ import annotations

from hashlib import sha256
import json

from bff.services.optimization_run.trip_energy_sensitivity_reporting import (
    REQUIRED_CASE_SCALES,
    build_trip_energy_sensitivity_report,
    render_trip_energy_sensitivity_markdown,
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


def _outcome(
    case_id: str,
    scale: float,
    *,
    gap_met: bool = False,
) -> dict:
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
            "rolling_soc_evidence_verified",
            "declared_case_parameter_effective",
            "declared_common_controls_effective",
            "submitted_request_provenance_matches",
            "prepared_trip_structure_verified",
            "source_run_matches_original_frozen_git_sha",
        )
    }
    checks["mip_gap_target_met"] = gap_met
    bev_trips = 105 if scale == 0.8 else 91 if scale <= 1.0 else 77
    active_bevs = 22 if scale == 0.8 else 21 if scale <= 1.0 else 20
    return {
        "case_id": case_id,
        "family": "trip_energy_sensitivity",
        "case_accepted": gap_met,
        "checks": checks,
        "failed_checks": [] if gap_met else ["mip_gap_target_met"],
        "stable_control_fingerprint": "stable",
        "prepared_trip_input_sha256": "prepared-trips",
        "solver_status": "optimal" if gap_met else "time_limit",
        "mip_gap_target_met": gap_met,
        "certified_mip_gap_percent": 0.5 if gap_met else 6.0,
        "solve_time_seconds": 3600.0,
        "wall_time_seconds": 4800.0 + scale,
        "rolling_execution_minutes_submitted": 60,
        "rolling_execution_minutes_requested": 60,
        "rolling_execution_minutes_effective": 60,
        "trip_count_served": 264,
        "trip_count_unserved": 0,
        "vehicle_count_used": 32,
        "bev_trip_count": bev_trips,
        "ice_trip_count": 264 - bev_trips,
        "total_cost_jpy": 58_000.0 * scale,
        "total_co2_kg": 980.0 * scale,
        "grid_import_kwh": 125.0 * scale,
        "pv_generated_kwh": 996.2,
        "pv_to_bus_kwh": 300.0,
        "pv_to_bess_kwh": 696.2,
        "bess_to_bus_kwh": 620.0,
        "rolling_min_bev_soc_kwh": 80.0,
        "rolling_min_bev_soc_percent": 25.0,
        "rolling_min_bev_soc_margin_percent": 5.0,
        "rolling_min_bev_soc_vehicle_id": "bev-a",
        "rolling_min_bev_soc_time": "11:00",
        "rolling_soc_evidence": {
            "applicable": True,
            "source_artifacts_verified": True,
            "active_bev_count": active_bevs,
            "timepoint_count": 25,
            "sample_count": active_bevs * 25,
            "minimum_soc_percent": 25.0,
            "minimum_margin_above_vehicle_limit_percent": 5.0,
            "source_bundle_sha256": f"soc-{case_id}",
        },
        "prepared_input_id": f"prepared-{case_id}",
        "job_id": f"job-{case_id}",
        "source_run_dir": f"run-{case_id}",
        "git_sha_unchanged": True,
    }


def _manifest(*, gap_met: bool = False) -> dict:
    payload = {
        "schema_version": "thesis_sensitivity_execution_v2",
        "frozen_git_sha": "source-sha",
        "audit_builder_git_sha": "audit-sha",
        "source_execution_manifest_sha256": "original-manifest",
        "selected_case_ids": sorted(REQUIRED_CASE_SCALES),
        "completed_case_ids": sorted(REQUIRED_CASE_SCALES),
        "all_selected_cases_completed": True,
        "stable_nonvaried_controls_match": True,
        "outcomes": [
            _outcome(case_id, scale, gap_met=gap_met)
            for case_id, scale in REQUIRED_CASE_SCALES.items()
        ],
    }
    payload["payload_sha256"] = _hash(payload)
    return payload


def test_reports_gap_limited_energy_cases_as_diagnostic() -> None:
    report = build_trip_energy_sensitivity_report(_manifest())

    assert report["status"] == "DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED"
    assert report["reporting_eligible"] is True
    assert report["research_conclusion_eligible"] is False
    assert report["transition_boundary_certified"] is False
    assert report["failed_checks"] == []
    assert report["observed_bev_trip_count_nonincreasing"] is True
    assert [row["trip_energy_scale"] for row in report["rows"]] == [
        0.8,
        0.9,
        1.0,
        1.1,
        1.2,
    ]
    assert report["rows"][2]["cost_delta_vs_1_0_jpy"] == 0.0
    assert [
        (row["lower_scale"], row["upper_scale"])
        for row in report["observed_dispatch_transition_intervals"]
    ] == [(0.8, 0.9), (1.0, 1.1)]
    assert "do not certify" in render_trip_energy_sensitivity_markdown(report)


def test_blocks_tampered_source_manifest() -> None:
    manifest = _manifest()
    manifest["outcomes"][0]["total_cost_jpy"] = 1.0

    report = build_trip_energy_sensitivity_report(manifest)

    assert report["status"] == "BLOCKED_INVALID_SOURCE_EVIDENCE"
    assert report["reporting_eligible"] is False
    assert "source_manifest_payload_sha256_valid" in report["failed_checks"]


def test_blocks_non_gap_failure_and_soc_provenance_failure() -> None:
    manifest = _manifest()
    outcome = manifest["outcomes"][1]
    outcome["checks"]["rolling_soc_evidence_verified"] = False
    outcome["failed_checks"] = [
        "rolling_soc_evidence_verified",
        "mip_gap_target_met",
    ]
    unsigned = dict(manifest)
    unsigned.pop("payload_sha256")
    manifest["payload_sha256"] = _hash(unsigned)

    report = build_trip_energy_sensitivity_report(manifest)

    assert report["status"] == "BLOCKED_INVALID_SOURCE_EVIDENCE"
    assert "ENERGY_0.9:rolling_soc_evidence_verified" in report["failed_checks"]
    assert (
        "ENERGY_0.9:only_mip_gap_may_block_reporting"
        in report["failed_checks"]
    )


def test_certifies_only_when_all_gap_targets_met() -> None:
    report = build_trip_energy_sensitivity_report(_manifest(gap_met=True))

    assert report["status"] == "READY_FOR_TRIP_ENERGY_SENSITIVITY"
    assert report["research_conclusion_eligible"] is True
    assert report["transition_boundary_certified"] is True
    assert "may be used" in render_trip_energy_sensitivity_markdown(report)


def test_blocks_prepared_trip_hash_drift() -> None:
    manifest = _manifest()
    manifest["outcomes"][3]["prepared_trip_input_sha256"] = "drift"
    unsigned = dict(manifest)
    unsigned.pop("payload_sha256")
    manifest["payload_sha256"] = _hash(unsigned)

    report = build_trip_energy_sensitivity_report(manifest)

    assert report["status"] == "BLOCKED_INVALID_SOURCE_EVIDENCE"
    assert "single_nonempty_prepared_trip_hash" in report["failed_checks"]


def test_blocks_flat_minimum_soc_that_disagrees_with_evidence() -> None:
    manifest = _manifest()
    manifest["outcomes"][2]["rolling_min_bev_soc_percent"] = 21.0
    unsigned = dict(manifest)
    unsigned.pop("payload_sha256")
    manifest["payload_sha256"] = _hash(unsigned)

    report = build_trip_energy_sensitivity_report(manifest)

    assert report["status"] == "BLOCKED_INVALID_SOURCE_EVIDENCE"
    assert (
        "ENERGY_1.0:rolling_min_soc_matches_evidence"
        in report["failed_checks"]
    )
