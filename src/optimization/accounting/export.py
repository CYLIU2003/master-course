from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .schema import AccountingArtifacts


def _row_dict(row: Any) -> dict[str, Any]:
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError(f"Unsupported row type: {type(row)!r}")


def _write_csv(path: Path, rows: Sequence[Any]) -> None:
    import csv

    data = [_row_dict(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(data[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)


def export_accounting_outputs(output_dir: str | Path, artifacts: AccountingArtifacts) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    vehicle_csv = root / "vehicle_slot_ledger.csv"
    vehicle_json = root / "vehicle_slot_ledger.json"
    energy_csv = root / "energy_flow_ledger.csv"
    energy_json = root / "energy_flow_ledger.json"
    summary_json = root / "kpi_summary.json"

    vehicle_rows = [_row_dict(row) for row in artifacts.vehicle_slot_ledger]
    energy_rows = [_row_dict(row) for row in artifacts.energy_flow_ledger]

    _write_csv(vehicle_csv, vehicle_rows)
    _write_csv(energy_csv, energy_rows)
    vehicle_json.write_text(json.dumps(vehicle_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    energy_json.write_text(json.dumps(energy_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_json.write_text(json.dumps(artifacts.summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "vehicle_slot_ledger_csv": str(vehicle_csv),
        "vehicle_slot_ledger_json": str(vehicle_json),
        "energy_flow_ledger_csv": str(energy_csv),
        "energy_flow_ledger_json": str(energy_json),
        "kpi_summary_json": str(summary_json),
    }

