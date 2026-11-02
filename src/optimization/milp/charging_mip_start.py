"""Optional binary charging start; never replaces fixed dispatch or real state."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
import math
from typing import Any

from src.optimization.common.problem import ChargingSlot


CHARGING_START_POLICIES = ("none", "fixed_assignment_binary", "stage1_recourse_binary")
RECOURSE_START_POLICY = "stage1_recourse_binary"
FIXED_ASSIGNMENT_SOURCE = "fixed_assignment.charging_slots"
RECOURSE_SOURCE = "stage1_time_indexed_energy_recourse.charge_power_kw_by_vehicle_slot"


def validate_charging_start_policy(policy: str) -> str:
    if policy not in CHARGING_START_POLICIES:
        raise ValueError(f"Unsupported Stage2 charging start policy: {policy!r}")
    return policy


def recourse_charging_slots(
    charge_power_kw_by_vehicle_slot: Mapping[str, Mapping[Any, Any]], *,
    slot_indices: Iterable[int],
    charger_vars: Mapping[tuple[str, str, int], Any],
    ports_by_charger: Mapping[str, int],
    blocked_slots_by_vehicle: Mapping[str, Iterable[int]],
) -> tuple[tuple[ChargingSlot, ...], dict[str, Any]]:
    """Turn the Stage 1 continuous recourse into a port-feasible binary support.

    The recourse relaxes physical charger assignment, so it can charge more
    vehicles in a slot than there are ports. Here every slot keeps at most
    ``ports`` vehicles per charger: vehicles already charging in the previous
    slot keep their charger first, then larger recourse power wins. Dropped
    and blocked (trip, deadhead, away) support is counted, never hidden.
    The result is only a MIP start proposal for native validation.
    """
    candidates: dict[str, list[str]] = {}
    for vehicle, charger, _slot in charger_vars:
        if charger not in candidates.setdefault(vehicle, []):
            candidates[vehicle].append(charger)
    blocked = {vehicle: set(slots) for vehicle, slots in blocked_slots_by_vehicle.items()}
    power: dict[int, dict[str, float]] = {}
    invalid = 0
    for vehicle, by_slot in charge_power_kw_by_vehicle_slot.items():
        for raw_slot, raw_kw in by_slot.items():
            kw = float(raw_kw)
            if not math.isfinite(kw) or kw < 0:
                invalid += 1
                continue
            if kw > 1e-6:
                power.setdefault(int(raw_slot), {})[str(vehicle)] = kw
    audit = {"source_positive_slots": sum(len(v) for v in power.values()),
             "blocked_slots": 0, "unrepresentable_slots": 0, "port_dropped_slots": 0,
             "invalid_source_values": invalid}
    slots: list[ChargingSlot] = []
    previous: dict[str, str] = {}
    for slot in sorted(slot_indices):
        wanted = power.get(slot, {})
        used: dict[str, int] = {}
        current: dict[str, str] = {}
        order = sorted(wanted, key=lambda v: (v not in previous, -wanted[v], v))
        for vehicle in order:
            if slot in blocked.get(vehicle, ()):
                audit["blocked_slots"] += 1
                continue
            options = [c for c in candidates.get(vehicle, ()) if (vehicle, c, slot) in charger_vars]
            if not options:
                audit["unrepresentable_slots"] += 1
                continue
            if previous.get(vehicle) in options:
                options.remove(previous[vehicle])
                options.insert(0, previous[vehicle])
            charger = next((c for c in options if used.get(c, 0) < max(int(ports_by_charger.get(c, 1)), 1)), None)
            if charger is None:
                audit["port_dropped_slots"] += 1
                continue
            used[charger] = used.get(charger, 0) + 1
            current[vehicle] = charger
            slots.append(ChargingSlot(vehicle, slot, charger, charge_kw=wanted[vehicle]))
        previous = current
    audit["kept_slots"] = len(slots)
    return tuple(slots), audit


def apply_charging_mip_start(
    model: Any, *, policy: str, warm_start: bool,
    charging_slots: Iterable[ChargingSlot],
    charge_on_vars: Mapping[tuple[str, int], Any],
    charger_vars: Mapping[tuple[str, str, int], Any],
    window_start_slot: int | None,
    connected_chargers: Mapping[str, str],
    active_session_vehicle_ids: Iterable[str],
    source: str = FIXED_ASSIGNMENT_SOURCE,
    source_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a partial MIP start to native validation, not an incumbent.

    Only binary charge-on/physical-charger variables are supplied. In particular
    no historical SOC, flow, power, or terminal state is copied into this model.
    V2G/discharge source plans are outside this optional proposal's scope and
    cause no start writes; the unchanged model is still solved normally.
    Invalid source support causes no start writes. Conflicting connection
    choices at the first slot are omitted; the actual-state constraints remain.
    """
    validate_charging_start_policy(policy)
    audit: dict[str, Any] = {"policy": policy, "status": "NOT_APPLIED",
        "source": source, "scope": "binary_only",
        "submitted_variables": 0, "solver_acceptance": "NOT_OBSERVED"}
    if source_audit is not None:
        audit["source_conversion"] = dict(source_audit)
    if policy == "none" or not warm_start:
        return {**audit, "reason": "disabled"}
    if not charge_on_vars or not charger_vars:
        return {**audit, "reason": "no_charging_variables"}
    if type(window_start_slot) is not int or window_start_slot < 0:
        raise ValueError("Stage2 charging start requires the actual window start slot")
    current_slots = {slot for _, slot in charge_on_vars}
    power: dict[tuple[str, int, str | None], float] = {}
    for charge in charging_slots:
        if charge.slot_index not in current_slots:
            continue
        if (not math.isfinite(charge.charge_kw) or charge.charge_kw < 0
                or not math.isfinite(charge.discharge_kw) or charge.discharge_kw != 0):
            return {**audit, "reason": "invalid_or_discharge_source"}
        key = (charge.vehicle_id, charge.slot_index, charge.charger_id)
        power[key] = power.get(key, 0.0) + charge.charge_kw
    active: dict[tuple[str, int], str] = {}
    for (vehicle, slot, charger), kw in power.items():
        if not math.isfinite(kw):
            return {**audit, "reason": "invalid_source_power_sum"}
        if kw <= 1e-6:
            continue
        key = (vehicle, slot)
        if key not in charge_on_vars or (vehicle, charger, slot) not in charger_vars:
            return {**audit, "reason": "source_charger_not_representable"}
        if key in active and active[key] != charger:
            return {**audit, "reason": "multiple_source_chargers_in_slot"}
        active[key] = charger
    if not active:
        return {**audit, "reason": "no_positive_source_charging"}
    source_rows = sorted((vehicle, slot, charger) for (vehicle, slot), charger in active.items())
    first_slot = window_start_slot
    omitted = {(vehicle, first_slot) for vehicle in active_session_vehicle_ids
               if (vehicle, first_slot) in active
               and connected_chargers.get(vehicle) != active[(vehicle, first_slot)]}
    variables, values = [], []
    for key, var in charge_on_vars.items():
        if key not in omitted:
            variables.append(var)
            values.append(int(key in active))
    charge_on_count = len(variables)
    for (vehicle, charger, slot), var in charger_vars.items():
        if (vehicle, slot) not in omitted:
            variables.append(var)
            values.append(int(active.get((vehicle, slot)) == charger))
    if not variables:
        return {**audit, "reason": "all_source_connection_slots_omitted",
                "omitted_connection_slots": len(omitted)}
    # Setting Start cannot change bounds, constraints or the incumbent. Gurobi
    # alone determines whether this proposal has feasible continuous recourse.
    model.setAttr("Start", variables, values)
    return {**audit, "status": "SUBMITTED", "reason": "native_validation_required",
        "submitted_variables": len(variables), "charge_on_variables": charge_on_count,
        "charger_variables": len(variables) - charge_on_count,
        "source_positive_slots": len(active), "omitted_connection_slots": len(omitted),
        "source_support_sha256": hashlib.sha256(json.dumps(source_rows, separators=(",", ":")).encode()).hexdigest()}
