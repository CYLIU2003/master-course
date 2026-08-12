"""Build an audited M0--M3 day-ahead comparison from two frontend runs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.services.optimization_run.thesis_ablation_comparison import (
    build_complete_day_ahead_ablation_comparison,
    comparison_csv_rows,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase1-run", type=Path, required=True)
    parser.add_argument("--phase4-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    payload = build_complete_day_ahead_ablation_comparison(
        phase1_run_dir=args.phase1_run,
        phase4_run_dir=args.phase4_run,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "day_ahead_method_comparison.json"
    csv_path = output_dir / "day_ahead_method_comparison.csv"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rows = comparison_csv_rows(payload)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json_path)
    print(csv_path)
    print(payload["status"])
    return 0 if payload["status"] == "READY_FOR_DAY_AHEAD_METHOD_COMPARISON" else 2


if __name__ == "__main__":
    raise SystemExit(main())
