"""Bind the existing independent auditor to the fresh search-policy release."""
import importlib.util
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "monthly_saved_auditor", ROOT / "output/monthly_fair_weeks_20260914/audit_budget_week.py")
auditor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditor)


def configure() -> None:
    launch = json.loads((BASE / "budget_rerun_launch.json").read_text(encoding="utf-8"))
    auditor.ROOT = ROOT
    auditor.FROZEN_ROOT = Path(launch["frozen_root"])
    auditor.EXPECTED_SHA = launch["source_git_sha"]
    auditor.CAMPAIGN = auditor.FROZEN_ROOT / launch["campaign_relative_path"]
    auditor.FORECAST_DIR = auditor.FROZEN_ROOT / "output/monthly_fair_weeks_20260914/forecast_holdouts"
    auditor.MONTHLY_INPUT_IMPORT = auditor.FROZEN_ROOT / "output/monthly_input_import.json"
    auditor.EXPECTED_SEARCH_CONTROLS_BY_KIND = {
        "day_ahead": {"stage2_gurobi_mip_focus": 1, "stage2_gurobi_method": 1},
        "hourly": {"stage2_gurobi_mip_focus": 1, "stage2_gurobi_method": 0},
    }


if __name__ == "__main__":
    configure()
    raise SystemExit(auditor.main())
