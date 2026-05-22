from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping

from .validators import validate_accounting_artifacts


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate canonical accounting outputs")
    parser.add_argument("--scenario-dir", required=True, help="Scenario output directory")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on validation failures")
    args = parser.parse_args()

    scenario_dir = Path(args.scenario_dir)
    vehicle_path = scenario_dir / "vehicle_slot_ledger.csv"
    energy_path = scenario_dir / "energy_flow_ledger.csv"
    summary_path = scenario_dir / "kpi_summary.json"
    if not summary_path.exists():
        summary_path = scenario_dir / "graph" / "kpi_summary.json"

    vehicle_rows = _read_csv(vehicle_path)
    energy_rows = _read_csv(energy_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    issues = validate_accounting_artifacts(vehicle_rows=vehicle_rows, energy_rows=energy_rows, summary=summary, strict=args.strict)
    if issues:
        for issue in issues:
            print(f"[FAIL] {issue}")
        raise SystemExit(1 if args.strict else 0)

    print("[OK] accounting outputs are consistent")


if __name__ == "__main__":
    main()
