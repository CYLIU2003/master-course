from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .schema import AccountingArtifacts


FUEL_CANONICAL_LEDGER_FIELDNAMES = (
    "timestamp",
    "service_date",
    "vehicle_id",
    "operator_id",
    "vehicle_type",
    "trip_id",
    "route_id",
    "distance_km",
    "fuel_efficiency_km_per_l",
    "fuel_consumption_l",
    "refuel_l",
    "fuel_cost_jpy",
    "ice_co2_kg",
    "diesel_price_jpy_per_l",
    "fuel_emission_factor_kg_per_l",
)
FUEL_TIMESERIES_FIELDNAMES = (
    "timestamp",
    "service_date",
    "fuel_consumption_l",
    "refuel_l",
    "fuel_cost_jpy",
    "ice_co2_kg",
    "fuel_source_of_truth",
)


def _row_dict(row: Any) -> dict[str, Any]:
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError(f"Unsupported row type: {type(row)!r}")


def _write_csv(
    path: Path,
    rows: Sequence[Any],
    *,
    empty_fieldnames: Sequence[str] = (),
) -> None:
    import csv

    data = [_row_dict(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        if not empty_fieldnames:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=list(empty_fieldnames)).writeheader()
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
    movement_csv = root / "movement_event_ledger.csv"
    movement_json = root / "movement_event_ledger.json"
    vehicle_energy_csv = root / "vehicle_energy_ledger.csv"
    vehicle_energy_json = root / "vehicle_energy_ledger.json"
    energy_csv = root / "energy_flow_ledger.csv"
    energy_json = root / "energy_flow_ledger.json"
    bess_timeseries_csv = root / "bess_timeseries.csv"
    fuel_canonical_csv = root / "fuel_canonical_ledger.csv"
    fuel_timeseries_csv = root / "fuel_timeseries.csv"
    co2_timeseries_csv = root / "co2_timeseries.csv"
    initial_soc_csv = root / "initial_soc_ledger.csv"
    initial_soc_precheck_csv = root / "initial_soc_precheck.csv"
    validation_csv = root / "data_flow_validation.csv"
    summary_json = root / "kpi_summary.json"

    vehicle_rows = [_row_dict(row) for row in artifacts.vehicle_slot_ledger]
    movement_rows = [_row_dict(row) for row in artifacts.movement_event_ledger]
    vehicle_energy_rows = [_row_dict(row) for row in artifacts.vehicle_energy_ledger]
    energy_rows = [_row_dict(row) for row in artifacts.energy_flow_ledger]
    fuel_canonical_rows = [_row_dict(row) for row in artifacts.fuel_canonical_ledger]
    fuel_timeseries_rows = [_row_dict(row) for row in artifacts.fuel_timeseries]
    co2_timeseries_rows = [_row_dict(row) for row in artifacts.co2_timeseries]
    initial_soc_rows = [_row_dict(row) for row in artifacts.initial_soc_ledger]
    initial_soc_precheck_rows = [_row_dict(row) for row in artifacts.initial_soc_precheck]
    validation_rows = [_row_dict(row) for row in artifacts.data_flow_validation]
    bess_rows = [
        {
            "timestamp": row.get("timestamp", row.get("slot_start", "")),
            "service_date": row.get("service_date", ""),
            "depot_id": row.get("depot_id", ""),
            "bess_capacity_kwh": row.get("bess_capacity_kwh", 0.0),
            "bess_soc_start_kwh": row.get("bess_soc_start_kwh", 0.0),
            "bess_soc_end_kwh": row.get("bess_soc_end_kwh", 0.0),
            "bess_soc_percent": (
                (float(row.get("bess_soc_end_kwh", 0.0) or 0.0) / float(row.get("bess_capacity_kwh", 0.0) or 0.0) * 100.0)
                if float(row.get("bess_capacity_kwh", 0.0) or 0.0) > 0.0
                else 0.0
            ),
            "bess_soc_min_kwh": row.get("bess_soc_min_kwh", 0.0),
            "bess_soc_max_kwh": row.get("bess_soc_max_kwh", 0.0),
            "bess_terminal_soc_min_kwh": row.get("bess_terminal_soc_min_kwh", 0.0),
            "pv_to_bess_kwh": row.get("pv_to_bess_kwh", 0.0),
            "grid_to_bess_kwh": row.get("grid_to_bess_kwh", 0.0),
            "bess_charge_kwh": row.get("bess_charge_kwh", 0.0),
            "bess_discharge_kwh": row.get("bess_discharge_kwh", 0.0),
            "bess_to_bus_kwh": row.get("bess_to_bus_kwh", 0.0),
            "bess_charge_kw": float(row.get("bess_charge_kwh", 0.0) or 0.0) / max(float(row.get("slot_minutes", 0.0) or 0.0) / 60.0, 1.0e-9),
            "bess_discharge_kw": float(row.get("bess_discharge_kwh", 0.0) or 0.0) / max(float(row.get("slot_minutes", 0.0) or 0.0) / 60.0, 1.0e-9),
            "bess_to_bus_unit_cost_jpy_per_kwh": row.get("bess_to_bus_unit_cost_jpy_per_kwh", 0.0),
            "pv_to_bess_cost_jpy": row.get("pv_to_bess_cost_jpy", 0.0),
            "pv_to_bus_cost_jpy": row.get("pv_to_bus_cost_jpy", 0.0),
            "bess_to_bus_cost_jpy": row.get("bess_to_bus_cost_jpy", 0.0),
            "bess_total_flow_cost_jpy": row.get("bess_total_flow_cost_jpy", 0.0),
            "bess_soc_violation_kwh": row.get("bess_soc_violation_kwh", 0.0),
        }
        for row in energy_rows
    ]

    _write_csv(vehicle_csv, vehicle_rows)
    _write_csv(movement_csv, movement_rows)
    _write_csv(vehicle_energy_csv, vehicle_energy_rows)
    _write_csv(energy_csv, energy_rows)
    _write_csv(bess_timeseries_csv, bess_rows)
    _write_csv(
        fuel_canonical_csv,
        fuel_canonical_rows,
        empty_fieldnames=FUEL_CANONICAL_LEDGER_FIELDNAMES,
    )
    _write_csv(
        fuel_timeseries_csv,
        fuel_timeseries_rows,
        empty_fieldnames=FUEL_TIMESERIES_FIELDNAMES,
    )
    _write_csv(co2_timeseries_csv, co2_timeseries_rows)
    _write_csv(initial_soc_csv, initial_soc_rows)
    _write_csv(initial_soc_precheck_csv, initial_soc_precheck_rows)
    _write_csv(validation_csv, validation_rows)
    vehicle_json.write_text(json.dumps(vehicle_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    movement_json.write_text(
        json.dumps(movement_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    vehicle_energy_json.write_text(json.dumps(vehicle_energy_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    energy_json.write_text(json.dumps(energy_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_json.write_text(json.dumps(artifacts.summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "vehicle_slot_ledger_csv": str(vehicle_csv),
        "vehicle_slot_ledger_json": str(vehicle_json),
        "movement_event_ledger_csv": str(movement_csv),
        "movement_event_ledger_json": str(movement_json),
        "vehicle_energy_ledger_csv": str(vehicle_energy_csv),
        "vehicle_energy_ledger_json": str(vehicle_energy_json),
        "energy_flow_ledger_csv": str(energy_csv),
        "energy_flow_ledger_json": str(energy_json),
        "bess_timeseries_csv": str(bess_timeseries_csv),
        "fuel_canonical_ledger_csv": str(fuel_canonical_csv),
        "fuel_timeseries_csv": str(fuel_timeseries_csv),
        "co2_timeseries_csv": str(co2_timeseries_csv),
        "initial_soc_ledger_csv": str(initial_soc_csv),
        "initial_soc_precheck_csv": str(initial_soc_precheck_csv),
        "data_flow_validation_csv": str(validation_csv),
        "kpi_summary_json": str(summary_json),
    }

