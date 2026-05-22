from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


def _sum(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return float(sum(float(row.get(key, 0.0) or 0.0) for row in rows))


def validate_accounting_artifacts(
    *,
    vehicle_rows: Sequence[Mapping[str, Any]],
    energy_rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    strict: bool = False,
) -> list[str]:
    issues: list[str] = []

    pv_generation = _sum(energy_rows, "pv_generation_kwh")
    pv_balance = _sum(energy_rows, "pv_to_bus_kwh") + _sum(energy_rows, "pv_to_bess_kwh") + _sum(energy_rows, "pv_curtailed_kwh")
    if abs(pv_generation - pv_balance) > 1.0e-6:
        issues.append(f"PV conservation failed: generation={pv_generation:.6f}, balance={pv_balance:.6f}")

    grid_total = _sum(energy_rows, "grid_total_kwh")
    grid_balance = _sum(energy_rows, "grid_to_bus_kwh") + _sum(energy_rows, "grid_to_bess_kwh") + _sum(energy_rows, "depot_aux_grid_kwh")
    if abs(grid_total - grid_balance) > 1.0e-6:
        issues.append(f"Grid conservation failed: total={grid_total:.6f}, balance={grid_balance:.6f}")

    total_charge = _sum(vehicle_rows, "charge_input_kwh")
    soc_balance = 0.0
    for row in vehicle_rows:
        soc_start = float(row.get("soc_start_ratio", 0.0) or 0.0)
        soc_end = float(row.get("soc_end_ratio", 0.0) or 0.0)
        soc_balance += soc_end - soc_start - float(row.get("soc_delta_charge_ratio", 0.0) or 0.0) + float(row.get("soc_delta_drive_ratio", 0.0) or 0.0) + float(row.get("soc_delta_loss_ratio", 0.0) or 0.0)
    if abs(soc_balance) > 1.0e-6:
        issues.append(f"SOC conservation failed: residual={soc_balance:.6f}")
    if total_charge < -1.0e-9:
        issues.append("Charge input sum is negative.")

    expected_peak = max((float(row.get("grid_kw", 0.0) or 0.0) for row in energy_rows), default=0.0)
    actual_peak = float(summary.get("peak_grid_kw", 0.0) or 0.0)
    if abs(expected_peak - actual_peak) > 1.0e-6:
        issues.append(f"Peak grid mismatch: expected={expected_peak:.6f}, actual={actual_peak:.6f}")

    return issues

