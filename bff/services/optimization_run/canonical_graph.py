from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional


def canonical_output_base_date(problem, graph_context: Optional[Dict[str, Any]]) -> date:
    del graph_context
    service_date = str((problem.metadata or {}).get("service_date") or "").strip()
    if service_date:
        try:
            return datetime.fromisoformat(service_date[:10]).date()
        except ValueError:
            pass
    return datetime.now().date()


def canonical_datetime_from_min(base_date, minute_from_midnight: int) -> datetime:
    return datetime.combine(base_date, datetime.min.time()) + timedelta(minutes=int(minute_from_midnight))


def canonical_horizon_start_min(problem) -> int:
    try:
        hh_text, mm_text = str(getattr(problem.scenario, "horizon_start", None) or "00:00").split(":", 1)
        return int(hh_text) * 60 + int(mm_text)
    except ValueError:
        return 0


def canonical_slot_datetime(problem, base_date: date, slot_index: int) -> datetime:
    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    absolute_min = canonical_horizon_start_min(problem) + int(slot_index) * timestep_min
    return canonical_datetime_from_min(base_date, absolute_min)


def canonical_deadhead_distance_km(problem, deadhead_min: int) -> float:
    try:
        speed = float((problem.metadata or {}).get("deadhead_speed_kmh") or 18.0)
    except (TypeError, ValueError):
        speed = 18.0
    return max(float(deadhead_min or 0), 0.0) * max(speed, 0.0) / 60.0


def canonical_estimated_deadhead_energy_kwh(
    problem,
    *,
    deadhead_min: int,
    trip_energy_kwh: float,
    trip_distance_km: float,
) -> float:
    if deadhead_min <= 0:
        return 0.0
    safe_distance = max(float(trip_distance_km or 0.0), 1.0e-6)
    energy_per_km = max(float(trip_energy_kwh or 0.0), 0.0) / safe_distance
    return canonical_deadhead_distance_km(problem, deadhead_min) * energy_per_km


def canonical_vehicle_initial_soc_kwh(vehicle: Any) -> float:
    capacity = max(float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 0.0), 0.0)
    value = getattr(vehicle, "initial_soc", None)
    if value is None:
        return capacity
    parsed = float(value)
    if parsed <= 1.0 and capacity > 0.0:
        return parsed * capacity
    return parsed
