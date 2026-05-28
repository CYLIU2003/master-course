from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sum(rows: list[dict[str, Any]], key: str) -> float:
    return sum(_safe_float(row.get(key)) for row in rows)


def _find_existing(root: Path, *candidates: str) -> Path | None:
    for candidate in candidates:
        path = root / candidate
        if path.exists():
            return path
    return None


def _report(label: str, ok: bool, detail: str) -> None:
    print(f"[{'OK' if ok else 'FAIL'}] {label}: {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate optimization output consistency")
    parser.add_argument("output_dir", help="Run output directory")
    args = parser.parse_args()

    root = Path(args.output_dir)
    issues: list[str] = []

    ledger_path = _find_existing(root, "energy_flow_ledger.csv", "depot_energy_flows.csv", "graph\\energy_flow_ledger.csv")
    source_path = _find_existing(root, "graph\\vehicle_charge_energy_sources.csv", "vehicle_charge_energy_sources.csv")
    soc_path = _find_existing(root, "graph\\vehicle_soc_timeseries.csv", "vehicle_soc_timeseries.csv")
    slot_path = _find_existing(root, "vehicle_slot_ledger.csv", "graph\\vehicle_slot_ledger.csv")
    trip_path = _find_existing(root, "trip_assignment.csv", "graph\\trip_assignment.csv")
    kpi_path = _find_existing(root, "kpi_summary.json", "graph\\kpi_summary.json")

    ledger_rows = _read_csv(ledger_path) if ledger_path else []
    source_rows = _read_csv(source_path) if source_path else []
    soc_rows = _read_csv(soc_path) if soc_path else []
    slot_rows = _read_csv(slot_path) if slot_path else []
    trip_rows = _read_csv(trip_path) if trip_path else []
    kpi = _read_json(kpi_path) if kpi_path else {}

    pv_generation = _sum(ledger_rows, "pv_generation_kwh")
    pv_balance = _sum(ledger_rows, "pv_to_bus_kwh") + _sum(ledger_rows, "pv_to_bess_kwh") + _sum(ledger_rows, "pv_curtail_kwh")
    ok = abs(pv_generation - pv_balance) <= 1.0e-6
    _report("PV balance", ok, f"generation={pv_generation:.6f}, balance={pv_balance:.6f}")
    if not ok:
        issues.append("PV balance")

    bus_charge_total = _sum(ledger_rows, "bus_charge_total_kwh")
    bus_charge_balance = _sum(ledger_rows, "grid_to_bus_kwh") + _sum(ledger_rows, "pv_to_bus_kwh") + _sum(ledger_rows, "bess_to_bus_kwh")
    ok = abs(bus_charge_total - bus_charge_balance) <= 1.0e-6
    _report("Bus charge balance", ok, f"total={bus_charge_total:.6f}, balance={bus_charge_balance:.6f}")
    if not ok:
        issues.append("Bus charge balance")

    kpi_pv = _safe_float(kpi.get("pv_generation_total_kwh", kpi.get("pv_generation_kwh")))
    ok = abs(kpi_pv - pv_generation) <= 1.0e-6
    _report("KPI consistency", ok, f"kpi={kpi_pv:.6f}, ledger={pv_generation:.6f}")
    if not ok:
        issues.append("KPI consistency")

    pv_vehicle = _sum(source_rows, "pv_to_vehicle_kwh")
    bess_vehicle = _sum(source_rows, "bess_to_vehicle_kwh")
    grid_vehicle = _sum(source_rows, "grid_to_vehicle_kwh")
    pv_bus = _sum(ledger_rows, "pv_to_bus_kwh")
    bess_bus = _sum(ledger_rows, "bess_to_bus_kwh")
    grid_bus = _sum(ledger_rows, "grid_to_bus_kwh")
    ok = abs(pv_vehicle - pv_bus) <= 1.0e-6 and abs(bess_vehicle - bess_bus) <= 1.0e-6 and abs(grid_vehicle - grid_bus) <= 1.0e-6
    _report(
        "Vehicle source allocation",
        ok,
        f"pv={pv_vehicle:.6f}/{pv_bus:.6f}, bess={bess_vehicle:.6f}/{bess_bus:.6f}, grid={grid_vehicle:.6f}/{grid_bus:.6f}",
    )
    if not ok:
        issues.append("Vehicle source allocation")

    if slot_path is None or not slot_rows:
        _report("Service distance", False, "vehicle_slot_ledger.csv missing or empty")
        issues.append("Service distance")
    else:
        trip_served_distance = _sum([row for row in trip_rows if str(row.get("served_flag", "")).strip().lower() in {"true", "1", "yes"}], "distance_km")
        slot_service_distance = _sum(slot_rows, "service_km")
        ok = abs(slot_service_distance - trip_served_distance) <= 1.0e-6
        _report("Service distance", ok, f"ledger={slot_service_distance:.6f}, trip_assignment={trip_served_distance:.6f}")
        if not ok:
            issues.append("Service distance")

    ok = bool(soc_rows)
    _report("SOC timeseries", ok, f"rows={len(soc_rows)}")
    if not ok:
        issues.append("SOC timeseries")

    if issues:
        raise SystemExit(1)

    print("[OK] output consistency checks passed")


if __name__ == "__main__":
    main()
