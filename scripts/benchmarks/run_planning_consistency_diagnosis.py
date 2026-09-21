"""Run one fresh May day-ahead under a frozen revision; never send email."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.run_exact_seasonal_campaign import run_campaign
from scripts.benchmarks.run_shibu21_24_seasonal_diagnostic import git_state, write_json


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
        reasons = list(diagnostic.get("reasons") or case_summary.get("reasons") or [])
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
        metadata = native["metadata"]
        native_log_path = metadata.get("stage1_native_log_path")
        if design.get("stage1_native_log_enabled") is True:
            if not native_log_path or not Path(native_log_path).is_file():
                raise RuntimeError("Requested native Stage 1 log is missing")
            evidence.append(Path(native_log_path))
        summary = {"status": "DIAGNOSIS_COMPLETE", "source_state": after,
            "physical_accepted": progress["day_ahead_physical_accepted"],
            "quality": quality, "elapsed_seconds": progress["day_ahead_seconds"],
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
