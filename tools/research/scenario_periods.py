"""Manage a scenario's independent periods without AI or ODPT acquisition."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.scenario_periods import PeriodEdit, bind_campaign, get_periods, save_periods


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("show", "save", "bind", "export"))
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--input", type=Path, help="PeriodEdit JSON with the current revision")
    parser.add_argument("--period")
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "save":
        if not args.input:
            parser.error("save requires --input")
        result = save_periods(args.scenario, PeriodEdit.model_validate_json(args.input.read_text(encoding="utf-8-sig")))
    elif args.command == "bind":
        if not args.period or not args.campaign:
            parser.error("bind requires --period and --campaign")
        result = bind_campaign(args.scenario, args.period, args.campaign)
    else:
        result = get_periods(args.scenario)
        if args.command == "export":
            if not args.output:
                parser.error("export requires --output")
            # The current campaign driver supports complete seven-day cases.
            # Other lengths remain plans until a matching validated runner exists.
            if not result["periods"] or any(p["days"] != 7 for p in result["periods"]):
                parser.error("weekly_campaign requires nonempty seven-day periods")
            result = {"schema_version": "scenario_week_plan_v1", "scenario_id": args.scenario,
                      "revision": result["revision"], "weeks": [p["start"] for p in result["periods"]]}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
