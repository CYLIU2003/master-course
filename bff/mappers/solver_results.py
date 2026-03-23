from __future__ import annotations

from typing import Any, Dict, List

from src.milp_model import MILPResult
from src.simulator import FeasibilityIssue, FeasibilityReport, SimulationResult


def serialize_milp_result(result: MILPResult) -> Dict[str, Any]:
    return {
        "status": result.status,
        "objective_value": result.objective_value,
        "solve_time_seconds": result.solve_time_sec,
        "mip_gap": result.mip_gap,
        "assignment": result.assignment,
        "soc_series": result.soc_series,
        "charge_schedule": result.charge_schedule,
        "charge_power_kw": result.charge_power_kw,
        "refuel_schedule_l": result.refuel_schedule_l,
        "grid_import_kw": result.grid_import_kw,
        "pv_used_kw": result.pv_used_kw,
        "peak_demand_kw": result.peak_demand_kw,
        "obj_breakdown": result.obj_breakdown,
        "unserved_tasks": result.unserved_tasks,
        "infeasibility_info": result.infeasibility_info,
    }


def deserialize_milp_result(payload: Dict[str, Any]) -> MILPResult:
    return MILPResult(
        status=str(payload.get("status") or "UNKNOWN"),
        objective_value=payload.get("objective_value"),
        solve_time_sec=float(payload.get("solve_time_seconds") or 0.0),
        mip_gap=payload.get("mip_gap"),
        assignment=dict(payload.get("assignment") or {}),
        soc_series=dict(payload.get("soc_series") or {}),
        charge_schedule=dict(payload.get("charge_schedule") or {}),
        charge_power_kw=dict(payload.get("charge_power_kw") or {}),
        refuel_schedule_l=dict(payload.get("refuel_schedule_l") or {}),
        grid_import_kw=dict(payload.get("grid_import_kw") or {}),
        pv_used_kw=dict(payload.get("pv_used_kw") or {}),
        peak_demand_kw=dict(payload.get("peak_demand_kw") or {}),
        obj_breakdown=dict(payload.get("obj_breakdown") or {}),
        unserved_tasks=list(payload.get("unserved_tasks") or []),
        infeasibility_info=str(payload.get("infeasibility_info") or ""),
    )


def _serialize_feasibility_report(report: FeasibilityReport | None) -> Dict[str, Any] | None:
    if report is None:
        return None
    issues: List[Dict[str, Any]] = []
    for issue in report.issues:
        issues.append(
            {
                "category": issue.category,
                "severity": issue.severity,
                "vehicle_id": issue.vehicle_id,
                "task_id": issue.task_id,
                "time_idx": issue.time_idx,
                "detail": issue.detail,
            }
        )
    return {
        "feasible": report.feasible,
        "trip_coverage_ok": report.trip_coverage_ok,
        "time_connection_ok": report.time_connection_ok,
        "soc_ok": report.soc_ok,
        "charger_ok": report.charger_ok,
        "grid_limit_ok": report.grid_limit_ok,
        "end_soc_ok": report.end_soc_ok,
        "issues": issues,
    }


def serialize_simulation_result(result: SimulationResult) -> Dict[str, Any]:
    feasibility = _serialize_feasibility_report(result.feasibility_report)
    return {
        "total_operating_cost": result.total_operating_cost,
        "total_energy_cost": result.total_energy_cost,
        "total_demand_charge": result.total_demand_charge,
        "total_degradation_cost": result.total_degradation_cost,
        "total_fuel_cost": result.total_fuel_cost,
        "total_co2_kg": result.total_co2_kg,
        "pv_self_consumption_ratio": result.pv_self_consumption_ratio,
        "total_pv_kwh": result.total_pv_kwh,
        "total_grid_kwh": result.total_grid_kwh,
        "peak_demand_kw": result.peak_demand_kw,
        "charger_utilization": result.charger_utilization,
        "vehicle_utilization": result.vehicle_utilization,
        "served_task_ratio": result.served_task_ratio,
        "unserved_tasks": result.unserved_tasks,
        "soc_min_kwh": result.soc_min_kwh,
        "soc_violations": result.soc_violations,
        "infeasibility_penalty_total": result.infeasibility_penalty_total,
        "grid_import_kw_series": result.grid_import_kw_series,
        "pv_used_kw_series": result.pv_used_kw_series,
        "feasibility_report": feasibility,
        "feasibility_violations": (feasibility or {}).get("issues", []),
    }
