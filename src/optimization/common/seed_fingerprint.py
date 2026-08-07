"""Canonical fingerprint for a Phase 3 plan handed to Phase 4."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math

from src.optimization.common.problem import AssignmentPlan


def phase4_seed_plan_fingerprint(plan: AssignmentPlan) -> str:
    """Hash assignment, charging provenance, SOC, and depot-energy traces.

    Candidate-pool hashes are optional metadata and are absent when Phase 3
    evaluates only its primary candidate. This fingerprint is plan-native and
    therefore exists for every finite physical hand-off.
    """

    def _finite(value: object) -> float:
        parsed = float(value or 0.0)
        if not math.isfinite(parsed):
            raise ValueError("phase4 seed contains a non-finite value")
        return round(parsed, 12)

    def _depot_slot_rows(raw: object) -> list[list[object]]:
        if not isinstance(raw, Mapping):
            return []
        rows: list[list[object]] = []
        for depot_id, slot_map in raw.items():
            if not isinstance(slot_map, Mapping):
                continue
            for slot_idx, value in slot_map.items():
                rows.append(
                    [str(depot_id), int(slot_idx), _finite(value)]
                )
        return sorted(rows, key=lambda row: (row[0], row[1]))

    duty_vehicle_map = plan.duty_vehicle_map()
    duties = [
        {
            "duty_id": str(duty.duty_id),
            "vehicle_id": str(
                duty_vehicle_map.get(str(duty.duty_id)) or ""
            ),
            "trip_ids": [str(leg.trip.trip_id) for leg in duty.legs],
        }
        for duty in plan.duties
    ]
    duties.sort(
        key=lambda row: (
            row["vehicle_id"],
            row["trip_ids"],
            row["duty_id"],
        )
    )
    payload = {
        "schema_version": "phase4_seed_plan_fingerprint_v1",
        "duties": duties,
        "served_trip_ids": sorted(str(item) for item in plan.served_trip_ids),
        "unserved_trip_ids": sorted(
            str(item) for item in plan.unserved_trip_ids
        ),
        "charging_slots": sorted(
            [
                str(slot.vehicle_id),
                int(slot.slot_index),
                str(slot.charger_id or ""),
                str(slot.charging_depot_id or ""),
                str(slot.energy_source or ""),
                _finite(slot.charge_kw),
                _finite(slot.discharge_kw),
            ]
            for slot in plan.charging_slots
        ),
        "refuel_slots": sorted(
            [
                str(slot.vehicle_id),
                int(slot.slot_index),
                str(slot.location_id or ""),
                _finite(slot.refuel_liters),
            ]
            for slot in plan.refuel_slots
        ),
        "grid_to_bus": _depot_slot_rows(
            plan.grid_to_bus_kwh_by_depot_slot
        ),
        "pv_to_bus": _depot_slot_rows(plan.pv_to_bus_kwh_by_depot_slot),
        "bess_to_bus": _depot_slot_rows(
            plan.bess_to_bus_kwh_by_depot_slot
        ),
        "grid_to_bess": _depot_slot_rows(
            plan.grid_to_bess_kwh_by_depot_slot
        ),
        "pv_to_bess": _depot_slot_rows(
            plan.pv_to_bess_kwh_by_depot_slot
        ),
        "pv_curtailment": _depot_slot_rows(
            plan.pv_curtail_kwh_by_depot_slot
        ),
        "bess_soc": _depot_slot_rows(
            plan.bess_soc_kwh_by_depot_slot
        ),
        "bess_soc_start": _depot_slot_rows(
            dict(plan.metadata or {}).get(
                "bess_soc_start_kwh_by_depot_slot"
            )
        ),
        "vehicle_soc": _depot_slot_rows(
            plan.vehicle_soc_kwh_by_vehicle_slot
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
