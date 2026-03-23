from __future__ import annotations

from typing import Any, Dict, List

from .problem import AssignmentPlan, OptimizationEngineResult


class ResultSerializer:
    @staticmethod
    def serialize_plan(plan: AssignmentPlan) -> Dict[str, Any]:
        duties: List[Dict[str, Any]] = []
        for duty in plan.duties:
            duties.append(
                {
                    "duty_id": duty.duty_id,
                    "vehicle_type": duty.vehicle_type,
                    "trip_ids": duty.trip_ids,
                    "legs": [
                        {
                            "trip_id": leg.trip.trip_id,
                            "deadhead_from_prev_min": leg.deadhead_from_prev_min,
                        }
                        for leg in duty.legs
                    ],
                }
            )

        return {
            "duties": duties,
            "vehicle_paths": {duty_id: list(trip_ids) for duty_id, trip_ids in plan.vehicle_paths().items()},
            "charging_schedule": [
                {
                    "vehicle_id": slot.vehicle_id,
                    "slot_index": slot.slot_index,
                    "charger_id": slot.charger_id,
                    "charge_kw": slot.charge_kw,
                    "discharge_kw": slot.discharge_kw,
                }
                for slot in plan.charging_slots
            ],
            "served_trip_ids": list(plan.served_trip_ids),
            "unserved_trip_ids": list(plan.unserved_trip_ids),
            "metadata": dict(plan.metadata),
        }

    @classmethod
    def serialize_result(cls, result: OptimizationEngineResult) -> Dict[str, Any]:
        cost_breakdown = dict(result.cost_breakdown)
        solver_metadata = dict(result.solver_metadata)
        objective_weights = dict(solver_metadata.get("objective_weights") or {})
        raw_components = {
            "energy_cost": float(cost_breakdown.get("energy_cost", 0.0) or 0.0),
            "demand_cost": float(cost_breakdown.get("demand_cost", 0.0) or 0.0),
            "vehicle_cost": float(cost_breakdown.get("vehicle_cost", 0.0) or 0.0),
            "unserved_penalty": float(cost_breakdown.get("unserved_penalty", 0.0) or 0.0),
            "switch_cost": float(cost_breakdown.get("switch_cost", 0.0) or 0.0),
            "deviation_cost": float(cost_breakdown.get("deviation_cost", 0.0) or 0.0),
            "degradation_cost": float(cost_breakdown.get("degradation_cost", 0.0) or 0.0),
            "co2_cost": float(cost_breakdown.get("co2_cost", 0.0) or 0.0),
        }
        weighted_components = {
            "energy_cost": raw_components["energy_cost"] * float(objective_weights.get("electricity_cost", 1.0) or 1.0),
            "demand_cost": raw_components["demand_cost"] * float(objective_weights.get("demand_charge_cost", 1.0) or 1.0),
            "vehicle_cost": raw_components["vehicle_cost"] * float(objective_weights.get("vehicle_fixed_cost", 1.0) or 1.0),
            "unserved_penalty": raw_components["unserved_penalty"] * float(objective_weights.get("unserved_penalty", 1.0) or 1.0),
            "switch_cost": raw_components["switch_cost"] * float(objective_weights.get("switch_cost", 1.0) or 1.0),
            "deviation_cost": raw_components["deviation_cost"] * float(objective_weights.get("deviation_cost", 1.0) or 1.0),
            "degradation_cost": raw_components["degradation_cost"] * float(objective_weights.get("degradation", 1.0) or 1.0),
            "co2_cost": raw_components["co2_cost"] * float(objective_weights.get("emission_cost", 1.0) or 1.0),
        }
        fleet_size = len(result.plan.vehicle_paths())
        used_vehicle_count = sum(1 for trip_ids in result.plan.vehicle_paths().values() if trip_ids)
        utilization_ratio = float(used_vehicle_count) / float(fleet_size) if fleet_size > 0 else 0.0
        return {
            "solver_mode": result.mode.value,
            "solver_status": result.solver_status,
            "objective_mode": solver_metadata.get("objective_mode", "total_cost"),
            "objective_value": result.objective_value,
            "feasible": result.feasible,
            "warnings": list(result.warnings),
            "infeasibility_reasons": list(result.infeasibility_reasons),
            "cost_breakdown": cost_breakdown,
            "objective_components_raw": raw_components,
            "objective_components_weighted": weighted_components,
            "objective_weights": objective_weights,
            "pv_summary": {
                "pv_generated_kwh": float(cost_breakdown.get("pv_generated_kwh", 0.0) or 0.0),
                "pv_used_direct_kwh": float(cost_breakdown.get("pv_used_direct_kwh", 0.0) or 0.0),
                "pv_curtailed_kwh": float(cost_breakdown.get("pv_curtailed_kwh", 0.0) or 0.0),
                "grid_import_kwh": float(cost_breakdown.get("grid_import_kwh", 0.0) or 0.0),
                "peak_grid_kw": float(cost_breakdown.get("peak_grid_kw", 0.0) or 0.0),
            },
            "utilization_summary": {
                "fleet_size": fleet_size,
                "used_vehicle_count": used_vehicle_count,
                "utilization_ratio": utilization_ratio,
            },
            "termination_reason": solver_metadata.get("termination_reason"),
            "effective_limits": dict(solver_metadata.get("effective_limits") or {}),
            "solver_metadata": solver_metadata,
            "operator_stats": {
                name: {
                    "selected": stats.selected,
                    "accepted": stats.accepted,
                    "rejected": stats.rejected,
                    "reward": stats.reward,
                }
                for name, stats in result.operator_stats.items()
            },
            "incumbent_history": [
                {
                    "iteration": snap.iteration,
                    "objective_value": snap.objective_value,
                    "feasible": snap.feasible,
                }
                for snap in result.incumbent_history
            ],
            **cls.serialize_plan(result.plan),
        }
