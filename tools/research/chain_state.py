"""Read the executed state at a 00:00 boundary to start the next plan of a chain.

Only the rolling execution state is read, never a forecast or day-ahead state.
No trip of the 渋21〜23 timetable crosses midnight (latest arrival 23:24, earliest
departure 05:51), so no vehicle is in service at the boundary. A BEV absent from
the state was never used: it keeps the previous state, which the caller supplies.
"""
from __future__ import annotations

from typing import Mapping


def boundary_state(state: Mapping, *, days: int, depot_id: str, previous_soc_kwh: Mapping[str, float],
                   previous_fuel_l: Mapping[str, float]) -> dict:
    """Merge ``state_for_next_hour.json`` at ``days`` × 24 h with the previous state."""
    if days < 1 or state["current_min"] != days * 1440:
        raise ValueError(f"State at minute {state['current_min']} is not the end of day {days}")
    if state["in_progress_events"]:
        raise ValueError("A vehicle is in service at the chain boundary")
    soc, fuel = state["actual_vehicle_soc_kwh"], state["actual_vehicle_fuel_l"]
    unknown = (set(soc) - set(previous_soc_kwh)) | (set(fuel) - set(previous_fuel_l))
    if unknown:
        raise ValueError(f"Executed state has unknown vehicles: {sorted(unknown)}")
    return {"current_min": state["current_min"],
            "vehicle_soc_kwh": {**previous_soc_kwh, **soc},
            "vehicle_fuel_l": {**previous_fuel_l, **fuel},
            "bess_soc_kwh": float(state["actual_bess_soc_kwh"][depot_id]),
            "unused_bev_ids": sorted(set(previous_soc_kwh) - set(soc))}
