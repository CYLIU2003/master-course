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


_MISSING_LEDGER_FILE_MARKER = "__MISSING_LEDGER_FILE__"


def _resolve_ledger_path(scenario_dir: Path, filename: str) -> Path:
    direct = scenario_dir / filename
    if direct.exists():
        return direct
    graph = scenario_dir / "graph" / filename
    if graph.exists():
        return graph
    return scenario_dir / filename


def _read_required_csv(scenario_dir: Path, filename: str, strict: bool) -> list[dict[str, Any]]:
    path = _resolve_ledger_path(scenario_dir, filename)
    if not path.exists():
        if strict:
            return [{_MISSING_LEDGER_FILE_MARKER: filename}]
        return []
    return _read_csv(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate canonical accounting outputs")
    parser.add_argument("--scenario-dir", required=True, help="Scenario output directory")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on validation failures")
    args = parser.parse_args()

    scenario_dir = Path(args.scenario_dir)
    vehicle_rows = _read_required_csv(scenario_dir, "vehicle_slot_ledger.csv", strict=args.strict)
    energy_rows = _read_required_csv(scenario_dir, "energy_flow_ledger.csv", strict=args.strict)
    graph_summary_path = scenario_dir / "graph" / "kpi_summary.json"
    root_summary_path = scenario_dir / "kpi_summary.json"
    summary_path = graph_summary_path if graph_summary_path.exists() else root_summary_path
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    issues: list[str] = []

    if vehicle_rows and vehicle_rows[0].get(_MISSING_LEDGER_FILE_MARKER):
        issues.append("MISSING required ledger file: vehicle_slot_ledger.csv")
    if energy_rows and energy_rows[0].get(_MISSING_LEDGER_FILE_MARKER):
        issues.append("MISSING required ledger file: energy_flow_ledger.csv")
    if args.strict and not summary_path.exists():
        issues.append("MISSING required summary file: kpi_summary.json (checked root and graph/)")

    operator_rows = [row for row in vehicle_rows + energy_rows if _MISSING_LEDGER_FILE_MARKER not in row]
    unknown_operator_count = sum(
        1 for row in operator_rows
        if str(row.get("operator_id") or "").strip() in ("", "UNKNOWN_OPERATOR")
    )
    if unknown_operator_count > 0:
        if args.strict:
            issues.append(f"UNKNOWN_OPERATOR or empty operator_id found in {unknown_operator_count} ledger rows")
        else:
            issues.append(f"WARNING: {unknown_operator_count} ledger rows have UNKNOWN_OPERATOR or empty operator_id")

    validation_issues = validate_accounting_artifacts(
        vehicle_rows=vehicle_rows if vehicle_rows and _MISSING_LEDGER_FILE_MARKER not in vehicle_rows[0] else [],
        energy_rows=energy_rows if energy_rows and _MISSING_LEDGER_FILE_MARKER not in energy_rows[0] else [],
        summary=summary,
        strict=args.strict,
    )
    issues.extend(str(issue) for issue in validation_issues)
    if issues:
        for issue in issues:
            print(f"[FAIL] {issue}")
        raise SystemExit(1 if args.strict else 0)

    print("[OK] accounting outputs are consistent")


if __name__ == "__main__":
    main()
