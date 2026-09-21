"""Sequential fresh diagnostics of two explicitly declared conditions."""
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
from scripts.benchmarks.seasonal_design_contract import require_execution_enabled

PROFILES = ("bounded_presolve_barrier", "bounded_presolve_norel")
MEMORY_BOUNDED_PROFILES = ("bounded_presolve_dual", "bounded_presolve_norel")
SUPPORT_PROFILES = ("dense_slot_support", "sparse_slot_support")
BESS_RANGE_PROFILES = ("baseline_20_80", "expanded_10_90")


def profile_design(design: dict, profiles: tuple, profile: str) -> dict:
    """Apply one declared treatment without changing the common solve budget."""
    if profiles == BESS_RANGE_PROFILES:
        return {**design, 'bess_operating_range_profile':profile,
            'bess_operating_range_basis':'unverified_hardware_sensitivity',
            'bess_terminal_soc_floor_percent':10.0 if profile == 'expanded_10_90' else 20.0}
    if profiles == SUPPORT_PROFILES:
        return {**design, 'stage1_gurobi_search_profile':'bounded_presolve_dual',
                'stage1_sparse_charge_window_support':profile == 'sparse_slot_support'}
    return {**design, 'stage1_gurobi_search_profile':profile}


def run(design_path: Path, output: Path) -> dict:
    design = json.loads(design_path.read_text(encoding="utf-8"))
    require_execution_enabled(design)
    profiles = tuple(design.get("diagnostic_profiles", ()))
    if profiles not in (PROFILES, MEMORY_BOUNDED_PROFILES, SUPPORT_PROFILES, BESS_RANGE_PROFILES):
        raise ValueError("Run exactly one supported pair of predeclared conditions, once each")
    before = git_state()
    if not before.get("sha") or before["status_porcelain"]:
        raise RuntimeError("Root-search diagnosis requires a clean frozen commit")
    output = output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    state = {"status": "RUNNING", "source_state": before, "profiles": list(profiles),
             "monthly_complete": False, "email_sent": False}
    write_json(output / "state.json", state)
    try:
        for profile in profiles:
            if git_state() != before:
                raise RuntimeError("Source state changed between root strategies")
            case = output / profile
            case.mkdir()
            case_design = profile_design(design, profiles, profile)
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
                failure_path = case / "run/failure.json"
                if failure_path.is_file():
                    failure = json.loads(failure_path.read_text(encoding="utf-8"))
                    state["failed_profile"] = {
                        "profile": profile, "failure_path": str(failure_path),
                        "failure_sha256": hashlib.sha256(failure_path.read_bytes()).hexdigest(),
                        "error": failure.get("error"),
                        "campaign_outcome": failure.get("campaign_outcome"),
                    }
                raise RuntimeError(f"{profile} failed; inspect its failure.json and logs; no automatic retry")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            results.append({"profile": profile, "summary_path": str(summary_path),
                "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                "physical_accepted": summary["physical_accepted"], "quality": summary["quality"],
                "daily_path_cover_bounds": summary["daily_path_cover_bounds"],
                "native_memory": summary.get("native_memory"),
                "stage1_search_controls": summary.get("stage1_search_controls"),
                "gurobi_threads": summary.get("gurobi_threads"),
                "charge_window_support": summary.get("charge_window_support"),
                "stage1_model_size": summary.get("stage1_model_size"),
                "bess_operating_range_profile": case_design.get("bess_operating_range_profile", "baseline_20_80"),
                "bess_terminal_soc_floor_percent": case_design.get("bess_terminal_soc_floor_percent", 20.0),
                "bess_operating_range_basis": case_design.get("bess_operating_range_basis"),
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
