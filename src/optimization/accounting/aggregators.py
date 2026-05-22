from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Dict, Iterable, Mapping, Sequence


def _sum(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return float(sum(float(row.get(key, 0.0) or 0.0) for row in rows))


def _distinct_count(rows: Sequence[Mapping[str, Any]], key: str) -> int:
    return len({str(row.get(key) or "") for row in rows if str(row.get(key) or "").strip()})


def build_accounting_summary(
    *,
    vehicle_rows: Sequence[Mapping[str, Any]],
    energy_rows: Sequence[Mapping[str, Any]],
    trip_assignment_rows: Sequence[Mapping[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    metadata = dict(metadata or {})
    trip_assignment_rows = list(trip_assignment_rows or [])

    service_km = _sum(vehicle_rows, "service_km")
    deadhead_before_km = _sum(vehicle_rows, "deadhead_before_km")
    deadhead_after_km = _sum(vehicle_rows, "deadhead_after_km")
    deadhead_total_km = _sum(vehicle_rows, "deadhead_total_km")
    bev_drive_energy_kwh = _sum(vehicle_rows, "bev_drive_energy_kwh")
    total_charge_input_kwh = _sum(vehicle_rows, "charge_input_kwh")
    fuel_cost_jpy = _sum(vehicle_rows, "fuel_cost_jpy")
    co2_cost_jpy = _sum(vehicle_rows, "co2_cost_jpy")
    battery_degradation_cost_jpy = _sum(vehicle_rows, "battery_degradation_cost_jpy")
    electricity_cost_jpy = _sum(energy_rows, "energy_cost_jpy")
    contract_overage_cost_jpy = _sum(energy_rows, "contract_overage_cost_jpy")

    peak_grid_kw = max((float(row.get("grid_kw", 0.0) or 0.0) for row in energy_rows), default=0.0)
    demand_rate = max((float(row.get("demand_rate_jpy_per_kw", 0.0) or 0.0) for row in energy_rows), default=0.0)
    demand_cost_jpy = peak_grid_kw * demand_rate

    pv_generation_kwh = _sum(energy_rows, "pv_generation_kwh")
    pv_to_bus_kwh = _sum(energy_rows, "pv_to_bus_kwh")
    pv_to_bess_kwh = _sum(energy_rows, "pv_to_bess_kwh")
    pv_curtailed_kwh = _sum(energy_rows, "pv_curtailed_kwh")
    bess_to_bus_kwh = _sum(energy_rows, "bess_to_bus_kwh")
    grid_to_bus_kwh = _sum(energy_rows, "grid_to_bus_kwh")
    grid_to_bess_kwh = _sum(energy_rows, "grid_to_bess_kwh")
    grid_total_kwh = _sum(energy_rows, "grid_total_kwh")
    pv_utilization_ratio = (pv_to_bus_kwh + pv_to_bess_kwh) / pv_generation_kwh if pv_generation_kwh > 0 else 0.0

    soc_start_values = [float(row.get("soc_start_ratio", 0.0) or 0.0) for row in vehicle_rows]
    soc_end_values = [float(row.get("soc_end_ratio", 0.0) or 0.0) for row in vehicle_rows]
    min_soc_ratio = min(soc_end_values + soc_start_values) if (soc_start_values or soc_end_values) else 0.0
    mean_soc_ratio = mean(soc_end_values) if soc_end_values else 0.0
    final_min_soc_ratio = min(soc_end_values) if soc_end_values else 0.0
    final_mean_soc_ratio = mean(soc_end_values) if soc_end_values else 0.0

    used_vehicle_count = _distinct_count(vehicle_rows, "vehicle_id")
    available_vehicle_count = int(metadata.get("available_vehicle_count", used_vehicle_count) or used_vehicle_count)
    operator_id = str(metadata.get("operator_id") or "")
    scenario_id = str(metadata.get("scenario_id") or "")
    run_id = str(metadata.get("run_id") or "")
    service_date = str(metadata.get("service_date") or "")
    weather_date = str(metadata.get("weather_date") or service_date)

    served_trip_count = _distinct_count(trip_assignment_rows, "trip_id") if trip_assignment_rows else _distinct_count(vehicle_rows, "trip_id")
    unserved_trip_count = int(metadata.get("unserved_trip_count", 0) or 0)
    bev_trip_count = len({str(row.get("trip_id") or "") for row in vehicle_rows if str(row.get("vehicle_type") or "").upper() == "BEV" and str(row.get("trip_id") or "")})
    ice_trip_count = len({str(row.get("trip_id") or "") for row in vehicle_rows if str(row.get("vehicle_type") or "").upper() == "ICE" and str(row.get("trip_id") or "")})

    total_cost_jpy = electricity_cost_jpy + demand_cost_jpy + fuel_cost_jpy + co2_cost_jpy + battery_degradation_cost_jpy + contract_overage_cost_jpy
    objective_value = float(metadata.get("objective_value", total_cost_jpy) or total_cost_jpy)

    summary = {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "service_date": service_date,
        "weather_date": weather_date,
        "operator_id": operator_id,
        "total_cost_jpy": total_cost_jpy,
        "objective_value_jpy": objective_value,
        "energy_cost_jpy": electricity_cost_jpy,
        "demand_cost_jpy": demand_cost_jpy,
        "fuel_cost_jpy": fuel_cost_jpy,
        "co2_cost_jpy": co2_cost_jpy,
        "battery_degradation_cost_jpy": battery_degradation_cost_jpy,
        "contract_overage_cost_jpy": contract_overage_cost_jpy,
        "served_trip_count": served_trip_count,
        "unserved_trip_count": unserved_trip_count,
        "bev_trip_count": bev_trip_count,
        "ice_trip_count": ice_trip_count,
        "used_vehicle_count": used_vehicle_count,
        "available_vehicle_count": available_vehicle_count,
        "vehicle_utilization_ratio": used_vehicle_count / available_vehicle_count if available_vehicle_count > 0 else 0.0,
        "service_km": service_km,
        "deadhead_before_km": deadhead_before_km,
        "deadhead_after_km": deadhead_after_km,
        "deadhead_total_km": deadhead_total_km,
        "pv_generation_kwh": pv_generation_kwh,
        "pv_to_bus_kwh": pv_to_bus_kwh,
        "pv_to_bess_kwh": pv_to_bess_kwh,
        "pv_curtailed_kwh": pv_curtailed_kwh,
        "pv_utilization_ratio": pv_utilization_ratio,
        "bess_to_bus_kwh": bess_to_bus_kwh,
        "grid_to_bus_kwh": grid_to_bus_kwh,
        "grid_to_bess_kwh": grid_to_bess_kwh,
        "grid_total_kwh": grid_total_kwh,
        "peak_grid_kw": peak_grid_kw,
        "total_charge_input_kwh": total_charge_input_kwh,
        "bev_drive_energy_kwh": bev_drive_energy_kwh,
        "min_soc_ratio": min_soc_ratio,
        "mean_soc_ratio": mean_soc_ratio,
        "final_min_soc_ratio": final_min_soc_ratio,
        "final_mean_soc_ratio": final_mean_soc_ratio,
        "objective_is_actual_cost": bool(metadata.get("objective_is_actual_cost", False)),
        "supports_exact_milp": bool(metadata.get("supports_exact_milp", False)),
        "fallback_applied": bool(metadata.get("fallback_applied", False)),
        "charging_source_provenance_exact": bool(metadata.get("charging_source_provenance_exact", False)),
        "contract_power_kw": float(metadata.get("contract_power_kw", 0.0) or 0.0),
        "contract_power_exceeded": bool(metadata.get("contract_power_exceeded", False)),
        "contract_overage_kw": float(metadata.get("contract_overage_kw", 0.0) or 0.0),
        "contract_power_mode": str(metadata.get("contract_power_mode", "report_only") or "report_only"),
        "solver_status": str(metadata.get("solver_status", "") or ""),
        "mip_gap_requested_ratio": metadata.get("mip_gap_requested_ratio"),
        "mip_gap_requested_percent": metadata.get("mip_gap_requested_percent"),
        "mip_gap_achieved_ratio": metadata.get("mip_gap_achieved_ratio"),
        "mip_gap_achieved_percent": metadata.get("mip_gap_achieved_percent"),
    }
    return summary

