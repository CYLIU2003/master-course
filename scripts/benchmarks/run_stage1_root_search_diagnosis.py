"""Sequential fresh diagnostics of two declared Stage 1 root strategies."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.run_shibu21_24_seasonal_diagnostic import git_state, write_json

PROFILES = ("bounded_presolve_barrier", "bounded_presolve_norel")


def run(design_path: Path, output: Path) -> dict:
    design = json.loads(design_path.read_text(encoding="utf-8"))
    if tuple(design.get("diagnostic_profiles", ())) != PROFILES:
        raise ValueError("Run exactly the two predeclared root strategies, once each")
    before = git_state()
    if not before.get("sha") or before["status_porcelain"]:
        raise RuntimeError("Root-search diagnosis requires a clean frozen commit")
    output = output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    state = {"status": "RUNNING", "source_state": before, "profiles": list(PROFILES),
             "monthly_complete": False, "email_sent": False}
    write_json(output / "state.json", state)
    try:
        for profile in PROFILES:
            if git_state() != before:
                raise RuntimeError("Source state changed between root strategies")
            case = output / profile
            case.mkdir()
            case_design = {**design, "stage1_gurobi_search_profile": profile}
            write_json(case / "design.json", case_design)
            state["active_profile"] = profile
            write_json(output / "state.json", state)
            command = [sys.executable, "-X", "utf8", "-u",
                "scripts/benchmarks/run_planning_consistency_diagnosis.py",
                "--config", str(case / "design.json"), "--output", str(case / "run")]
            with (case / "stdout.log").open("w", encoding="utf-8") as out, (case / "stderr.log").open("w", encoding="utf-8") as err:
                completed = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if git_state() != before:
                raise RuntimeError("Source state changed during root strategy")
            summary_path = case / "run/summary.json"
            if completed.returncode or not summary_path.is_file():
                raise RuntimeError(f"{profile} failed; inspect its failure.json and logs; no automatic retry")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            results.append({"profile": profile, "summary_path": str(summary_path),
                "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                "physical_accepted": summary["physical_accepted"], "quality": summary["quality"],
                "daily_path_cover_bounds": summary["daily_path_cover_bounds"],
                "stage1_native_log_path": summary["stage1_native_log_path"]})
            write_json(output / "partial_results.json", results)
        state.update(status="ROOT_SEARCH_DIAGNOSIS_COMPLETE", results=results,
                     research_acceptance="BLOCKED_PENDING_WEEKLY_EXECUTION_AND_INDEPENDENT_REVIEW")
        write_json(output / "summary.json", state)
        write_json(output / "state.json", state)
        return state
    except Exception as exc:
        state.update(status="ROOT_SEARCH_DIAGNOSIS_FAILED", results=results,
                     error=f"{type(exc).__name__}: {exc}")
        write_json(output / "failure.json", state)
        write_json(output / "state.json", state)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.output), ensure_ascii=False), flush=True)
