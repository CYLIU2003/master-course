from __future__ import annotations

from typing import Any, Dict, List

from .problem import AssignmentPlan, OptimizationEngineResult


class ResultSerializer:
    @staticmethod
    def _serialize_depot_slot_mapping(raw_mapping: Any) -> Dict[str, Dict[int, float]]:
        if not isinstance(raw_mapping, dict):
            return {}
        serialized: Dict[str, Dict[int, float]] = {}
        for depot_id, slot_map in raw_mapping.items():
            if not isinstance(slot_map, dict):
                continue
            serialized[str(depot_id)] = {
                int(slot_idx): float(value or 0.0)
                for slot_idx, value in slot_map.items()
            }
        return serialized

    @staticmethod
    def serialize_plan(plan: AssignmentPlan) -> Dict[str, Any]:
        metadata = dict(plan.metadata)

        def _slot_to_hhmm(slot_index: int) -> str:
            timestep_min = int(metadata.get("timestep_min") or 0)
            if timestep_min <= 0:
                return ""
            base_text = str(metadata.get("horizon_start") or "00:00")
            try:
                hh_text, mm_text = base_text.split(":", 1)
                base_min = int(hh_text) * 60 + int(mm_text)
            except ValueError:
                base_min = 0
            minute = (base_min + int(slot_index) * timestep_min) % (24 * 60)
            return f"{minute // 60:02d}:{minute % 60:02d}"

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
                    "charging_depot_id": slot.charging_depot_id,
                    "charging_latitude": slot.charging_latitude,
                    "charging_longitude": slot.charging_longitude,
                }
                for slot in plan.charging_slots
            ],
            "refueling_schedule": [
                {
                    "vehicle_id": slot.vehicle_id,
                    "slot_index": slot.slot_index,
                    "time_hhmm": _slot_to_hhmm(slot.slot_index),
                    "refuel_liters": slot.refuel_liters,
                    "location_id": slot.location_id,
                }
                for slot in plan.refuel_slots
            ],
            "served_trip_ids": list(plan.served_trip_ids),
            "unserved_trip_ids": list(plan.unserved_trip_ids),
            "grid_to_bus_kwh_by_depot_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.grid_to_bus_kwh_by_depot_slot
            ),
            "pv_to_bus_kwh_by_depot_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.pv_to_bus_kwh_by_depot_slot
            ),
            "bess_to_bus_kwh_by_depot_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.bess_to_bus_kwh_by_depot_slot
            ),
            "pv_to_bess_kwh_by_depot_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.pv_to_bess_kwh_by_depot_slot
            ),
            "grid_to_bess_kwh_by_depot_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.grid_to_bess_kwh_by_depot_slot
            ),
            "pv_curtail_kwh_by_depot_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.pv_curtail_kwh_by_depot_slot
            ),
            "bess_soc_kwh_by_depot_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.bess_soc_kwh_by_depot_slot
            ),
            "contract_over_limit_kwh_by_depot_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.contract_over_limit_kwh_by_depot_slot
            ),
            "vehicle_cost_ledger": [
                {
                    "vehicle_id": row.vehicle_id,
                    "day_index": row.day_index,
                    "provisional_drive_cost_jpy": row.provisional_drive_cost_jpy,
                    "provisional_leftover_cost_jpy": row.provisional_leftover_cost_jpy,
                    "realized_charge_cost_jpy": row.realized_charge_cost_jpy,
                    "realized_refuel_cost_jpy": row.realized_refuel_cost_jpy,
                    "realized_bess_discharge_cost_jpy": row.realized_bess_discharge_cost_jpy,
                    "contract_overage_allocated_jpy": row.contract_overage_allocated_jpy,
                    "start_soc_kwh": row.start_soc_kwh,
                    "end_soc_kwh": row.end_soc_kwh,
                    "start_fuel_l": row.start_fuel_l,
                    "end_fuel_l": row.end_fuel_l,
                }
                for row in plan.vehicle_cost_ledger
            ],
            "daily_cost_ledger": [
                {
                    "day_index": row.day_index,
                    "service_date": row.service_date,
                    "ev_provisional_drive_cost_jpy": row.ev_provisional_drive_cost_jpy,
                    "ev_realized_charge_cost_jpy": row.ev_realized_charge_cost_jpy,
                    "ev_leftover_provisional_cost_jpy": row.ev_leftover_provisional_cost_jpy,
                    "ice_provisional_drive_cost_jpy": row.ice_provisional_drive_cost_jpy,
                    "ice_realized_refuel_cost_jpy": row.ice_realized_refuel_cost_jpy,
                    "ice_leftover_provisional_cost_jpy": row.ice_leftover_provisional_cost_jpy,
                    "demand_charge_jpy": row.demand_charge_jpy,
                    "total_cost_jpy": row.total_cost_jpy,
                }
                for row in plan.daily_cost_ledger
            ],
            "metadata": metadata,
        }

    @classmethod
    def serialize_result(cls, result: OptimizationEngineResult) -> Dict[str, Any]:
        # Backward-compatible path: some direct MILP callers still pass legacy
        # MILPResult which has obj_breakdown/assignment instead of plan/result metadata.
        if not hasattr(result, "plan"):
            cost_breakdown = dict(getattr(result, "cost_breakdown", {}) or getattr(result, "obj_breakdown", {}) or {})
            assignment = dict(getattr(result, "assignment", {}) or {})
            served_trip_ids = sorted({trip_id for trips in assignment.values() for trip_id in (trips or [])})
            unserved_trip_ids = list(getattr(result, "unserved_tasks", []) or [])
            infeasibility_info = str(getattr(result, "infeasibility_info", "") or "")
            fleet_size = len(assignment)
            used_vehicle_count = sum(1 for trip_ids in assignment.values() if trip_ids)
            vehicle_fragment_counts = {str(vehicle_id): len(list(trip_ids or [])) for vehicle_id, trip_ids in assignment.items()}
            utilization_ratio = float(used_vehicle_count) / float(fleet_size) if fleet_size > 0 else 0.0
            return {
                "solver_mode": str(getattr(getattr(result, "mode", None), "value", "mode_milp_only") or "mode_milp_only"),
                "solver_status": str(getattr(result, "status", "UNKNOWN") or "UNKNOWN"),
                "objective_mode": "total_cost",
                "objective_value": getattr(result, "objective_value", None),
                "feasible": str(getattr(result, "status", "")).upper() in {"OPTIMAL", "TIME_LIMIT", "SUBOPTIMAL", "FEASIBLE"},
                "warnings": [],
                "infeasibility_reasons": [infeasibility_info] if infeasibility_info else [],
                "cost_breakdown": cost_breakdown,
                "objective_components_raw": {},
                "objective_components_weighted": {},
                "objective_weights": {},
                "pv_summary": {},
                "utilization_summary": {
                    "fleet_size": fleet_size,
                    "used_vehicle_count": used_vehicle_count,
                    "utilization_ratio": utilization_ratio,
                },
                "termination_reason": None,
                "effective_limits": {},
                "solver_metadata": {},
                "operator_stats": {},
                "incumbent_history": [],
                "duties": [],
                "vehicle_paths": assignment,
                "vehicle_fragment_counts": vehicle_fragment_counts,
                "vehicles_with_multiple_fragments": [
                    vehicle_id for vehicle_id, count in vehicle_fragment_counts.items() if count > 1
                ],
                "max_fragments_observed": max(vehicle_fragment_counts.values(), default=0),
                "charging_schedule": [],
                "refueling_schedule": [],
                "served_trip_ids": served_trip_ids,
                "unserved_trip_ids": unserved_trip_ids,
                "trip_count_served": len(served_trip_ids),
                "trip_count_unserved": len(unserved_trip_ids),
                "coverage_rank_primary": len(unserved_trip_ids),
                "secondary_objective_value": getattr(result, "objective_value", None),
                "contract_over_limit_kwh_by_depot_slot": {},
                "metadata": {},
            }

        cost_breakdown = dict(result.cost_breakdown)
        solver_metadata = dict(result.solver_metadata)
        objective_weights = dict(solver_metadata.get("objective_weights") or {})
        raw_components = {
            "energy_cost": float(cost_breakdown.get("energy_cost", 0.0) or 0.0),
            "demand_cost": float(cost_breakdown.get("demand_cost", 0.0) or 0.0),
            "vehicle_cost": float(cost_breakdown.get("vehicle_cost", 0.0) or 0.0),
            "driver_cost": float(cost_breakdown.get("driver_cost", 0.0) or 0.0),
            "unserved_penalty": float(cost_breakdown.get("unserved_penalty", 0.0) or 0.0),
            "switch_cost": float(cost_breakdown.get("switch_cost", 0.0) or 0.0),
            "deviation_cost": float(cost_breakdown.get("deviation_cost", 0.0) or 0.0),
            "degradation_cost": float(cost_breakdown.get("degradation_cost", 0.0) or 0.0),
            "co2_cost": float(cost_breakdown.get("co2_cost", 0.0) or 0.0),
            "contract_overage_cost": float(cost_breakdown.get("contract_overage_cost", 0.0) or 0.0),
            "return_leg_bonus": float(cost_breakdown.get("return_leg_bonus", 0.0) or 0.0),
        }
        weighted_components = {
            "energy_cost": raw_components["energy_cost"] * float(objective_weights.get("electricity_cost", 1.0) or 1.0),
            "demand_cost": raw_components["demand_cost"] * float(objective_weights.get("demand_charge_cost", 1.0) or 1.0),
            "vehicle_cost": raw_components["vehicle_cost"] * float(objective_weights.get("vehicle_fixed_cost", 1.0) or 1.0),
            "driver_cost": raw_components["driver_cost"],
            "unserved_penalty": raw_components["unserved_penalty"] * float(objective_weights.get("unserved_penalty", 1.0) or 1.0),
            "switch_cost": raw_components["switch_cost"] * float(objective_weights.get("switch_cost", 1.0) or 1.0),
            "deviation_cost": raw_components["deviation_cost"] * float(objective_weights.get("deviation_cost", 1.0) or 1.0),
            "degradation_cost": raw_components["degradation_cost"] * float(objective_weights.get("degradation", 1.0) or 1.0),
            "co2_cost": raw_components["co2_cost"] * float(objective_weights.get("emission_cost", 1.0) or 1.0),
            "contract_overage_cost": raw_components["contract_overage_cost"],
            "return_leg_bonus": raw_components["return_leg_bonus"] * float(objective_weights.get("return_leg_bonus", 1.0) or 1.0),
        }
        fleet_size = len(result.plan.vehicle_paths())
        used_vehicle_count = sum(1 for trip_ids in result.plan.vehicle_paths().values() if trip_ids)
        utilization_ratio = float(used_vehicle_count) / float(fleet_size) if fleet_size > 0 else 0.0
        vehicle_fragment_counts = result.plan.vehicle_fragment_counts()
        vehicles_with_multiple_fragments = result.plan.vehicles_with_multiple_fragments()
        max_fragments_observed = result.plan.max_fragments_observed()
        trip_count_served = len(result.plan.served_trip_ids)
        trip_count_unserved = len(result.plan.unserved_trip_ids)
        secondary_objective_value = float(result.objective_value) - float(cost_breakdown.get("unserved_penalty", 0.0) or 0.0)
        return {
            "solver_mode": result.mode.value,
            "solver_status": result.solver_status,
            "objective_mode": solver_metadata.get("objective_mode", "total_cost"),
            "objective_value": result.objective_value,
            "secondary_objective_value": secondary_objective_value,
            "feasible": result.feasible,
            "warnings": list(result.warnings),
            "infeasibility_reasons": list(result.infeasibility_reasons),
            "strict_coverage_precheck": dict(
                solver_metadata.get("strict_coverage_precheck") or {}
            ),
            "cost_breakdown": cost_breakdown,
            "operating_cost_provisional_jpy": float(cost_breakdown.get("operating_cost_provisional_total", 0.0) or 0.0),
            "operating_cost_realized_jpy": float(cost_breakdown.get("operating_cost_realized_total", 0.0) or 0.0),
            "operating_cost_leftover_jpy": float(cost_breakdown.get("operating_cost_leftover_total", 0.0) or 0.0),
            "ev_provisional_drive_cost_jpy": float(cost_breakdown.get("provisional_ev_drive_cost", 0.0) or 0.0),
            "ev_realized_charge_cost_jpy": float(cost_breakdown.get("realized_ev_charge_cost", 0.0) or 0.0),
            "ev_leftover_provisional_cost_jpy": float(cost_breakdown.get("leftover_ev_provisional_cost", 0.0) or 0.0),
            "ice_provisional_drive_cost_jpy": float(cost_breakdown.get("provisional_ice_drive_cost", 0.0) or 0.0),
            "ice_realized_refuel_cost_jpy": float(cost_breakdown.get("realized_ice_refuel_cost", 0.0) or 0.0),
            "ice_leftover_provisional_cost_jpy": float(cost_breakdown.get("leftover_ice_provisional_cost", 0.0) or 0.0),
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
            "trip_count_served": trip_count_served,
            "trip_count_unserved": trip_count_unserved,
            "coverage_rank_primary": trip_count_unserved,
            "vehicle_fragment_counts": dict(vehicle_fragment_counts),
            "vehicles_with_multiple_fragments": list(vehicles_with_multiple_fragments),
            "max_fragments_observed": int(max_fragments_observed),
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
                    "wall_clock_sec": snap.wall_clock_sec,
                }
                for snap in result.incumbent_history
            ],
            **cls.serialize_plan(result.plan),
        }
