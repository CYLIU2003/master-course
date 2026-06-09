"""Finalize reporting ledgers from canonical optimization run artifacts.

The functions in this module do not run solvers, simulations, dispatch, or
vehicle assignment. They only reconcile reporting artifacts from existing run
CSV/JSON ledgers.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any


TOL = 1e-6

REPORTING_FILES = [
    "graph/kpi_summary.json",
    "summary.json",
    "cost_breakdown_detail.csv",
    "graph/energy_flow_ledger.csv",
    "graph/data_flow_validation.csv",
]


@dataclass(frozen=True)
class ReportingRebuildResult:
    run_dir: Path
    updated_files: list[str]
    ledger_totals: dict[str, float]
    cost_totals: dict[str, float]
    validation_status: dict[str, Any]
    warnings: list[str]


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"required file not found: {path}")


def load_json(path: Path) -> dict[str, Any]:
    require_file(path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require_file(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def sum_column(path: Path, column: str) -> float:
    _, rows = read_csv(path)
    return sum(as_float(row.get(column)) for row in rows)


def max_column(path: Path, column: str) -> float:
    _, rows = read_csv(path)
    values = [as_float(row.get(column)) for row in rows if row.get(column) not in (None, "")]
    return max(values) if values else 0.0


def key_value_rows(path: Path) -> tuple[list[str], list[dict[str, str]], dict[str, int]]:
    fieldnames, rows = read_csv(path)
    if "key" in fieldnames and "value" in fieldnames:
        index = {row["key"]: i for i, row in enumerate(rows)}
        return fieldnames, rows, index
    if "component" in fieldnames and "yen" in fieldnames:
        normalized = [
            {"key": row.get("component", ""), "value": row.get("yen", ""), "unit": "JPY"}
            for row in rows
        ]
        index = {row["key"]: i for i, row in enumerate(normalized)}
        return ["key", "value", "unit"], normalized, index
    if "term" in fieldnames and "value" in fieldnames:
        normalized = [
            {"key": row.get("term", ""), "value": row.get("value", ""), "unit": row.get("unit", "")}
            for row in rows
        ]
        index = {row["key"]: i for i, row in enumerate(normalized)}
        return ["key", "value", "unit"], normalized, index
    raise ValueError(f"expected key/value, component/yen, or term/value CSV: {path}")


def get_kv(rows: list[dict[str, str]], index: dict[str, int], key: str, default: float = 0.0) -> float:
    if key not in index:
        return default
    return as_float(rows[index[key]].get("value"), default)


def set_kv(
    rows: list[dict[str, str]],
    index: dict[str, int],
    key: str,
    value: Any,
    unit: str | None = None,
) -> None:
    text_value = repr(float(value)) if isinstance(value, (int, float)) else str(value)
    if key in index:
        row = rows[index[key]]
        row["value"] = text_value
        if unit is not None and "unit" in row:
            row["unit"] = unit
        return
    row = {"key": key, "value": text_value}
    if rows and "unit" in rows[0]:
        row["unit"] = unit or ""
    rows.append(row)
    index[key] = len(rows) - 1


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_timestamp(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value.replace(" ", "T")


def bess_timestamp(row: dict[str, str]) -> str:
    if row.get("timestamp"):
        return normalize_timestamp(row["timestamp"])
    if row.get("date") and row.get("time"):
        return normalize_timestamp(f"{row['date']}T{row['time']}:00" if len(row["time"]) == 5 else f"{row['date']}T{row['time']}")
    if row.get("time"):
        return normalize_timestamp(row["time"])
    return ""


def infer_bess_capacity(bess_rows: list[dict[str, str]]) -> float:
    candidates: list[float] = []
    for row in bess_rows:
        soc = as_float(row.get("bess_soc_kwh"))
        pct = as_float(row.get("bess_soc_percent"))
        if soc > 0 and pct > 0:
            candidates.append(soc * 100.0 / pct)
    if candidates:
        return median(candidates)

    soc_max = max(as_float(row.get("bess_soc_max_kwh")) for row in bess_rows) if bess_rows else 0.0
    if soc_max > 0:
        return soc_max / 0.8
    return 0.0


def copy_run(input_dir: Path, output_dir: Path, overwrite: bool) -> None:
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input-run-dir not found: {input_dir}")
    if input_dir == output_dir:
        raise ValueError("input-run-dir and output-run-dir must differ")
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"ERROR: output-run-dir already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(input_dir, output_dir)


def update_energy_flow_bess_metadata(run_dir: Path) -> dict[str, Any]:
    energy_path = run_dir / "graph" / "energy_flow_ledger.csv"
    bess_path = run_dir / "graph" / "bess_timeseries.csv"
    energy_fields, energy_rows = read_csv(energy_path)
    _, bess_rows = read_csv(bess_path)

    required_cols = [
        "bess_capacity_kwh",
        "bess_soc_min_kwh",
        "bess_soc_max_kwh",
        "bess_terminal_soc_min_kwh",
        "bess_soc_start_kwh",
        "bess_soc_end_kwh",
    ]
    for col in required_cols:
        if col not in energy_fields:
            energy_fields.append(col)

    capacity = infer_bess_capacity(bess_rows)
    by_timestamp = {bess_timestamp(row): row for row in bess_rows if bess_timestamp(row)}
    by_index = {str(i): row for i, row in enumerate(bess_rows)}

    join_key = "row_number"
    matched_rows: list[dict[str, str]] = []
    if energy_rows and all(normalize_timestamp(row.get("timestamp", "")) in by_timestamp for row in energy_rows):
        join_key = "timestamp"
        matched_rows = [by_timestamp[normalize_timestamp(row.get("timestamp", ""))] for row in energy_rows]
    elif energy_rows and all(row.get("time") in by_timestamp for row in energy_rows if row.get("time")):
        join_key = "time"
        matched_rows = [by_timestamp[row.get("time", "")] for row in energy_rows]
    elif energy_rows and all(row.get("slot_index") in by_index for row in energy_rows):
        join_key = "slot_index"
        matched_rows = [by_index[row.get("slot_index", "")] for row in energy_rows]
    else:
        if len(energy_rows) != len(bess_rows):
            raise ValueError(
                "cannot align energy_flow_ledger.csv and bess_timeseries.csv by timestamp, slot_index, or row number"
            )
        matched_rows = bess_rows

    for row, bess in zip(energy_rows, matched_rows):
        row["bess_capacity_kwh"] = repr(float(capacity))
        row["bess_soc_min_kwh"] = repr(as_float(bess.get("bess_soc_min_kwh")))
        row["bess_soc_max_kwh"] = repr(as_float(bess.get("bess_soc_max_kwh")))
        row["bess_terminal_soc_min_kwh"] = repr(as_float(bess.get("bess_terminal_soc_min_kwh")))
        if "bess_soc_kwh" in bess:
            row["bess_soc_start_kwh"] = repr(as_float(bess.get("bess_soc_kwh")))
            row["bess_soc_end_kwh"] = repr(as_float(bess.get("bess_soc_kwh")))

    write_csv(energy_path, energy_fields, energy_rows)
    return {
        "bess_metadata_source": "graph/bess_timeseries.csv",
        "bess_metadata_join_key": join_key,
        "bess_capacity_kwh": capacity,
        "bess_soc_min_kwh": max(as_float(row.get("bess_soc_min_kwh")) for row in bess_rows) if bess_rows else 0.0,
        "bess_soc_max_kwh": max(as_float(row.get("bess_soc_max_kwh")) for row in bess_rows) if bess_rows else 0.0,
    }


def compute_ledger_totals(run_dir: Path) -> dict[str, float]:
    graph = run_dir / "graph"
    energy_path = graph / "energy_flow_ledger.csv"
    cost_path = graph / "cost_timeseries.csv"
    fuel_path = graph / "fuel_canonical_ledger.csv"
    fuel_ts_path = graph / "fuel_timeseries.csv"
    co2_path = graph / "co2_timeseries.csv"

    totals = {
        "pv_generation_kwh": sum_column(energy_path, "pv_generation_kwh"),
        "pv_to_bus_kwh": sum_column(energy_path, "pv_to_bus_kwh"),
        "pv_to_bess_kwh": sum_column(energy_path, "pv_to_bess_kwh"),
        "pv_curtailed_kwh": sum_column(energy_path, "pv_curtailed_kwh"),
        "pv_curtailment_kwh": sum_column(energy_path, "pv_curtailment_kwh"),
        "grid_to_bus_kwh": sum_column(energy_path, "grid_to_bus_kwh"),
        "grid_to_bess_kwh": sum_column(energy_path, "grid_to_bess_kwh"),
        "grid_import_kwh": sum_column(energy_path, "grid_import_kwh"),
        "bess_to_bus_kwh": sum_column(energy_path, "bess_to_bus_kwh"),
        "bus_charging_total_kwh": sum_column(energy_path, "bus_charging_total_kwh"),
        "bess_charge_kwh": sum_column(energy_path, "bess_charge_kwh"),
        "bess_discharge_kwh": sum_column(energy_path, "bess_discharge_kwh"),
        "pv_to_bus_cost_jpy": sum_column(energy_path, "pv_to_bus_cost_jpy"),
        "pv_to_bess_cost_jpy": sum_column(energy_path, "pv_to_bess_cost_jpy"),
        "bess_to_bus_cost_jpy": sum_column(energy_path, "bess_to_bus_cost_jpy"),
        "bess_total_flow_cost_jpy": sum_column(energy_path, "bess_total_flow_cost_jpy"),
        "peak_grid_import_kw": max_column(energy_path, "grid_import_kw"),
        "grid_purchase_cost_jpy": sum_column(cost_path, "grid_purchase_cost_jpy"),
        "fuel_consumption_l": sum_column(fuel_path, "fuel_consumption_l"),
        "fuel_cost_jpy": sum_column(fuel_path, "fuel_cost_jpy"),
        "fuel_timeseries_consumption_l": sum_column(fuel_ts_path, "fuel_consumption_l"),
        "fuel_timeseries_cost_jpy": sum_column(fuel_ts_path, "fuel_cost_jpy"),
        "grid_co2_kg": sum_column(co2_path, "grid_co2_kg"),
        "ice_co2_kg": sum_column(co2_path, "ice_co2_kg"),
        "total_co2_kg": sum_column(co2_path, "total_co2_kg"),
    }
    return totals


def update_cost_breakdown(run_dir: Path, totals: dict[str, float]) -> dict[str, float]:
    path = run_dir / "cost_breakdown_detail.csv"
    fields, rows, index = key_value_rows(path)

    old_total_co2 = get_kv(rows, index, "total_co2_kg")
    old_co2_cost = get_kv(rows, index, "co2_cost")
    carbon_price = old_co2_cost / old_total_co2 if old_total_co2 > 0 and old_co2_cost > 0 else 0.0
    co2_cost = totals["total_co2_kg"] * carbon_price

    electricity_cost = totals["grid_purchase_cost_jpy"]
    fuel_cost = totals["fuel_cost_jpy"]
    energy_cost = electricity_cost + fuel_cost
    demand_charge = get_kv(rows, index, "demand_charge")
    vehicle_cost = get_kv(rows, index, "vehicle_cost", get_kv(rows, index, "vehicle_fixed_cost"))
    battery_degradation_cost = get_kv(
        rows,
        index,
        "battery_degradation_cost",
        get_kv(rows, index, "degradation_cost"),
    )

    set_kv(rows, index, "electricity_cost", electricity_cost, "JPY")
    set_kv(rows, index, "electricity_cost_final", electricity_cost, "")
    set_kv(rows, index, "grid_purchase_cost", electricity_cost, "")
    set_kv(rows, index, "energy_cost", energy_cost, "JPY")
    set_kv(rows, index, "fuel_cost", fuel_cost, "JPY")
    set_kv(rows, index, "fuel_cost_final", fuel_cost, "JPY")
    set_kv(rows, index, "fuel_cost_provisional", fuel_cost, "JPY")
    set_kv(rows, index, "fuel_cost_provisional_leftover", fuel_cost, "JPY")
    set_kv(rows, index, "total_fuel_cost", fuel_cost, "")
    set_kv(rows, index, "vehicle_cost", vehicle_cost, "JPY")
    set_kv(rows, index, "battery_degradation_cost", battery_degradation_cost, "JPY")
    set_kv(rows, index, "degradation_cost", battery_degradation_cost, "JPY")
    set_kv(rows, index, "total_degradation_cost", battery_degradation_cost, "JPY")

    set_kv(rows, index, "grid_co2_kg", totals["grid_co2_kg"], "kg-CO2")
    set_kv(rows, index, "grid_electricity_co2_kg", totals["grid_co2_kg"], "")
    set_kv(rows, index, "power_generation_co2_kg", totals["grid_co2_kg"], "")
    set_kv(rows, index, "ice_co2_kg", totals["ice_co2_kg"], "")
    set_kv(rows, index, "ice_bus_co2_kg", totals["ice_co2_kg"], "")
    set_kv(rows, index, "engine_bus_co2_kg", totals["ice_co2_kg"], "")
    set_kv(rows, index, "total_co2_kg", totals["total_co2_kg"], "kg-CO2")
    set_kv(rows, index, "co2_cost", co2_cost, "JPY")

    real_total = (
        energy_cost
        + demand_charge
        + vehicle_cost
        + get_kv(rows, index, "driver_cost")
        + get_kv(rows, index, "deadhead_cost")
        + battery_degradation_cost
        + get_kv(rows, index, "contract_overage_cost")
        + get_kv(rows, index, "pv_self_consumption_cost_jpy")
        + get_kv(rows, index, "bess_discharge_cost")
        + co2_cost
    )
    total_with_assets = real_total + get_kv(rows, index, "pv_asset_cost") + get_kv(rows, index, "bess_asset_cost")
    set_kv(rows, index, "total_cost", real_total, "JPY")
    set_kv(rows, index, "total_cost_with_assets", total_with_assets, "")
    set_kv(rows, index, "total_operating_cost", real_total, "JPY")

    write_csv(path, fields, rows)
    return {
        "electricity_cost": electricity_cost,
        "demand_charge": demand_charge,
        "fuel_cost": fuel_cost,
        "energy_cost": energy_cost,
        "co2_cost": co2_cost,
        "battery_degradation_cost": battery_degradation_cost,
        "carbon_price_jpy_per_kg": carbon_price,
        "total_cost": real_total,
        "total_cost_with_assets": total_with_assets,
    }


def objective_value_from_breakdown(run_dir: Path, fallback: float) -> float:
    path = run_dir / "objective_breakdown.csv"
    fields, rows, index = key_value_rows(path)
    return get_kv(rows, index, "objective_value", fallback)


def update_summary(run_dir: Path, cost: dict[str, float]) -> dict[str, Any]:
    path = run_dir / "summary.json"
    summary = load_json(path)
    objective_value = objective_value_from_breakdown(run_dir, as_float(summary.get("objective_value_jpy", summary.get("objective_value"))))
    total_cost = cost["total_cost"]

    summary["objective_value"] = objective_value
    summary["objective_value_jpy"] = objective_value
    summary["objective_value_unit"] = "JPY"
    summary["total_cost_jpy"] = total_cost
    summary["reported_total_cost_jpy"] = total_cost
    summary["gross_operating_cost_jpy"] = total_cost
    summary["grid_purchase_cost_jpy"] = cost["electricity_cost"]
    summary["demand_charge_cost_jpy"] = cost["demand_charge"]
    summary["fuel_cost_jpy"] = cost["fuel_cost"]
    summary["co2_cost_jpy"] = cost["co2_cost"]
    summary["objective_is_actual_cost"] = False
    summary["cost_definition"] = {
        "total_cost_jpy": "gross operating cost based on canonical reporting ledgers",
        "reported_total_cost_jpy": "same as gross_operating_cost_jpy",
        "gross_operating_cost_jpy": "actual operating cost terms from reporting ledgers",
        "objective_value_jpy": "solver/fallback objective value; may include rewards and penalties",
        "objective_is_actual_cost": False,
    }
    write_json(path, summary)
    return summary


def update_kpi_summary(
    run_dir: Path,
    totals: dict[str, float],
    cost: dict[str, float],
    bess_metadata: dict[str, Any],
) -> dict[str, Any]:
    path = run_dir / "graph" / "kpi_summary.json"
    kpi = load_json(path)
    objective_value = objective_value_from_breakdown(run_dir, as_float(kpi.get("objective_value_jpy", kpi.get("objective_value"))))

    energy_keys = [
        "pv_generation_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "pv_curtailment_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "grid_import_kwh",
        "bess_to_bus_kwh",
        "bus_charging_total_kwh",
        "bess_charge_kwh",
        "bess_discharge_kwh",
        "peak_grid_import_kw",
    ]
    for key in energy_keys:
        if key in totals:
            kpi[key] = totals[key]

    kpi["grid_total_kwh"] = totals["grid_import_kwh"]
    kpi["peak_grid_kw"] = totals["peak_grid_import_kw"]
    kpi["bess_discharge_to_bus_kwh"] = totals["bess_discharge_kwh"]

    cost_keys = {
        "grid_purchase_cost_jpy": cost["electricity_cost"],
        "demand_charge_cost_jpy": cost["demand_charge"],
        "fuel_cost_jpy": cost["fuel_cost"],
        "co2_cost_jpy": cost["co2_cost"],
        "battery_degradation_cost_jpy": cost["battery_degradation_cost"],
        "pv_to_bus_cost_jpy": totals["pv_to_bus_cost_jpy"],
        "pv_to_bess_cost_jpy": totals["pv_to_bess_cost_jpy"],
        "bess_to_bus_cost_jpy": totals["bess_to_bus_cost_jpy"],
        "bess_total_flow_cost_jpy": totals["bess_total_flow_cost_jpy"],
    }
    for key, value in cost_keys.items():
        kpi[key] = value

    kpi["energy_cost_jpy"] = cost["energy_cost"]
    kpi["demand_cost_jpy"] = cost["demand_charge"]
    kpi["total_cost_jpy"] = cost["total_cost"]
    kpi["gross_operating_cost_jpy"] = cost["total_cost"]
    kpi["reported_total_cost_jpy"] = cost["total_cost"]
    kpi["objective_value"] = objective_value
    kpi["objective_value_jpy"] = objective_value
    kpi["objective_is_actual_cost"] = False

    kpi["fuel_consumption_l"] = totals["fuel_consumption_l"]
    kpi["ice_fuel_consumed_l"] = totals["fuel_consumption_l"]
    kpi["ice_fuel_l"] = totals["fuel_consumption_l"]
    kpi["grid_co2_kg"] = totals["grid_co2_kg"]
    kpi["electricity_co2_kg"] = totals["grid_co2_kg"]
    kpi["ice_co2_kg"] = totals["ice_co2_kg"]
    kpi["fuel_co2_kg"] = totals["ice_co2_kg"]
    kpi["total_co2_kg"] = totals["total_co2_kg"]

    kpi.setdefault("energy", {})
    kpi["energy"].update({key: kpi[key] for key in energy_keys if key in kpi})
    kpi["energy"]["grid_import_kwh"] = totals["grid_import_kwh"]
    kpi["energy"]["bess_discharge_kwh"] = totals["bess_discharge_kwh"]

    kpi.setdefault("fuel", {})
    kpi["fuel"].update(
        {
            "fuel_consumption_l": totals["fuel_consumption_l"],
            "fuel_cost_jpy": cost["fuel_cost"],
            "fuel_source_of_truth": "fuel_canonical_ledger",
        }
    )

    kpi.setdefault("co2", {})
    kpi["co2"].update(
        {
            "total_co2_kg": totals["total_co2_kg"],
            "grid_co2_kg": totals["grid_co2_kg"],
            "ice_co2_kg": totals["ice_co2_kg"],
            "co2_boundary": "grid_plus_ice",
            "co2_accounting_method": "grid_import_based",
        }
    )

    kpi.setdefault("cost", {})
    kpi["cost"].update(cost_keys)
    kpi["cost"].update(
        {
            "energy_cost_jpy": cost["energy_cost"],
            "gross_operating_cost_jpy": cost["total_cost"],
            "reported_total_cost_jpy": cost["total_cost"],
            "total_cost_jpy": cost["total_cost"],
            "objective_value": objective_value,
            "objective_value_jpy": objective_value,
            "objective_is_actual_cost": False,
        }
    )

    kpi.setdefault("bess", {})
    kpi["bess"].update(
        {
            "capacity_kwh": bess_metadata["bess_capacity_kwh"],
            "soc_min_kwh": bess_metadata["bess_soc_min_kwh"],
            "soc_max_kwh": bess_metadata["bess_soc_max_kwh"],
            "pv_to_bess_kwh": totals["pv_to_bess_kwh"],
            "grid_to_bess_kwh": totals["grid_to_bess_kwh"],
            "bess_to_bus_kwh": totals["bess_to_bus_kwh"],
            "bess_charge_kwh": totals["bess_charge_kwh"],
            "bess_discharge_kwh": totals["bess_discharge_kwh"],
            "pv_to_bess_cost_jpy": totals["pv_to_bess_cost_jpy"],
            "pv_to_bus_cost_jpy": totals["pv_to_bus_cost_jpy"],
            "bess_to_bus_cost_jpy": totals["bess_to_bus_cost_jpy"],
            "bess_total_flow_cost_jpy": totals["bess_total_flow_cost_jpy"],
        }
    )

    kpi.setdefault("metadata", {})
    kpi["metadata"].update(
        {
            "bess_metadata_source": bess_metadata["bess_metadata_source"],
            "bess_metadata_join_key": bess_metadata["bess_metadata_join_key"],
        }
    )
    kpi["bess_metadata_source"] = bess_metadata["bess_metadata_source"]
    kpi["bess_metadata_join_key"] = bess_metadata["bess_metadata_join_key"]
    kpi["cost_definition"] = {
        "total_cost_jpy": "gross operating cost based on canonical reporting ledgers",
        "reported_total_cost_jpy": "same as gross_operating_cost_jpy",
        "gross_operating_cost_jpy": "actual operating cost terms from reporting ledgers",
        "objective_value_jpy": "solver/fallback objective value; may include rewards and penalties",
        "objective_is_actual_cost": False,
    }

    write_json(path, kpi)
    return kpi


def validation_row(
    check_name: str,
    expected: Any,
    actual: Any,
    tolerance: float = TOL,
    severity: str = "INFO",
    source_files: str = "",
) -> dict[str, Any]:
    if isinstance(expected, bool) or isinstance(actual, bool):
        ok = expected is actual
        diff: Any = 0.0 if ok else 1.0
    else:
        expected_f = as_float(expected)
        actual_f = as_float(actual)
        diff = actual_f - expected_f
        ok = abs(diff) <= tolerance
    return {
        "check_name": check_name,
        "status": "OK" if ok else "NG",
        "expected_value": expected,
        "actual_value": actual,
        "difference": diff,
        "tolerance": tolerance,
        "severity": severity if not ok else "INFO",
        "message": "OK" if ok else f"{check_name} differs by {diff}",
        "source_files": source_files,
    }


def update_data_flow_validation(
    run_dir: Path,
    totals: dict[str, float],
    cost: dict[str, float],
    summary: dict[str, Any],
    kpi: dict[str, Any],
    bess_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    path = run_dir / "graph" / "data_flow_validation.csv"
    fields, rows = read_csv(path)
    _, cost_rows, cost_index = key_value_rows(run_dir / "cost_breakdown_detail.csv")
    cost_breakdown_total = get_kv(cost_rows, cost_index, "total_cost")
    cost_breakdown_fuel_cost = get_kv(cost_rows, cost_index, "fuel_cost")
    cost_breakdown_ice_co2 = get_kv(cost_rows, cost_index, "ice_co2_kg")
    cost_breakdown_total_co2 = get_kv(cost_rows, cost_index, "total_co2_kg")
    vehicle_source_path = run_dir / "graph" / "vehicle_charging_source_timeseries.csv"
    vehicle_grid_to_bus = sum_column(vehicle_source_path, "grid_to_vehicle_kwh") if vehicle_source_path.exists() else 0.0
    vehicle_pv_to_bus = sum_column(vehicle_source_path, "pv_to_vehicle_kwh") if vehicle_source_path.exists() else 0.0
    vehicle_bess_to_bus = sum_column(vehicle_source_path, "bess_to_vehicle_kwh") if vehicle_source_path.exists() else 0.0
    required_fields = [
        "check_name",
        "status",
        "expected_value",
        "actual_value",
        "difference",
        "tolerance",
        "severity",
        "message",
        "source_files",
    ]
    if fields != required_fields:
        fields = required_fields

    checks = [
        validation_row(
            "pv_generation_balance",
            totals["pv_generation_kwh"],
            totals["pv_to_bus_kwh"] + totals["pv_to_bess_kwh"] + totals["pv_curtailed_kwh"],
            tolerance=1.0e-3,
            source_files="energy_flow_ledger.csv",
        ),
        validation_row(
            "bus_charging_balance",
            totals["bus_charging_total_kwh"],
            totals["grid_to_bus_kwh"] + totals["pv_to_bus_kwh"] + totals["bess_to_bus_kwh"],
            tolerance=1.0e-3,
            source_files="energy_flow_ledger.csv",
        ),
        validation_row(
            "grid_import_balance",
            totals["grid_import_kwh"],
            totals["grid_to_bus_kwh"] + totals["grid_to_bess_kwh"],
            tolerance=1.0e-3,
            source_files="energy_flow_ledger.csv",
        ),
        validation_row(
            "bess_charge_balance",
            totals["bess_charge_kwh"],
            totals["pv_to_bess_kwh"] + totals["grid_to_bess_kwh"],
            tolerance=1.0e-3,
            source_files="energy_flow_ledger.csv",
        ),
        validation_row(
            "bess_discharge_balance",
            totals["bess_discharge_kwh"],
            totals["bess_to_bus_kwh"],
            tolerance=1.0e-3,
            source_files="energy_flow_ledger.csv",
        ),
        validation_row(
            "vehicle_grid_to_bus_allocation_matches_site_total",
            totals["grid_to_bus_kwh"],
            vehicle_grid_to_bus,
            tolerance=1.0e-3,
            severity="WARNING",
            source_files="vehicle_charging_source_timeseries.csv;energy_flow_ledger.csv",
        ),
        validation_row(
            "vehicle_pv_to_bus_allocation_matches_site_total",
            totals["pv_to_bus_kwh"],
            vehicle_pv_to_bus,
            tolerance=1.0e-3,
            severity="WARNING",
            source_files="vehicle_charging_source_timeseries.csv;energy_flow_ledger.csv",
        ),
        validation_row(
            "vehicle_bess_to_bus_allocation_matches_site_total",
            totals["bess_to_bus_kwh"],
            vehicle_bess_to_bus,
            tolerance=1.0e-3,
            severity="WARNING",
            source_files="vehicle_charging_source_timeseries.csv;energy_flow_ledger.csv",
        ),
        validation_row(
            "kpi_grid_purchase_cost_matches_cost_timeseries",
            totals["grid_purchase_cost_jpy"],
            as_float(kpi.get("grid_purchase_cost_jpy")),
            source_files="kpi_summary.json;cost_timeseries.csv",
        ),
        validation_row(
            "kpi_demand_charge_matches_cost_breakdown",
            cost["demand_charge"],
            as_float(kpi.get("demand_charge_cost_jpy")),
            source_files="kpi_summary.json;cost_breakdown_detail.csv",
        ),
        validation_row(
            "kpi_fuel_cost_matches_fuel_canonical",
            totals["fuel_cost_jpy"],
            as_float(kpi.get("fuel_cost_jpy")),
            source_files="kpi_summary.json;fuel_canonical_ledger.csv",
        ),
        validation_row(
            "kpi_total_cost_matches_cost_breakdown",
            cost_breakdown_total,
            as_float(kpi.get("reported_total_cost_jpy")),
            source_files="kpi_summary.json;cost_breakdown_detail.csv",
        ),
        validation_row(
            "summary_total_cost_matches_cost_breakdown",
            cost_breakdown_total,
            as_float(summary.get("gross_operating_cost_jpy")),
            source_files="summary.json;cost_breakdown_detail.csv",
        ),
        validation_row(
            "summary_objective_value_matches_objective_breakdown",
            objective_value_from_breakdown(run_dir, 0.0),
            as_float(summary.get("objective_value_jpy")),
            source_files="summary.json;objective_breakdown.csv",
        ),
        validation_row(
            "summary_total_cost_separated_from_objective_value",
            False,
            bool(summary.get("objective_is_actual_cost")),
            source_files="summary.json",
        ),
        validation_row(
            "cost_breakdown_fuel_cost_matches_fuel_canonical",
            totals["fuel_cost_jpy"],
            cost_breakdown_fuel_cost,
            source_files="cost_breakdown_detail.csv;fuel_canonical_ledger.csv",
        ),
        validation_row(
            "cost_breakdown_ice_co2_matches_co2_timeseries",
            totals["ice_co2_kg"],
            cost_breakdown_ice_co2,
            source_files="cost_breakdown_detail.csv;co2_timeseries.csv",
        ),
        validation_row(
            "cost_breakdown_total_co2_matches_co2_timeseries",
            totals["total_co2_kg"],
            cost_breakdown_total_co2,
            source_files="cost_breakdown_detail.csv;co2_timeseries.csv",
        ),
        validation_row(
            "energy_flow_bess_capacity_matches_bess_timeseries",
            bess_metadata["bess_capacity_kwh"],
            max_column(run_dir / "graph" / "energy_flow_ledger.csv", "bess_capacity_kwh"),
            source_files="energy_flow_ledger.csv;bess_timeseries.csv",
        ),
        validation_row(
            "energy_flow_bess_soc_min_matches_bess_timeseries",
            bess_metadata["bess_soc_min_kwh"],
            max_column(run_dir / "graph" / "energy_flow_ledger.csv", "bess_soc_min_kwh"),
            source_files="energy_flow_ledger.csv;bess_timeseries.csv",
        ),
        validation_row(
            "energy_flow_bess_soc_max_matches_bess_timeseries",
            bess_metadata["bess_soc_max_kwh"],
            max_column(run_dir / "graph" / "energy_flow_ledger.csv", "bess_soc_max_kwh"),
            source_files="energy_flow_ledger.csv;bess_timeseries.csv",
        ),
    ]

    replace_names = {row["check_name"] for row in checks}
    replace_names.update(
        {
            "cost_breakdown_balance",
            "kpi_grid_purchase_cost_matches_cost_ledger",
            "kpi_demand_charge_cost_matches_cost_ledger",
            "pv_generation_balance",
            "bus_charging_balance",
            "grid_import_balance",
            "bess_charge_balance",
            "bess_discharge_balance",
            "vehicle_grid_to_bus_allocation_matches_site_total",
            "vehicle_pv_to_bus_allocation_matches_site_total",
            "vehicle_bess_to_bus_allocation_matches_site_total",
        }
    )
    kept = [row for row in rows if row.get("check_name") not in replace_names]
    kept.append(
        validation_row(
            "cost_breakdown_balance",
            cost["total_cost"],
            as_float(kpi.get("reported_total_cost_jpy")),
            source_files="cost_breakdown_detail.csv;kpi_summary.json",
        )
    )
    kept.extend(checks)
    write_csv(path, fields, kept)
    return kept


def update_validation_counts(run_dir: Path, rows: list[dict[str, Any]], kpi: dict[str, Any]) -> None:
    errors = sum(1 for row in rows if row.get("status") == "NG" and row.get("severity") == "ERROR")
    warnings = sum(1 for row in rows if row.get("status") == "NG" and row.get("severity") == "WARNING")
    status = "ERROR" if errors else ("WARNING" if warnings else "OK")

    kpi["data_flow_validation_status"] = status
    kpi["data_flow_error_count"] = errors
    kpi["data_flow_warning_count"] = warnings
    kpi["validation_status"] = status
    kpi.setdefault("validation", {})
    kpi["validation"].update(
        {"data_flow_validation_status": status, "error_count": errors, "warning_count": warnings}
    )
    write_json(run_dir / "graph" / "kpi_summary.json", kpi)


def status_for_checks(rows: list[dict[str, Any]], check_names: set[str]) -> str:
    selected = [row for row in rows if row.get("check_name") in check_names]
    if not selected:
        return "SKIPPED"
    return "OK" if all(row.get("status") == "OK" for row in selected) else "NG"


def write_strict_reconciliation(run_dir: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    def domain_row(domain: str, status: str, message: str, severity: str | None = None) -> dict[str, Any]:
        return {
            "domain": domain,
            "check_name": f"{domain}_strict_reconciliation",
            "source_a": "canonical reporting ledgers",
            "source_a_value": "",
            "source_b": "final reporting artifacts",
            "source_b_value": "",
            "difference": "",
            "tolerance": TOL,
            "status": status,
            "severity": severity or ("ERROR" if status == "NG" else "INFO"),
            "message": message,
        }

    strict_rows = [
        domain_row(
            "energy",
            status_for_checks(
                rows,
                {
                    "pv_generation_balance",
                    "bus_charging_balance",
                    "grid_import_balance",
                    "bess_charge_balance",
                    "bess_discharge_balance",
                },
            ),
            "Existing energy-flow checks preserved after reporting finalization.",
        ),
        domain_row(
            "identity",
            status_for_checks(rows, {"operator_id_empty_count", "service_date_consistency"}),
            "Identity checks were not modified by the finalizer.",
        ),
        domain_row(
            "vehicle-charge-allocation",
            status_for_checks(
                rows,
                {
                    "vehicle_grid_to_bus_allocation_matches_site_total",
                    "vehicle_pv_to_bus_allocation_matches_site_total",
                    "vehicle_bess_to_bus_allocation_matches_site_total",
                },
            ),
            "Vehicle charging source allocation ledgers were reconciled against site totals.",
        ),
        domain_row(
            "fuel",
            status_for_checks(
                rows,
                {
                    "fuel_cost_matches_fuel_consumption",
                    "cost_breakdown_fuel_cost_matches_fuel_canonical",
                    "kpi_fuel_cost_matches_fuel_canonical",
                },
            ),
            "Fuel cost follows fuel_canonical_ledger.csv.",
        ),
        domain_row(
            "co2",
            status_for_checks(
                rows,
                {
                    "co2_total_equals_grid_plus_ice",
                    "cost_breakdown_ice_co2_matches_co2_timeseries",
                    "cost_breakdown_total_co2_matches_co2_timeseries",
                },
            ),
            "CO2 totals follow co2_timeseries.csv.",
        ),
        domain_row(
            "cost",
            status_for_checks(
                rows,
                {
                    "kpi_grid_purchase_cost_matches_cost_timeseries",
                    "kpi_demand_charge_matches_cost_breakdown",
                    "kpi_total_cost_matches_cost_breakdown",
                    "summary_total_cost_matches_cost_breakdown",
                },
            ),
            "Cost KPI and summary totals are separated from objective value.",
        ),
        domain_row(
            "bess-metadata",
            status_for_checks(
                rows,
                {
                    "energy_flow_bess_capacity_matches_bess_timeseries",
                    "energy_flow_bess_soc_min_matches_bess_timeseries",
                    "energy_flow_bess_soc_max_matches_bess_timeseries",
                },
            ),
            "BESS capacity and SOC bounds come from bess_timeseries.csv.",
        ),
        domain_row(
            "vehicle-soc-violation",
            "OUT_OF_SCOPE_REMAINS",
            "Remains because this run was not re-optimized.",
            "WARNING",
        ),
        domain_row(
            "solver-status",
            "OUT_OF_SCOPE_REMAINS" if summary.get("solver_status") == "BASELINE_FALLBACK" else "OK",
            "BASELINE_FALLBACK remains because this run was not re-optimized."
            if summary.get("solver_status") == "BASELINE_FALLBACK"
            else "Solver status does not indicate BASELINE_FALLBACK.",
            "WARNING" if summary.get("solver_status") == "BASELINE_FALLBACK" else "INFO",
        ),
    ]
    legacy_rows = [
        {
            "category": "energy",
            "status": strict_rows[0]["status"],
            "message": strict_rows[0]["message"],
        },
        {
            "category": "identity",
            "status": strict_rows[1]["status"],
            "message": strict_rows[1]["message"],
        },
        {
            "category": "vehicle-charge-allocation",
            "status": strict_rows[2]["status"],
            "message": strict_rows[2]["message"],
        },
        {
            "category": "fuel",
            "status": strict_rows[3]["status"],
            "message": strict_rows[3]["message"],
        },
        {
            "category": "co2",
            "status": strict_rows[4]["status"],
            "message": strict_rows[4]["message"],
        },
        {
            "category": "cost",
            "status": strict_rows[5]["status"],
            "message": strict_rows[5]["message"],
        },
        {
            "category": "bess-metadata",
            "status": strict_rows[6]["status"],
            "message": strict_rows[6]["message"],
        },
        {
            "category": "vehicle-soc-violation",
            "status": strict_rows[7]["status"],
            "message": strict_rows[7]["message"],
        },
        {
            "category": "solver-status",
            "status": strict_rows[8]["status"],
            "message": strict_rows[8]["message"],
        },
    ]
    fields = [
        "domain",
        "check_name",
        "source_a",
        "source_a_value",
        "source_b",
        "source_b_value",
        "difference",
        "tolerance",
        "status",
        "severity",
        "message",
    ]
    write_csv(run_dir / "strict_reconciliation.csv", fields, strict_rows)
    write_csv(run_dir / "strict_reconciliation_after_rebuild.csv", ["category", "status", "message"], legacy_rows)

    md_lines = ["| Domain | Status | Severity | Message |", "|---|---|---|---|"]
    for row in strict_rows:
        md_lines.append(f"| {row['domain']} | {row['status']} | {row['severity']} | {row['message']} |")
    md_text = "\n".join(md_lines) + "\n"
    (run_dir / "strict_reconciliation.md").write_text(md_text, encoding="utf-8")
    (run_dir / "strict_reconciliation_after_rebuild.md").write_text(md_text, encoding="utf-8")


def write_manifest(input_dir: Path, output_dir: Path) -> None:
    entries = []
    for rel in REPORTING_FILES + [
        "rebuild_reporting_log.json",
        "strict_reconciliation.csv",
        "strict_reconciliation.md",
        "strict_reconciliation_after_rebuild.csv",
        "strict_reconciliation_after_rebuild.md",
    ]:
        input_path = input_dir / rel
        output_path = output_dir / rel
        input_hash = sha256_file(input_path)
        output_hash = sha256_file(output_path)
        entries.append(
            {
                "path": rel,
                "input_sha256": input_hash,
                "output_sha256": output_hash,
                "changed_from_input": input_hash != output_hash,
                "created_in_output": input_hash is None and output_hash is not None,
            }
        )
    manifest = {
        "input_run_dir": str(input_dir),
        "output_run_dir": str(output_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_run_modified": False,
        "manifest_path": "changed_files_manifest.json",
        "files": entries,
    }
    write_json(output_dir / "changed_files_manifest.json", manifest)


def _reporting_log_payload(
    run_dir: Path,
    totals: dict[str, float],
    cost: dict[str, float],
    bess_metadata: dict[str, Any],
    kpi: dict[str, Any],
    mode: str,
    input_dir: Path | None = None,
) -> dict[str, Any]:
    log = {
        "mode": mode,
        "run_dir": str(run_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "solver_rerun": False,
        "simulation_rerun": False,
        "vehicle_assignment_regenerated": False,
        "no_reoptimization_performed": True,
        "updated_files": REPORTING_FILES,
        "source_of_truth": {
            "energy": "graph/energy_flow_ledger.csv",
            "bess_metadata": "graph/bess_timeseries.csv",
            "grid_purchase_cost": "graph/cost_timeseries.csv",
            "demand_charge": "cost_breakdown_detail.csv:demand_charge",
            "fuel": "graph/fuel_canonical_ledger.csv",
            "co2": "graph/co2_timeseries.csv",
            "objective": "objective_breakdown.csv",
            "gross_operating_cost": "cost_breakdown_detail.csv",
        },
        "totals": totals,
        "cost": cost,
        "bess_metadata": bess_metadata,
        "validation_status": kpi.get("data_flow_validation_status"),
        "validation_error_count": kpi.get("data_flow_error_count"),
        "out_of_scope_remaining": ["vehicle SOC violation", "BASELINE_FALLBACK"],
    }
    if input_dir is not None:
        log["input_run_dir"] = str(input_dir)
        log["output_run_dir"] = str(run_dir)
        log["source_run_modified"] = False
    return log


def rebuild_reporting_artifacts_in_place(run_dir: Path) -> ReportingRebuildResult:
    run_dir = run_dir.resolve()
    bess_metadata = update_energy_flow_bess_metadata(run_dir)
    totals = compute_ledger_totals(run_dir)
    cost = update_cost_breakdown(run_dir, totals)
    summary = update_summary(run_dir, cost)
    kpi = update_kpi_summary(run_dir, totals, cost, bess_metadata)
    validation_rows = update_data_flow_validation(run_dir, totals, cost, summary, kpi, bess_metadata)
    update_validation_counts(run_dir, validation_rows, kpi)
    kpi = load_json(run_dir / "graph" / "kpi_summary.json")
    write_strict_reconciliation(run_dir, validation_rows, summary)
    log = _reporting_log_payload(run_dir, totals, cost, bess_metadata, kpi, "in_place_after_optimization")
    write_json(run_dir / "rebuild_reporting_log.json", log)
    warnings = [
        str(row.get("check_name"))
        for row in validation_rows
        if row.get("status") == "NG" and row.get("severity") == "WARNING"
    ]
    return ReportingRebuildResult(
        run_dir=run_dir,
        updated_files=list(REPORTING_FILES),
        ledger_totals=totals,
        cost_totals=cost,
        validation_status={
            "status": kpi.get("data_flow_validation_status"),
            "error_count": kpi.get("data_flow_error_count"),
            "warning_count": kpi.get("data_flow_warning_count"),
        },
        warnings=warnings,
    )


def rebuild_reporting_artifacts_to_output_dir(
    input_dir: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    copy_run(input_dir, output_dir, overwrite)
    result = rebuild_reporting_artifacts_in_place(output_dir)
    kpi = load_json(output_dir / "graph" / "kpi_summary.json")
    log = _reporting_log_payload(
        output_dir,
        result.ledger_totals,
        result.cost_totals,
        {"source": "graph/bess_timeseries.csv"},
        kpi,
        "copy_backfill_existing_run",
        input_dir=input_dir,
    )
    write_json(output_dir / "rebuild_reporting_log.json", log)
    write_manifest(input_dir, output_dir)
    return log
