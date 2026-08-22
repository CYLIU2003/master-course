from __future__ import annotations

from typing import Any, Dict, List, Mapping

from src.dispatch.models import DutyLeg, VehicleDuty

from .energy_flow_accounting import normalize_pv_energy_breakdown
from .problem import (
    AssignmentPlan,
    ChargingSlot,
    DailyCostLedgerEntry,
    OptimizationEngineResult,
    RefuelSlot,
    VehicleCostLedgerEntry,
)


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
                    "energy_source": slot.energy_source,
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
            "vehicle_soc_kwh_by_vehicle_slot": ResultSerializer._serialize_depot_slot_mapping(
                plan.vehicle_soc_kwh_by_vehicle_slot
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

    @staticmethod
    def deserialize_plan(
        problem: Any,
        serialized_plan: Mapping[str, Any],
    ) -> AssignmentPlan:
        """Restore a complete persisted canonical plan without re-optimizing.

        ``canonical_solver_result.json`` is the authoritative decision record
        for post-solve audits.  Reconstructing only duties (as the rolling
        reoptimizer intentionally does) drops charging and energy-source
        decisions, which makes fixed-decision stress accounting impossible.
        This inverse accepts only canonical trips from ``problem`` and keeps
        every serialized charging, fuel, flow, and ledger decision unchanged.
        """
        if not isinstance(serialized_plan, Mapping):
            raise ValueError("serialized plan must be a mapping")
        dispatch_context = getattr(problem, "dispatch_context", None)
        trip_lookup = (
            dispatch_context.trips_by_id()
            if dispatch_context is not None
            and callable(getattr(dispatch_context, "trips_by_id", None))
            else {}
        )
        if not trip_lookup:
            raise ValueError("cannot restore plan without canonical dispatch trips")

        duties: list[VehicleDuty] = []
        for raw_duty in list(serialized_plan.get("duties") or []):
            if not isinstance(raw_duty, Mapping):
                raise ValueError("serialized plan contains an invalid duty")
            duty_id = str(raw_duty.get("duty_id") or "").strip()
            if not duty_id:
                raise ValueError("serialized plan contains an empty duty_id")
            raw_legs = list(raw_duty.get("legs") or [])
            if not raw_legs:
                raw_legs = [
                    {"trip_id": trip_id, "deadhead_from_prev_min": 0}
                    for trip_id in list(raw_duty.get("trip_ids") or [])
                ]
            if not raw_legs:
                raise ValueError(f"serialized duty {duty_id!r} contains no legs")
            legs: list[DutyLeg] = []
            for raw_leg in raw_legs:
                if not isinstance(raw_leg, Mapping):
                    raise ValueError(f"serialized duty {duty_id!r} has an invalid leg")
                trip_id = str(raw_leg.get("trip_id") or "").strip()
                trip = trip_lookup.get(trip_id)
                if trip is None:
                    raise ValueError(
                        f"serialized duty {duty_id!r} references unknown trip {trip_id!r}"
                    )
                deadhead_min = int(raw_leg.get("deadhead_from_prev_min") or 0)
                if deadhead_min < 0:
                    raise ValueError(
                        f"serialized duty {duty_id!r} has negative deadhead time"
                    )
                legs.append(DutyLeg(trip=trip, deadhead_from_prev_min=deadhead_min))
            duties.append(
                VehicleDuty(
                    duty_id=duty_id,
                    vehicle_type=str(raw_duty.get("vehicle_type") or ""),
                    legs=tuple(legs),
                )
            )

        def _float(value: Any) -> float:
            return float(value or 0.0)

        def _slot_mapping(name: str) -> dict[str, dict[int, float]]:
            raw = serialized_plan.get(name) or {}
            if not isinstance(raw, Mapping):
                raise ValueError(f"serialized {name} must be a mapping")
            result: dict[str, dict[int, float]] = {}
            for depot_id, slot_values in raw.items():
                if not isinstance(slot_values, Mapping):
                    raise ValueError(f"serialized {name}[{depot_id!r}] must be a mapping")
                result[str(depot_id)] = {
                    int(slot_index): _float(value)
                    for slot_index, value in slot_values.items()
                }
            return result

        charging_slots = []
        for raw in list(serialized_plan.get("charging_schedule") or []):
            if not isinstance(raw, Mapping):
                raise ValueError("serialized charging_schedule contains an invalid slot")
            charging_slots.append(
                ChargingSlot(
                    vehicle_id=str(raw.get("vehicle_id") or ""),
                    slot_index=int(raw.get("slot_index") or 0),
                    charger_id=(
                        str(raw["charger_id"])
                        if raw.get("charger_id") is not None
                        else None
                    ),
                    energy_source=(
                        str(raw["energy_source"])
                        if raw.get("energy_source") is not None
                        else None
                    ),
                    charge_kw=_float(raw.get("charge_kw")),
                    discharge_kw=_float(raw.get("discharge_kw")),
                    charging_depot_id=(
                        str(raw["charging_depot_id"])
                        if raw.get("charging_depot_id") is not None
                        else None
                    ),
                    charging_latitude=(
                        _float(raw.get("charging_latitude"))
                        if raw.get("charging_latitude") is not None
                        else None
                    ),
                    charging_longitude=(
                        _float(raw.get("charging_longitude"))
                        if raw.get("charging_longitude") is not None
                        else None
                    ),
                )
            )
        refuel_slots = []
        for raw in list(serialized_plan.get("refueling_schedule") or []):
            if not isinstance(raw, Mapping):
                raise ValueError("serialized refueling_schedule contains an invalid slot")
            refuel_slots.append(
                RefuelSlot(
                    vehicle_id=str(raw.get("vehicle_id") or ""),
                    slot_index=int(raw.get("slot_index") or 0),
                    refuel_liters=_float(raw.get("refuel_liters")),
                    location_id=(
                        str(raw["location_id"])
                        if raw.get("location_id") is not None
                        else None
                    ),
                )
            )

        def _optional_float(raw: Mapping[str, Any], name: str) -> float | None:
            return _float(raw.get(name)) if raw.get(name) is not None else None

        vehicle_ledger = tuple(
            VehicleCostLedgerEntry(
                vehicle_id=str(raw.get("vehicle_id") or ""),
                day_index=int(raw.get("day_index") or 0),
                provisional_drive_cost_jpy=_float(raw.get("provisional_drive_cost_jpy")),
                provisional_leftover_cost_jpy=_float(raw.get("provisional_leftover_cost_jpy")),
                realized_charge_cost_jpy=_float(raw.get("realized_charge_cost_jpy")),
                realized_refuel_cost_jpy=_float(raw.get("realized_refuel_cost_jpy")),
                realized_bess_discharge_cost_jpy=_float(raw.get("realized_bess_discharge_cost_jpy")),
                contract_overage_allocated_jpy=_float(raw.get("contract_overage_allocated_jpy")),
                start_soc_kwh=_optional_float(raw, "start_soc_kwh"),
                end_soc_kwh=_optional_float(raw, "end_soc_kwh"),
                start_fuel_l=_optional_float(raw, "start_fuel_l"),
                end_fuel_l=_optional_float(raw, "end_fuel_l"),
            )
            for raw in list(serialized_plan.get("vehicle_cost_ledger") or [])
            if isinstance(raw, Mapping)
        )
        daily_ledger = tuple(
            DailyCostLedgerEntry(
                day_index=int(raw.get("day_index") or 0),
                service_date=(str(raw["service_date"]) if raw.get("service_date") is not None else None),
                ev_provisional_drive_cost_jpy=_float(raw.get("ev_provisional_drive_cost_jpy")),
                ev_realized_charge_cost_jpy=_float(raw.get("ev_realized_charge_cost_jpy")),
                ev_leftover_provisional_cost_jpy=_float(raw.get("ev_leftover_provisional_cost_jpy")),
                ice_provisional_drive_cost_jpy=_float(raw.get("ice_provisional_drive_cost_jpy")),
                ice_realized_refuel_cost_jpy=_float(raw.get("ice_realized_refuel_cost_jpy")),
                ice_leftover_provisional_cost_jpy=_float(raw.get("ice_leftover_provisional_cost_jpy")),
                demand_charge_jpy=_float(raw.get("demand_charge_jpy")),
                total_cost_jpy=_float(raw.get("total_cost_jpy")),
            )
            for raw in list(serialized_plan.get("daily_cost_ledger") or [])
            if isinstance(raw, Mapping)
        )
        metadata = serialized_plan.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise ValueError("serialized metadata must be a mapping")
        return AssignmentPlan(
            duties=tuple(duties),
            charging_slots=tuple(charging_slots),
            refuel_slots=tuple(refuel_slots),
            grid_to_bus_kwh_by_depot_slot=_slot_mapping("grid_to_bus_kwh_by_depot_slot"),
            pv_to_bus_kwh_by_depot_slot=_slot_mapping("pv_to_bus_kwh_by_depot_slot"),
            bess_to_bus_kwh_by_depot_slot=_slot_mapping("bess_to_bus_kwh_by_depot_slot"),
            pv_to_bess_kwh_by_depot_slot=_slot_mapping("pv_to_bess_kwh_by_depot_slot"),
            grid_to_bess_kwh_by_depot_slot=_slot_mapping("grid_to_bess_kwh_by_depot_slot"),
            pv_curtail_kwh_by_depot_slot=_slot_mapping("pv_curtail_kwh_by_depot_slot"),
            bess_soc_kwh_by_depot_slot=_slot_mapping("bess_soc_kwh_by_depot_slot"),
            contract_over_limit_kwh_by_depot_slot=_slot_mapping("contract_over_limit_kwh_by_depot_slot"),
            vehicle_soc_kwh_by_vehicle_slot=_slot_mapping("vehicle_soc_kwh_by_vehicle_slot"),
            vehicle_cost_ledger=vehicle_ledger,
            daily_cost_ledger=daily_ledger,
            served_trip_ids=tuple(str(item) for item in list(serialized_plan.get("served_trip_ids") or [])),
            unserved_trip_ids=tuple(str(item) for item in list(serialized_plan.get("unserved_trip_ids") or [])),
            metadata=dict(metadata),
        )

    @classmethod
    def serialize_result(cls, result: OptimizationEngineResult) -> Dict[str, Any]:
        # Backward-compatible path: some direct MILP callers still pass legacy
        # MILPResult which has obj_breakdown/assignment instead of plan/result metadata.
        if not hasattr(result, "plan"):
            cost_breakdown = dict(getattr(result, "cost_breakdown", {}) or getattr(result, "obj_breakdown", {}) or {})
            cost_breakdown.update(normalize_pv_energy_breakdown(cost_breakdown))
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
        cost_breakdown.update(normalize_pv_energy_breakdown(cost_breakdown))
        solver_metadata = dict(result.solver_metadata)
        objective_weights = dict(solver_metadata.get("objective_weights") or {})
        fuel_cost = float(cost_breakdown.get("fuel_cost", 0.0) or 0.0)
        aggregate_energy_cost = float(
            cost_breakdown.get("energy_cost", 0.0) or 0.0
        )
        if cost_breakdown.get("electricity_cost") is not None:
            electricity_cost = float(cost_breakdown.get("electricity_cost") or 0.0)
        elif cost_breakdown.get("electricity_cost_final") is not None:
            electricity_cost = float(cost_breakdown.get("electricity_cost_final") or 0.0)
        else:
            electricity_cost = max(aggregate_energy_cost - fuel_cost, 0.0) if fuel_cost > 0.0 else aggregate_energy_cost
        if aggregate_energy_cost <= 0.0:
            aggregate_energy_cost = electricity_cost + fuel_cost

        def _objective_weight(key: str, default: float = 1.0) -> float:
            try:
                return float(objective_weights.get(key, default))
            except (TypeError, ValueError):
                return float(default)

        raw_components = {
            "energy_cost": aggregate_energy_cost,
            "electricity_cost": electricity_cost,
            "fuel_cost": fuel_cost,
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
            "energy_cost": (
                raw_components["electricity_cost"] * _objective_weight("electricity_cost")
                + raw_components["fuel_cost"] * _objective_weight("fuel_cost")
            ),
            "electricity_cost": raw_components["electricity_cost"] * _objective_weight("electricity_cost"),
            "fuel_cost": raw_components["fuel_cost"] * _objective_weight("fuel_cost"),
            "demand_cost": raw_components["demand_cost"] * _objective_weight("demand_charge_cost"),
            "vehicle_cost": raw_components["vehicle_cost"] * _objective_weight("vehicle_fixed_cost"),
            "driver_cost": raw_components["driver_cost"],
            "unserved_penalty": raw_components["unserved_penalty"] * _objective_weight("unserved_penalty"),
            "switch_cost": raw_components["switch_cost"] * _objective_weight("switch_cost"),
            "deviation_cost": raw_components["deviation_cost"] * _objective_weight("deviation_cost"),
            "degradation_cost": raw_components["degradation_cost"] * _objective_weight("degradation"),
            "co2_cost": raw_components["co2_cost"] * _objective_weight("emission_cost"),
            "contract_overage_cost": raw_components["contract_overage_cost"],
            "return_leg_bonus": raw_components["return_leg_bonus"] * _objective_weight("return_leg_bonus"),
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
            "energy_cash_purchase_cost_jpy": float(cost_breakdown.get("energy_cash_purchase_cost_jpy", 0.0) or 0.0),
            "energy_inventory_valuation_cost_jpy": float(cost_breakdown.get("energy_inventory_valuation_cost_jpy", 0.0) or 0.0),
            "ev_unreplenished_drive_energy_kwh": float(cost_breakdown.get("ev_unreplenished_drive_energy_kwh", 0.0) or 0.0),
            "ev_energy_inventory_balanced": bool(cost_breakdown.get("ev_energy_inventory_balanced", False)),
            "energy_cost_basis": str(cost_breakdown.get("energy_cost_basis") or "realized_supply_plus_inventory_valuation"),
            "fuel_cost_final_jpy": float(cost_breakdown.get("fuel_cost_final", cost_breakdown.get("fuel_cost", 0.0)) or 0.0),
            "fuel_cost_provisional_jpy": float(cost_breakdown.get("fuel_cost_provisional", cost_breakdown.get("provisional_ice_drive_cost", 0.0)) or 0.0),
            "fuel_cost_refueled_jpy": float(cost_breakdown.get("fuel_cost_refueled", cost_breakdown.get("realized_ice_refuel_cost", 0.0)) or 0.0),
            "fuel_cost_realized_jpy": float(cost_breakdown.get("fuel_cost_realized", cost_breakdown.get("realized_ice_refuel_cost", 0.0)) or 0.0),
            "fuel_cost_provisional_leftover_jpy": float(cost_breakdown.get("fuel_cost_provisional_leftover", cost_breakdown.get("leftover_ice_provisional_cost", 0.0)) or 0.0),
            "ice_provisional_drive_cost_jpy": float(cost_breakdown.get("provisional_ice_drive_cost", 0.0) or 0.0),
            "ice_realized_refuel_cost_jpy": float(cost_breakdown.get("realized_ice_refuel_cost", 0.0) or 0.0),
            "ice_leftover_provisional_cost_jpy": float(cost_breakdown.get("leftover_ice_provisional_cost", 0.0) or 0.0),
            "objective_components_raw": raw_components,
            "objective_components_weighted": weighted_components,
            "objective_weights": objective_weights,
            "pv_summary": {
                "pv_generated_kwh": float(cost_breakdown.get("pv_generated_kwh", 0.0) or 0.0),
                "pv_used_direct_kwh": float(cost_breakdown.get("pv_used_direct_kwh", 0.0) or 0.0),
                "pv_to_bus_kwh": float(cost_breakdown.get("pv_to_bus_kwh", 0.0) or 0.0),
                "pv_to_bess_kwh": float(cost_breakdown.get("pv_to_bess_kwh", 0.0) or 0.0),
                "pv_curtailed_kwh": float(cost_breakdown.get("pv_curtailed_kwh", 0.0) or 0.0),
                "pv_curtail_kwh": float(cost_breakdown.get("pv_curtail_kwh", 0.0) or 0.0),
                "grid_import_kwh": float(cost_breakdown.get("grid_import_kwh", 0.0) or 0.0),
                "peak_grid_kw": float(cost_breakdown.get("peak_grid_kw", 0.0) or 0.0),
                "pv_used_total_kwh": float(cost_breakdown.get("pv_used_total_kwh", 0.0) or 0.0),
                "pv_curtail_balance_kwh": float(cost_breakdown.get("pv_curtail_balance_kwh", 0.0) or 0.0),
                "pv_utilization_rate": float(cost_breakdown.get("pv_utilization_rate", 0.0) or 0.0),
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
