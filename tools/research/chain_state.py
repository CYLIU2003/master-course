"""Read the executed state at a next-morning boundary to start the next plan of a chain.

The boundary is the next-morning target slot, not 00:00: a bus that has just
returned at midnight cannot be at the morning target yet, and the plan that owns
the target must also own the overnight charging that reaches it. Only the rolling
execution is read, never a forecast or day-ahead state. A BEV without a trace was
never used: it keeps its previous state, which the caller supplies.
"""
from __future__ import annotations

import math
from typing import Mapping


def _at(trace: Mapping[str, float], slot: int, label: str) -> float:
    value = trace.get(str(slot))
    if value is None or not math.isfinite(float(value)):
        raise ValueError(f"{label} has no finite value at slot {slot}")
    return float(value)


def boundary_state(plan: Mapping, *, boundary_slot: int, depot_id: str, previous_soc_kwh: Mapping[str, float],
                   fuel_l: Mapping[str, float]) -> dict:
    """Return BEV SOC, BESS SOC and ICE fuel at the start of ``boundary_slot``.

    A vehicle's slot value is the state at the start of the slot (rc13: slot 96
    equals the hourly state at 24:00 for every bus); the BESS trace is the state
    at the end of the slot. ``fuel_l`` comes from the last hourly state before the
    boundary, which only the caller can read.
    """
    if boundary_slot < 1:
        raise ValueError("A chain boundary needs at least one executed slot")
    traces = plan["vehicle_soc_kwh_by_vehicle_slot"]
    unknown = set(traces) - set(previous_soc_kwh)
    if unknown:
        raise ValueError(f"Executed plan has unknown BEVs: {sorted(unknown)}")
    soc = {vehicle: _at(traces[vehicle], boundary_slot, f"SOC of {vehicle}") if vehicle in traces else float(previous)
           for vehicle, previous in previous_soc_kwh.items()}
    return {"boundary_slot": boundary_slot, "vehicle_soc_kwh": soc,
            "bess_soc_kwh": _at(plan["bess_soc_kwh_by_depot_slot"][depot_id], boundary_slot - 1, "BESS SOC"),
            "vehicle_fuel_l": dict(fuel_l), "unused_bev_ids": sorted(set(previous_soc_kwh) - set(traces))}
