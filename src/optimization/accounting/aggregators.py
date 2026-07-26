from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Dict, Iterable, Mapping, Sequence

from src.optimization.common.cost_components import normalize_cost_component_flags


def _sum(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return float(sum(float(row.get(key, 0.0) or 0.0) for row in rows))


def _distinct_count(rows: Sequence[Mapping[str, Any]], key: str) -> int:
    return len({str(row.get(key) or "") for row in rows if str(row.get(key) or "").strip()})


def _is_served_assignment(row: Mapping[str, Any]) -> bool:
    served = str(row.get("served_flag", True)).strip().lower()
    return served not in {"false", "0", "no"} and bool(
        str(row.get("assigned_vehicle_id") or row.get("vehicle_id") or "").strip()
    )


def _assignment_vehicle_id(row: Mapping[str, Any]) -> str:
    return str(row.get("assigned_vehicle_id") or row.get("vehicle_id") or "").strip()


def _assignment_vehicle_type(row: Mapping[str, Any]) -> str:
    return str(row.get("assigned_vehicle_type") or row.get("vehicle_type") or "").strip().upper()


def _assignment_service_date(row: Mapping[str, Any], fallback: str) -> str:
    for key in ("actual_departure", "scheduled_departure", "service_date", "slot_start"):
        value = str(row.get(key) or "").strip()
        if value:
            return value[:10]
    return fallback[:10]


def build_accounting_summary(
    *,
    vehicle_rows: Sequence[Mapping[str, Any]],
    vehicle_energy_rows: Sequence[Mapping[str, Any]] | None = None,
    energy_rows: Sequence[Mapping[str, Any]],
    trip_assignment_rows: Sequence[Mapping[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    metadata = dict(metadata or {})
    component_flags = normalize_cost_component_flags(
        metadata.get("cost_component_flags")
    )
    vehicle_energy_rows = list(vehicle_energy_rows or [])
    trip_assignment_rows = list(trip_assignment_rows or [])

    service_km = _sum(vehicle_rows, "service_km")
    deadhead_before_km = _sum(vehicle_rows, "deadhead_before_km")
    deadhead_after_km = _sum(vehicle_rows, "deadhead_after_km")
    deadhead_total_km = _sum(vehicle_rows, "deadhead_total_km")
    bev_drive_energy_kwh = _sum(vehicle_rows, "bev_drive_energy_kwh")
    total_charge_input_kwh = _sum(vehicle_rows, "charge_input_kwh")
    bev_charge_to_battery_kwh = _sum(vehicle_rows, "charge_to_battery_kwh")
    bev_charge_loss_kwh = _sum(vehicle_rows, "charge_loss_kwh")
    ice_fuel_consumed_l = _sum(vehicle_energy_rows, "fuel_consumed_l") if vehicle_energy_rows else _sum(vehicle_rows, "ice_fuel_liter")
    ice_refueled_l = _sum(vehicle_energy_rows, "refuel_l") if vehicle_energy_rows else _sum(vehicle_rows, "refuel_l")
    fuel_cost_jpy = _sum(vehicle_rows, "fuel_cost_jpy")
    ice_co2_kg = (
        _sum(vehicle_energy_rows, "ice_co2_kg")
        if vehicle_energy_rows
        else _sum(vehicle_rows, "ice_co2_kg")
    )
    electricity_co2_kg = sum(
        float(row.get("grid_import_kwh", row.get("grid_total_kwh", 0.0)) or 0.0)
        * float(row.get("grid_emission_factor_kg_per_kwh", 0.0) or 0.0)
        for row in energy_rows
    )
    total_co2_kg = ice_co2_kg + electricity_co2_kg
    co2_price_jpy_per_kg = max(
        float(metadata.get("co2_price_jpy_per_kg", 0.0) or 0.0),
        0.0,
    )
    co2_cost_jpy = (
        total_co2_kg * co2_price_jpy_per_kg
        if component_flags["co2_cost"]
        else 0.0
    )
    battery_degradation_cost_jpy = _sum(vehicle_rows, "battery_degradation_cost_jpy")
    grid_energy_cost_jpy = _sum(energy_rows, "energy_cost_jpy")
    bess_total_flow_cost_jpy = _sum(energy_rows, "bess_total_flow_cost_jpy")
    electricity_cost_jpy = grid_energy_cost_jpy + bess_total_flow_cost_jpy
    contract_overage_cost_jpy = _sum(energy_rows, "contract_overage_cost_jpy")

    peak_grid_kw = max((float(row.get("grid_kw", 0.0) or 0.0) for row in energy_rows), default=0.0)
    demand_rate = max((float(row.get("demand_rate_jpy_per_kw", 0.0) or 0.0) for row in energy_rows), default=0.0)
    demand_cost_jpy = peak_grid_kw * demand_rate

    pv_generation_kwh = _sum(energy_rows, "pv_generation_kwh")
    pv_to_bus_kwh = _sum(energy_rows, "pv_to_bus_kwh")
    pv_to_bess_kwh = _sum(energy_rows, "pv_to_bess_kwh")
    pv_curtailed_kwh = _sum(energy_rows, "pv_curtailed_kwh")
    bess_to_bus_kwh = _sum(energy_rows, "bess_to_bus_kwh")
    bess_charge_kwh = _sum(energy_rows, "bess_charge_kwh")
    bess_discharge_kwh = _sum(energy_rows, "bess_discharge_kwh")
    pv_to_bus_cost_jpy = _sum(energy_rows, "pv_to_bus_cost_jpy")
    pv_to_bess_cost_jpy = _sum(energy_rows, "pv_to_bess_cost_jpy")
    bess_to_bus_cost_jpy = _sum(energy_rows, "bess_to_bus_cost_jpy")
    bess_unit_cost = max((float(row.get("bess_to_bus_unit_cost_jpy_per_kwh", 0.0) or 0.0) for row in energy_rows), default=0.0)
    bess_soc_violation_kwh = _sum(energy_rows, "bess_soc_violation_kwh")
    bess_soc_violation_count = sum(1 for row in energy_rows if float(row.get("bess_soc_violation_kwh", 0.0) or 0.0) > 1.0e-9)
    bess_capacity_kwh = max((float(row.get("bess_capacity_kwh", 0.0) or 0.0) for row in energy_rows), default=0.0)
    bess_initial_soc_kwh = next((float(row.get("bess_soc_start_kwh", 0.0) or 0.0) for row in energy_rows if float(row.get("bess_soc_start_kwh", 0.0) or 0.0) > 0.0), 0.0)
    bess_final_soc_kwh = float(energy_rows[-1].get("bess_soc_end_kwh", 0.0) or 0.0) if energy_rows else 0.0
    bess_soc_min_kwh = max((float(row.get("bess_soc_min_kwh", 0.0) or 0.0) for row in energy_rows), default=0.0)
    bess_soc_max_kwh = max((float(row.get("bess_soc_max_kwh", 0.0) or 0.0) for row in energy_rows), default=0.0)
    grid_to_bus_kwh = _sum(energy_rows, "grid_to_bus_kwh")
    grid_to_bess_kwh = _sum(energy_rows, "grid_to_bess_kwh")
    grid_total_kwh = _sum(energy_rows, "grid_import_kwh") or _sum(energy_rows, "grid_total_kwh")
    bus_charging_total_kwh = grid_to_bus_kwh + pv_to_bus_kwh + bess_to_bus_kwh
    pv_utilization_ratio = (pv_to_bus_kwh + pv_to_bess_kwh) / pv_generation_kwh if pv_generation_kwh > 0 else 0.0

    bev_vehicle_rows = [
        row
        for row in vehicle_rows
        if str(row.get("vehicle_type") or "").strip().upper() == "BEV"
    ]
    soc_start_values = [float(row.get("soc_start_ratio", 0.0) or 0.0) for row in bev_vehicle_rows]
    soc_end_values = [float(row.get("soc_end_ratio", 0.0) or 0.0) for row in bev_vehicle_rows]
    min_soc_ratio = min(soc_end_values + soc_start_values) if (soc_start_values or soc_end_values) else 0.0
    mean_soc_ratio = mean(soc_end_values) if soc_end_values else 0.0
    final_min_soc_ratio = min(soc_end_values) if soc_end_values else 0.0
    final_mean_soc_ratio = mean(soc_end_values) if soc_end_values else 0.0

    served_assignments = [row for row in trip_assignment_rows if _is_served_assignment(row)]
    if trip_assignment_rows:
        used_vehicle_ids = {_assignment_vehicle_id(row) for row in served_assignments}
        used_vehicle_count = len(used_vehicle_ids)
        used_vehicle_day_count = len(
            {
                (
                    _assignment_vehicle_id(row),
                    _assignment_service_date(row, str(metadata.get("service_date") or "")),
                )
                for row in served_assignments
            }
        )
    else:
        used_vehicle_count = _distinct_count(vehicle_rows, "vehicle_id")
        used_vehicle_day_count = len({
            (str(row.get("vehicle_id") or ""), str(row.get("slot_start") or "")[:10])
            for row in vehicle_rows
            if str(row.get("vehicle_id") or "").strip() and str(row.get("trip_id") or "").strip()
        })
    available_vehicle_count = int(metadata.get("available_vehicle_count", used_vehicle_count) or used_vehicle_count)
    operator_id = str(metadata.get("operator_id") or "UNKNOWN_OPERATOR")
    scenario_id = str(metadata.get("scenario_id") or "")
    run_id = str(metadata.get("run_id") or "")
    service_date = str(metadata.get("service_date") or "")
    weather_date = str(metadata.get("weather_date") or service_date)

    served_trip_count = _distinct_count(served_assignments, "trip_id") if trip_assignment_rows else _distinct_count(vehicle_rows, "trip_id")
    unserved_trip_count = (
        _distinct_count(
            [row for row in trip_assignment_rows if not _is_served_assignment(row)],
            "trip_id",
        )
        if trip_assignment_rows
        else int(metadata.get("unserved_trip_count", 0) or 0)
    )
    trip_count_source = served_assignments if trip_assignment_rows else vehicle_rows
    bev_trip_count = len({
        str(row.get("trip_id") or "")
        for row in trip_count_source
        if _assignment_vehicle_type(row) == "BEV" and str(row.get("trip_id") or "")
    })
    ice_trip_count = len({
        str(row.get("trip_id") or "")
        for row in trip_count_source
        if _assignment_vehicle_type(row) == "ICE" and str(row.get("trip_id") or "")
    })

    vehicle_usage_unit_cost = float(metadata.get("vehicle_usage_cost_jpy_per_used_bus", 0.0) or 0.0)
    vehicle_usage_cost_jpy = used_vehicle_day_count * vehicle_usage_unit_cost
    if not component_flags["vehicle_usage_cost"]:
        vehicle_usage_cost_jpy = 0.0
    total_cost_jpy = electricity_cost_jpy + demand_cost_jpy + fuel_cost_jpy + co2_cost_jpy + battery_degradation_cost_jpy + contract_overage_cost_jpy + vehicle_usage_cost_jpy
    solver_objective_matches_accounting_total = bool(
        metadata.get("solver_objective_matches_accounting_total", False)
    )
    objective_is_actual_cost = bool(metadata.get("objective_is_actual_cost", False))
    objective_value = total_cost_jpy if objective_is_actual_cost else float(metadata.get("objective_value", total_cost_jpy) or total_cost_jpy)
    solver_status = str(metadata.get("solver_status", "") or "")
    solver_objective_value = objective_value
    phase = str(metadata.get("phase", "") or "").strip().lower()
    validated_status = solver_status.upper() in {
        "OPTIMAL",
        "FEASIBLE",
        "SOLVED_FEASIBLE",
    } and phase != "phase2_assignment_only"
    research_gate = (
        not bool(metadata.get("research_run", False))
        or bool(metadata.get("research_run_accepted", False))
    )
    full_operational_validation = bool(
        metadata.get("full_operational_validation", phase != "phase2_assignment_only")
    )
    validated_operating_cost_jpy = (
        total_cost_jpy
        if validated_status
        and research_gate
        and full_operational_validation
        and bool(metadata.get("validated_feasible", True))
        else None
    )
    fallback_statuses = {"BASELINE_FALLBACK", "PARTIAL_BASELINE_FALLBACK"}
    is_optimization_result = bool(solver_status.upper() not in fallback_statuses and not bool(metadata.get("fallback_applied", False)))
    summary = {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "service_date": service_date,
        "weather_date": weather_date,
        "weather_reference_date": str(metadata.get("weather_reference_date", weather_date) or weather_date),
        "weather_profile": str(metadata.get("weather_profile", metadata.get("operation_mode", "")) or ""),
        "operation_mode": str(metadata.get("operation_mode", "") or ""),
        "run_created_at": str(metadata.get("run_created_at", "") or ""),
        "output_generated_at": str(metadata.get("output_generated_at", "") or ""),
        "operator_id": operator_id,
        "cost_component_flags": dict(component_flags),
        "canonical_fuel_cost_jpy": metadata.get("canonical_fuel_cost_jpy"),
        "canonical_ice_co2_kg": metadata.get("canonical_ice_co2_kg"),
        "timestep_min": int(metadata.get("slot_minutes", 0) or 0),
        "num_periods": int(metadata.get("num_periods", len(energy_rows)) or len(energy_rows)),
        "planning_horizon_hours": float(metadata.get("planning_horizon_hours", (int(metadata.get("slot_minutes", 0) or 0) * max(len(energy_rows), 1) / 60.0 if energy_rows else 0.0)) or 0.0),
        "total_cost_jpy": total_cost_jpy,
        "accounting_total_cost_jpy": total_cost_jpy,
        "gross_operating_cost_jpy": total_cost_jpy,
        "reported_total_cost_jpy": total_cost_jpy,
        "objective_value": objective_value,
        "objective_value_jpy": objective_value,
        "solver_objective_value": solver_objective_value,
        "validated_operating_cost_jpy": validated_operating_cost_jpy,
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
        "used_vehicle_day_count": used_vehicle_day_count,
        "vehicle_usage_cost_jpy": vehicle_usage_cost_jpy,
        "vehicle_usage_cost_jpy_per_used_bus": vehicle_usage_unit_cost,
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
        "pv_curtailment_kwh": pv_curtailed_kwh,
        "pv_export_kwh": 0.0,
        "pv_utilization_ratio": pv_utilization_ratio,
        "bess_to_bus_kwh": bess_to_bus_kwh,
        "bess_charge_kwh": bess_charge_kwh,
        "bess_discharge_to_bus_kwh": bess_to_bus_kwh,
        "bess_discharge_kwh": bess_discharge_kwh,
        "bess_to_bus_unit_cost_jpy_per_kwh": bess_unit_cost,
        "pv_to_bess_cost_jpy": pv_to_bess_cost_jpy,
        "pv_to_bus_cost_jpy": pv_to_bus_cost_jpy,
        "bess_to_bus_cost_jpy": bess_to_bus_cost_jpy,
        "bess_total_flow_cost_jpy": bess_total_flow_cost_jpy,
        "bess_soc_violation_count": bess_soc_violation_count,
        "bess_soc_violation_kwh": bess_soc_violation_kwh,
        "bess": {
            "enabled": bool(bess_capacity_kwh > 0.0 or bess_charge_kwh > 0.0 or bess_discharge_kwh > 0.0),
            "capacity_kwh": bess_capacity_kwh,
            "initial_soc_kwh": bess_initial_soc_kwh,
            "final_soc_kwh": bess_final_soc_kwh,
            "soc_min_kwh": bess_soc_min_kwh,
            "soc_max_kwh": bess_soc_max_kwh,
            "pv_to_bess_kwh": pv_to_bess_kwh,
            "grid_to_bess_kwh": grid_to_bess_kwh,
            "bess_to_bus_kwh": bess_to_bus_kwh,
            "bess_charge_kwh": bess_charge_kwh,
            "bess_discharge_kwh": bess_discharge_kwh,
            "bess_to_bus_unit_cost_jpy_per_kwh": bess_unit_cost,
            "pv_to_bess_cost_jpy": pv_to_bess_cost_jpy,
            "pv_to_bus_cost_jpy": pv_to_bus_cost_jpy,
            "bess_to_bus_cost_jpy": bess_to_bus_cost_jpy,
            "bess_total_flow_cost_jpy": bess_total_flow_cost_jpy,
            "soc_violation_count": bess_soc_violation_count,
            "soc_violation_kwh": bess_soc_violation_kwh,
        },
        "grid_to_bus_kwh": grid_to_bus_kwh,
        "grid_to_bess_kwh": grid_to_bess_kwh,
        "grid_total_kwh": grid_total_kwh,
        "grid_import_kwh": grid_total_kwh,
        "facility_load_kwh": 0.0,
        "grid_purchase_cost_jpy": grid_energy_cost_jpy,
        "demand_charge_cost_jpy": demand_cost_jpy,
        "peak_grid_import_kw": peak_grid_kw,
        "peak_grid_kw": peak_grid_kw,
        "bus_charging_total_kwh": bus_charging_total_kwh,
        "total_charge_input_kwh": total_charge_input_kwh,
        "bev_charge_input_kwh": total_charge_input_kwh,
        "bev_charge_to_battery_kwh": bev_charge_to_battery_kwh,
        "bev_charge_loss_kwh": bev_charge_loss_kwh,
        "bev_drive_energy_kwh": bev_drive_energy_kwh,
        "bev_drive_consumption_kwh": bev_drive_energy_kwh,
        "ice_fuel_consumed_l": ice_fuel_consumed_l,
        "ice_fuel_l": ice_fuel_consumed_l,
        "ice_refueled_l": ice_refueled_l,
        "ice_co2_kg": ice_co2_kg,
        "electricity_co2_kg": electricity_co2_kg,
        "grid_co2_kg": electricity_co2_kg,
        "fuel_co2_kg": ice_co2_kg,
        "total_co2_kg": total_co2_kg,
        "min_soc_ratio": min_soc_ratio,
        "mean_soc_ratio": mean_soc_ratio,
        "final_min_soc_ratio": final_min_soc_ratio,
        "final_mean_soc_ratio": final_mean_soc_ratio,
        "objective_is_actual_cost": objective_is_actual_cost,
        "solver_objective_matches_accounting_total": solver_objective_matches_accounting_total,
        "objective_semantics": str(metadata.get("objective_semantics", "single_solver_objective") or "single_solver_objective"),
        "supports_exact_milp": bool(metadata.get("supports_exact_milp", False)),
        "fallback_applied": bool(metadata.get("fallback_applied", False)),
        "is_optimization_result": is_optimization_result,
        "result_interpretation": "baseline_fallback_result" if solver_status.upper() in fallback_statuses else "optimization_result",
        # The legacy name means vehicle-level exactness here; site/depot source
        # totals are emitted separately because proportional vehicle allocation
        # is an inference even when the underlying depot/time-slot flow is exact.
        "charging_source_provenance_exact": bool(metadata.get("charging_source_provenance_exact", False)),
        "vehicle_source_provenance_exact": bool(
            metadata.get("vehicle_source_provenance_exact", metadata.get("charging_source_provenance_exact", False))
        ),
        "depot_source_provenance_exact": bool(
            metadata.get("depot_source_provenance_exact", False)
        ),
        "charging_source_provenance_scope": "vehicle_timestep",
        "vehicle_charging_source_allocation_method": str(metadata.get("vehicle_charging_source_allocation_method", "proportional_by_timestep") or "proportional_by_timestep"),
        "vehicle_charging_source_is_solver_native": bool(metadata.get("vehicle_charging_source_is_solver_native", False)),
        "contract_power_kw": float(metadata.get("contract_power_kw", 0.0) or 0.0),
        "contract_power_exceeded": bool(metadata.get("contract_power_exceeded", False)),
        "contract_overage_kw": float(metadata.get("contract_overage_kw", 0.0) or 0.0),
        "contract_power_mode": str(metadata.get("contract_power_mode", "report_only") or "report_only"),
        "solver_status": solver_status,
        "cost_definition": {
            "gross_operating_cost_jpy": "real cost terms only",
            "accounting_total_cost_jpy": "sum of canonical accounting ledger terms",
            "solver_objective_value": "solver-reported objective; may include terms outside accounting",
            "validated_operating_cost_jpy": "accounting total only when solver status and independent validation are feasible; otherwise null",
            "objective_value": "solver objective including penalties and bonuses",
            "reported_total_cost_jpy": "UI/reporting value; see included terms",
            "objective_is_actual_cost": objective_is_actual_cost,
            "solver_objective_matches_accounting_total": solver_objective_matches_accounting_total,
        },
"mip_gap_requested_ratio": metadata.get("mip_gap_requested_ratio"),
        "mip_gap_requested_percent": metadata.get("mip_gap_requested_percent"),
        "mip_gap_achieved_ratio": metadata.get("mip_gap_achieved_ratio"),
        "mip_gap_achieved_percent": metadata.get("mip_gap_achieved_percent"),
        "stage1_mip_gap": metadata.get("stage1_mip_gap"),
        "stage2_mip_gap": metadata.get("stage2_mip_gap"),
        "supports_two_stage_milp": metadata.get("supports_two_stage_milp"),
        "supports_integrated_exact_milp": metadata.get("supports_integrated_exact_milp"),
        "optimization_structure": metadata.get("optimization_structure"),
    }
    return summary

