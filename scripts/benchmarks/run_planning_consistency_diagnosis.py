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
    try:
        run_campaign(design, output / "campaign", selected_week="2025-05-12")
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
        summary = {"status": "DIAGNOSIS_COMPLETE", "source_state": after,
            "physical_accepted": progress["day_ahead_physical_accepted"],
            "quality": quality, "elapsed_seconds": progress["day_ahead_seconds"],
            "evidence_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence},
            "monthly_complete": False, "email_sent": False,
            "research_acceptance": "BLOCKED_PENDING_FRESH_WEEKLY_EVALUATION_AND_INDEPENDENT_REVIEW"}
        write_json(output / "summary.json", summary)
        write_json(output / "state.json", summary)
        return summary
    except Exception as exc:
        failure = {"status": "DIAGNOSIS_FAILED", "error": f"{type(exc).__name__}: {exc}",
                   "source_state": git_state(), "monthly_complete": False, "email_sent": False}
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
