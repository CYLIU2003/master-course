"""Run one fresh May day-ahead under a frozen revision; never send email."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.run_exact_seasonal_campaign import run_campaign
from scripts.benchmarks.run_shibu21_24_seasonal_diagnostic import git_state, write_json
from scripts.benchmarks.optimization_quality import native_root_log_evidence


def assess_evidence(native: dict, quality: dict, physical: dict) -> dict:
    """Separate diagnostic completion, subproblem quality and research claims."""
    blockers = []
    physical_passed = physical.get("accepted") is True and not physical.get("violations")
    if not physical_passed or native.get("feasible") is not True or native.get("infeasibility_reasons"):
        blockers.append("PHYSICAL_OR_SOLVER_FEASIBILITY_NOT_ACCEPTED")
    for stage in ("stage1", "stage2"):
        evidence = quality.get(stage) or {}
        if evidence.get("target_met") is not True:
            blockers.append(f"{stage.upper()}_GAP_TARGET_NOT_MET")
        if evidence.get("solver_status") == "memory_limit":
            # A refused allocation need not appear as a measured peak above the limit.
            blockers.append(f"{stage.upper()}_MEMORY_LIMIT")
    breakdown = native.get("cost_breakdown") or {}
    total = breakdown.get("total_cost")
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total):
        total = None
        blockers.append("FINAL_FORECAST_TOTAL_COST_MISSING")
    blockers.extend([
        "INITIAL_INCUMBENT_FIXED_STAGE2_COST_NOT_RECORDED",
        "FRESH_WEEKLY_EXECUTION_NOT_EVALUATED",
        "INDEPENDENT_RESEARCH_REVIEW_PENDING",
    ])
    return {
        "diagnosis_completed_is_optimization_accepted": False,
        "subproblem_gap_targets_met": all(
            (quality.get(stage) or {}).get("target_met") is True for stage in ("stage1", "stage2")
        ),
        "blocking_reasons": blockers,
        "stage1_objective_improvement_jpy": quality.get("incumbent_improvement_jpy"),
        "initial_incumbent_fixed_stage2_total_cost_improvement_jpy": None,
        "final_forecast_total_cost_jpy": total,
        "final_forecast_cost_breakdown": breakdown,
        "cost_basis": "day_ahead_forecast_not_executed_rolling_accounting",
        "stage2_objective_is_total_cost": False,
        "integrated_global_optimum_proven": False,
    }


def run(design_path: Path, output: Path) -> dict:
    design = json.loads(design_path.read_text(encoding="utf-8"))
    if design.get("diagnostic_stop_after_day_ahead") is not True:
        raise ValueError("This diagnosis must stop before rolling/monthly execution")
    before = git_state()
    if not before.get("sha") or before["status_porcelain"]:
        raise RuntimeError("Diagnosis requires a clean frozen commit")
    output = output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "state.json", {"status": "RUNNING", "source_state": before,
                                       "email_sent": False, "monthly_complete": False})
    campaign_outcome = None
    try:
        campaign = run_campaign(design, output / "campaign", selected_week="2025-05-12")
        cases = campaign.get("summaries", [])
        case_summary = cases[0] if len(cases) == 1 else {}
        diagnostic = case_summary.get("diagnostic_result") or {}
        phase = case_summary.get("day_ahead") or {}
        reasons = list(dict.fromkeys(
            reason for source in (
                diagnostic.get("reasons"), diagnostic.get("day_ahead_reasons"),
                case_summary.get("reasons"), phase.get("reasons"),
            ) for reason in (source or [])
        ))
        if case_summary.get("error") and not reasons:
            reasons.append(case_summary["error"])
        campaign_outcome = {
            "status": campaign.get("status"), "case_status": case_summary.get("status"),
            "solve_attempted": diagnostic.get("solve_attempted"), "reasons": reasons,
            "summary_path": str(output / "campaign/summary.json"),
        }
        if (campaign.get("status") != "DAY_AHEAD_ONLY_CAMPAIGN_COMPLETE"
                or case_summary.get("status") != "DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE"):
            raise RuntimeError(
                f"Day-ahead campaign stopped: {campaign_outcome['case_status']}; "
                + "; ".join(reasons or [str(campaign.get("status"))])
            )
        case = output / "campaign/cases/2025-05-12/diagnostic/2025-05-12"
        progress = json.loads((case / "progress.json").read_text(encoding="utf-8"))
        after = git_state()
        if after != before:
            raise RuntimeError("Source changed during diagnosis")
        if progress.get("status") != "DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE":
            raise RuntimeError(f"Day-ahead diagnosis failed: {progress.get('status')}")
        quality = json.loads((case / "day_ahead_optimization_quality.json").read_text(encoding="utf-8"))
        evidence = [case / name for name in ("canonical_solver_result.json",
                    "day_ahead_physical_validation.json", "day_ahead_optimization_quality.json",
                    "input_audit.json")]
        native = json.loads((case / "canonical_solver_result.json").read_text(encoding="utf-8"))
        physical = json.loads((case / "day_ahead_physical_validation.json").read_text(encoding="utf-8"))
        assessment = assess_evidence(native, quality, physical)
        if "PHYSICAL_OR_SOLVER_FEASIBILITY_NOT_ACCEPTED" in assessment["blocking_reasons"]:
            raise RuntimeError("Saved physical/native evidence contradicts successful day-ahead progress")
        metadata = native["metadata"]
        native_log_path = metadata.get("stage1_native_log_path")
        root_log = None
        if design.get("stage1_native_log_enabled") is True:
            if not native_log_path or not Path(native_log_path).is_file():
                raise RuntimeError("Requested native Stage 1 log is missing")
            evidence.append(Path(native_log_path))
            root_log = native_root_log_evidence(Path(native_log_path).read_text(encoding="utf-8", errors="replace"))
        seed_comparison = None
        if design.get("stage1_seed_cost_diagnostic_enabled") is True:
            seed_path = case / "supplied_seed_cost/comparison.json"
            seed_comparison = json.loads(seed_path.read_text(encoding="utf-8"))
            evidence.extend([seed_path, case / "day_ahead_failure_diagnostics/stage1_supplied_seed.json"])
            if seed_comparison["status"] != "SEED_NOT_APPLIED":
                evidence.extend([case / "supplied_seed_cost/canonical_solver_result.json",
                                 case / "supplied_seed_cost/physical_validation.json"])
            if seed_comparison["status"] != "COMPARABLE_FORECAST_COSTS":
                assessment["blocking_reasons"].append("SUPPLIED_SEED_COST_COMPARISON_BLOCKED")
        summary = {"status": "DIAGNOSIS_COMPLETE", "source_state": after,
            "physical_accepted": progress["day_ahead_physical_accepted"],
            "quality": quality, "elapsed_seconds": progress["day_ahead_seconds"],
            "evidence_assessment": assessment,
            "native_root_log_evidence": root_log,
            "supplied_seed_cost_comparison": seed_comparison,
            "stage1_search_controls": metadata.get("stage1_gurobi_search_controls"),
            "gurobi_threads": metadata.get("gurobi_threads"),
            "native_memory": metadata.get("stage1_search_telemetry", {}).get("native_memory"),
            "charge_window_support": metadata.get("stage1_shared_charger_relaxation", {}).get("charge_window_support"),
            "stage1_model_size": {key: metadata.get(key) for key in (
                "stage1_model_variable_count", "stage1_model_constraint_count",
                "stage1_model_nonzero_coefficient_count", "stage1_model_binary_variable_count")},
            "daily_path_cover_bounds": metadata.get("stage1_vehicle_day_path_cover_lower_bounds"),
            "daily_overlap_bounds": metadata.get("stage1_vehicle_day_overlap_lower_bounds"),
            "stage1_native_log_path": native_log_path,
            "evidence_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence},
            "monthly_complete": False, "email_sent": False,
            "research_acceptance": "BLOCKED_PENDING_FRESH_WEEKLY_EVALUATION_AND_INDEPENDENT_REVIEW"}
        write_json(output / "summary.json", summary)
        write_json(output / "state.json", summary)
        return summary
    except Exception as exc:
        failure = {"status": "DIAGNOSIS_FAILED", "error": f"{type(exc).__name__}: {exc}",
                   "source_state": git_state(), "monthly_complete": False, "email_sent": False,
                   "campaign_outcome": campaign_outcome}
        write_json(output / "failure.json", failure)
        write_json(output / "state.json", failure)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.config, args.output)
    print(json.dumps({"status": result["status"], "physical_accepted": result["physical_accepted"],
                      "quality": result["quality"]}, ensure_ascii=False), flush=True)
