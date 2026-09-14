"""Create a single version-bound observer after the frozen solver is launched."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))
from scripts.watch_monthly_campaign import validate_configuration, sha256, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--started", required=True)
    args = parser.parse_args()
    frozen = Path("C:/master-course-worktrees/shibu21-23-monthly-phase-search-20260915")
    expected_sha = "7c7c2334040d54722d2f1c354634269d35f8d1de"
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=frozen, text=True).strip()
    if source != expected_sha or subprocess.check_output(["git", "status", "--porcelain"], cwd=frozen):
        raise ValueError("New release source is not clean and fixed")
    output = BASE / "script_observer"
    if (output / "config.json").exists() or (BASE / "budget_rerun_launch.json").exists():
        raise ValueError("Deployment exists; inspect it instead of resetting identity")
    launch = {"status": "RUNNING", "frozen_root": str(frozen), "source_git_sha": source,
              "campaign_relative_path": "output/monthly_phase_search_campaign_20260915",
              "config": "config/shibu21_23_monthly_phase_search_20260915.json",
              "actual_solver_pid": args.pid, "started_at_utc": args.started,
              "verified_input_files": 47, "scenario_metadata_refs_relocated": 11,
              "stage2_search_policy": {"MIPFocus": 1, "day_ahead_Method": 1, "rolling_Method": 0},
              "previous_weekly_results_not_reused": True, "independently_audited_weeks": 0,
              "input_import": str(frozen / "output/monthly_input_import.json"),
              "validation": {"full_passed": 2343, "preexisting_ppt_failures": 2,
                             "new_failures": 0, "frozen_focused_passed": 116},
              "research_acceptance": "BLOCKED", "email_sent": False}
    write_json(BASE / "budget_rerun_launch.json", launch)
    old_base = ROOT / "output/monthly_fair_weeks_20260914"
    config = json.loads((old_base / "script_observer/config.json").read_text(encoding="utf-8"))
    config.update(deployment="phase_search", output=str(output), campaign=str(frozen / launch["campaign_relative_path"]),
                  audit=str(BASE / "monthly_budget_independent_audit.json"),
                  report_stem=str(ROOT / "docs/notes/SHIBU21_23_MONTHLY_PHASE_SEARCH_RESULTS_20260915"),
                  figure_stem=str(ROOT / "docs/notes/figures/shibu21_23_monthly_phase_search_20260915"),
                  source_git_sha=source, solver_pid=args.pid, solver_started_at_utc=args.started,
                  audit_script=str(BASE / "audit_budget_week.py"),
                  checkpoint_script=str(BASE / "update_monthly_checkpoint.py"),
                  email_subject=f"月別12週・季節比較の整理完了 [MC2025-{source[:8]}]")
    helpers = set(config["helper_hashes"])
    helpers.discard(str(old_base / "update_monthly_checkpoint.py"))
    helpers.update([str(BASE / "audit_budget_week.py"), str(BASE / "update_monthly_checkpoint.py")])
    config["helper_hashes"] = {filename: sha256(Path(filename)) for filename in sorted(helpers)}
    validate_configuration(config)
    write_json(BASE / "monthly_budget_independent_audit.json",
               {"expected_sha": source, "frozen_root": str(frozen),
                "campaign_output": launch["campaign_relative_path"], "status": "RUNNING_CAMPAIGN", "weeks": {}})
    write_json(output / "config.json", config)
    print(json.dumps({"source_git_sha": source, "solver_pid": args.pid, "observer_config": str(output / "config.json")}))


if __name__ == "__main__":
    main()
