"""Verify the fixed-input, 15-minute Phase 3 baseline artifact contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ZERO_COUNT_KEYS = (
    "unassigned_trip_count",
    "duplicate_trip_count",
    "vehicle_time_overlap_count",
    "infeasible_transition_count",
    "ev_soc_lower_violation_count",
    "ev_soc_upper_violation_count",
    "ev_soc_violation_count",
    "bess_soc_lower_violation_count",
    "bess_soc_upper_violation_count",
    "bess_soc_violation_count",
    "contract_power_violation_count",
    "charger_concurrency_violation_count",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def verify_run(run_dir: Path, *, expected_git_sha: str = "") -> dict[str, Any]:
    summary = _read_json(run_dir / "summary.json")
    solver_result = _read_json(run_dir / "solver_result.json")
    controlled_input = _read_json(
        run_dir / "controlled_model_validation_input.json"
    )
    manifest = _read_json(run_dir / "research_run_manifest.json")
    metadata = dict(solver_result.get("solver_metadata") or {})
    validation = dict(summary.get("validation_metrics") or {})
    pruning = dict(summary.get("arc_pruning_summary") or {})
    accounting = dict(summary.get("accounting_recalculation") or {})

    recorded_git_sha = str(summary.get("git_sha") or "")
    checks = {
        "expected_git_sha": bool(
            not expected_git_sha or recorded_git_sha == expected_git_sha
        ),
        "git_clean": summary.get("git_dirty") is False,
        "manifest_git_matches": (
            str(manifest.get("git_sha") or "") == recorded_git_sha
            and manifest.get("git_dirty") is False
        ),
        "fixed_prepared_input_hash": bool(
            summary.get("prepared_input_sha256")
            and summary.get("prepared_input_sha256")
            == controlled_input.get("prepared_input_sha256")
        ),
        "fifteen_minute_slots": (
            int(summary.get("time_step_min") or 0) == 15
            and int(controlled_input.get("slot_count") or 0) == 96
        ),
        "grid_only_assets": (
            summary.get("pv_enabled") is False
            and summary.get("bess_enabled") is False
            and summary.get("weather_operation_policy_enabled") is False
        ),
        "all_264_trips_served": (
            int(summary.get("trip_count_total") or 0) == 264
            and int(summary.get("trip_count_served") or 0) == 264
            and int(summary.get("trip_count_unserved") or 0) == 0
        ),
        "independently_feasible": (
            summary.get("feasible") is True
            and validation.get("all_required_validation_checks_passed") is True
            and all(int(validation.get(key) or 0) == 0 for key in ZERO_COUNT_KEYS)
        ),
        "stage1_has_incumbent": summary.get("stage1_has_feasible_incumbent")
        is True,
        "stage2_optimal": (
            str(summary.get("stage2_solver_status") or "").lower() == "optimal"
            and summary.get("stage2_has_feasible_incumbent") is True
        ),
        "no_fallback": metadata.get("fallback_applied") is False,
        "no_postsolve_repair": all(
            metadata.get(key) is False
            for key in (
                "postsolve_assignment_rebuilt",
                "postsolve_charging_recomputed",
                "postsolve_soc_repair_applied",
                "postsolve_opportunistic_topup_applied",
                "postsolve_modified_solution",
            )
        ),
        "full_successor_network": (
            pruning.get("successor_pruning_enabled") is False
            and int(pruning.get("pruned_arc_count") or 0) == 0
            and metadata.get("supports_exact_milp") is True
        ),
        "accounting_recalculation": accounting.get("passed") is True
        and float(accounting.get("max_abs_residual_jpy") or 0.0) <= float(
            accounting.get("tolerance_jpy") or 0.0
        ),
        "research_feasibility_accepted": (
            summary.get("research_run_accepted") is True
            and summary.get("research_feasibility_eligible") is True
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "research_phase3_baseline_verification_v1",
        "run_dir": str(run_dir.resolve()),
        "git_sha": recorded_git_sha,
        "prepared_input_id": summary.get("prepared_input_id"),
        "prepared_input_sha256": summary.get("prepared_input_sha256"),
        "experiment_hash": summary.get("experiment_hash"),
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "stage1_solver_status": summary.get("stage1_solver_status"),
        "stage1_mip_gap_ratio": summary.get("stage1_mip_gap_ratio"),
        "stage2_solver_status": summary.get("stage2_solver_status"),
        "accounting_total_cost_jpy": summary.get("accounting_total_cost_jpy"),
        "accounting_recalculation": accounting,
        "validation_metrics": validation,
        "arc_pruning_summary": pruning,
        "limitation": (
            "Phase 3 proves a validated feasible two-stage schedule. Its "
            "Stage 1 and Stage 2 objectives are not a single global "
            "accounting-cost objective."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-git-sha", default="")
    args = parser.parse_args()

    report = verify_run(
        args.run_dir,
        expected_git_sha=str(args.expected_git_sha or "").strip(),
    )
    output_path = args.run_dir / "formal_baseline_verification.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
