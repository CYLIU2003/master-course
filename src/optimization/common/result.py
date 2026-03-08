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
        return {
            "solver_mode": result.mode.value,
            "solver_status": result.solver_status,
            "objective_value": result.objective_value,
            "feasible": result.feasible,
            "warnings": list(result.warnings),
            "infeasibility_reasons": list(result.infeasibility_reasons),
            "cost_breakdown": dict(result.cost_breakdown),
            "solver_metadata": dict(result.solver_metadata),
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
