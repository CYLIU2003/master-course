"""Vehicle timeline activity selection for rich graph outputs."""

from __future__ import annotations

from typing import Any, Mapping


def vehicle_ids_with_timeline_activity(
    duties_by_vehicle: Mapping[str, Any],
    charging_slots: Any,
    refuel_slots: Any,
) -> tuple[str, ...]:
    vehicle_ids = {str(vehicle_id) for vehicle_id in duties_by_vehicle.keys()}
    vehicle_ids.update(
        str(getattr(slot, "vehicle_id", "") or "")
        for slot in (charging_slots or ())
        if str(getattr(slot, "vehicle_id", "") or "")
    )
    vehicle_ids.update(
        str(getattr(slot, "vehicle_id", "") or "")
        for slot in (refuel_slots or ())
        if str(getattr(slot, "vehicle_id", "") or "")
    )
    return tuple(sorted(vehicle_ids))
