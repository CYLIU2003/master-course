"""Check calendar adjacency and BESS inventory transfer between solved weeks.

This checks saved boundaries only. A long-term operations claim also needs the
second week solved with the first week's terminal inventory as its input.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import math
from pathlib import Path
import zipfile


def assess(weeks: list[dict]) -> dict:
    rows = sorted(weeks, key=lambda row: row["week"])
    errors: list[str] = []
    adjacent_pairs = 0
    transferred_pairs = 0
    for earlier, later in zip(rows, rows[1:]):
        earlier_start = date.fromisoformat(earlier["week"])
        later_start = date.fromisoformat(later["week"])
        if later_start != earlier_start + timedelta(days=7):
            errors.append(f"{earlier['week']} -> {later['week']}: calendar gap")
            continue
        adjacent_pairs += 1
        first = earlier["bess_terminal"]
        second = later["bess_terminal"]
        if not math.isclose(
            float(first["terminal_soc_kwh"]),
            float(second["initial_soc_kwh"]),
            rel_tol=0.0, abs_tol=1e-6,
        ):
            errors.append(f"{earlier['week']} -> {later['week']}: BESS inventory reset")
            continue
        transferred_pairs += 1
    return {
        "status": "BOUNDARIES_CONSISTENT" if len(rows) >= 2 and not errors else "CONTINUITY_NOT_ESTABLISHED",
        "week_count": len(rows),
        "adjacent_pair_count": adjacent_pairs,
        "matching_bess_transfer_pair_count": transferred_pairs,
        "boundaries_only": True,
        "requires_second_week_solved_from_transferred_inventory": True,
        "reasons": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="monthly_report.json or monthly_evidence_bundle.zip")
    args = parser.parse_args()
    if args.report.suffix.lower() == ".zip":
        with zipfile.ZipFile(args.report) as bundle:
            report = json.loads(bundle.read("monthly_report.json"))
    else:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    verdict = assess(report["weeks"])
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["status"] == "BOUNDARIES_CONSISTENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
