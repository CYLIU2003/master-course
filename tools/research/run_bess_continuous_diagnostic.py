"""Run a separate two-week BESS carryover diagnostic on the existing three-route scope.

Without --run this only prints the frozen design preview.  The run path uses
fresh Prepare for both weeks, then transfers accepted executed BESS inventory.
It is not a monthly-result rerun or evidence of a real depot import rating.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.run_exact_seasonal_campaign import (
    run_campaign,
    validate_carryover_weeks,
)

SOURCE_DESIGN = ROOT / "config/shibu21_23_monthly_auxiliary_proof_budget_20260922.json"
WEEKS = ("2025-01-20", "2025-01-27")


def diagnostic_design(source: dict) -> dict:
    design = deepcopy(source)
    design.update(
        evaluation_weeks=list(WEEKS),
        require_balanced_monthly_weeks=False,
        week_selection_rule="Two adjacent Monday-Sunday weeks fixed before solving; 2025-01-20 through 2025-02-02",
        research_status="DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
        design_status="TWO_WEEK_BESS_CARRYOVER_DIAGNOSTIC",
        continuity_scope="BESS executed terminal inventory only; BEV terminal remains return_to_initial",
        physical_import_limit_status="UNVERIFIED_PROVISIONAL_INPUT_NOT_REAL_EQUIPMENT_RATING",
    )
    if design.get("bess_terminal_soc_policy") != "minimum_only":
        raise ValueError("This diagnostic retains the declared minimum-only BESS policy")
    if design.get("diagnostic_stop_after_day_ahead") is True:
        raise ValueError("Carryover requires full rolling execution")
    validate_carryover_weeks(WEEKS, design)
    return design


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="Start the fresh two-week diagnostic from a clean commit")
    args = parser.parse_args()
    design = diagnostic_design(json.loads(SOURCE_DESIGN.read_text(encoding="utf-8")))
    if not args.run:
        print(json.dumps({
            "status": "PREVIEW_ONLY", "weeks": list(WEEKS),
            "bess_carryover": True, "new_output": str(args.output.resolve()),
            "research_status": design["research_status"],
            "physical_import_limit_status": design["physical_import_limit_status"],
        }, ensure_ascii=False))
        return 0
    result = run_campaign(design, args.output, carry_bess=True)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0 if result["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
