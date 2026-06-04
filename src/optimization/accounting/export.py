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
    vehicle_energy_csv = root / "vehicle_energy_ledger.csv"
    vehicle_energy_json = root / "vehicle_energy_ledger.json"
    energy_csv = root / "energy_flow_ledger.csv"
    energy_json = root / "energy_flow_ledger.json"
    fuel_canonical_csv = root / "fuel_canonical_ledger.csv"
    fuel_timeseries_csv = root / "fuel_timeseries.csv"
    co2_timeseries_csv = root / "co2_timeseries.csv"
    initial_soc_csv = root / "initial_soc_ledger.csv"
    initial_soc_precheck_csv = root / "initial_soc_precheck.csv"
    validation_csv = root / "data_flow_validation.csv"
    summary_json = root / "kpi_summary.json"

    vehicle_rows = [_row_dict(row) for row in artifacts.vehicle_slot_ledger]
    vehicle_energy_rows = [_row_dict(row) for row in artifacts.vehicle_energy_ledger]
    energy_rows = [_row_dict(row) for row in artifacts.energy_flow_ledger]
    fuel_canonical_rows = [_row_dict(row) for row in artifacts.fuel_canonical_ledger]
    fuel_timeseries_rows = [_row_dict(row) for row in artifacts.fuel_timeseries]
    co2_timeseries_rows = [_row_dict(row) for row in artifacts.co2_timeseries]
    initial_soc_rows = [_row_dict(row) for row in artifacts.initial_soc_ledger]
    initial_soc_precheck_rows = [_row_dict(row) for row in artifacts.initial_soc_precheck]
    validation_rows = [_row_dict(row) for row in artifacts.data_flow_validation]

    _write_csv(vehicle_csv, vehicle_rows)
    _write_csv(vehicle_energy_csv, vehicle_energy_rows)
    _write_csv(energy_csv, energy_rows)
    _write_csv(fuel_canonical_csv, fuel_canonical_rows)
    _write_csv(fuel_timeseries_csv, fuel_timeseries_rows)
    _write_csv(co2_timeseries_csv, co2_timeseries_rows)
    _write_csv(initial_soc_csv, initial_soc_rows)
    _write_csv(initial_soc_precheck_csv, initial_soc_precheck_rows)
    _write_csv(validation_csv, validation_rows)
    vehicle_json.write_text(json.dumps(vehicle_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    vehicle_energy_json.write_text(json.dumps(vehicle_energy_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    energy_json.write_text(json.dumps(energy_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_json.write_text(json.dumps(artifacts.summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "vehicle_slot_ledger_csv": str(vehicle_csv),
        "vehicle_slot_ledger_json": str(vehicle_json),
        "vehicle_energy_ledger_csv": str(vehicle_energy_csv),
        "vehicle_energy_ledger_json": str(vehicle_energy_json),
        "energy_flow_ledger_csv": str(energy_csv),
        "energy_flow_ledger_json": str(energy_json),
        "fuel_canonical_ledger_csv": str(fuel_canonical_csv),
        "fuel_timeseries_csv": str(fuel_timeseries_csv),
        "co2_timeseries_csv": str(co2_timeseries_csv),
        "initial_soc_ledger_csv": str(initial_soc_csv),
        "initial_soc_precheck_csv": str(initial_soc_precheck_csv),
        "data_flow_validation_csv": str(validation_csv),
        "kpi_summary_json": str(summary_json),
    }

