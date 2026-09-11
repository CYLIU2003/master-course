"""Fingerprint the structural inputs of the relaxed coverage precheck."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import hashlib
import json
import math
from typing import Any

from src.dispatch.models import DispatchContext
from .problem import CanonicalOptimizationProblem, ProblemTrip, ProblemVehicle


def _encode_input(value: Any) -> Any:
    """Retain field values and mapping key types without rounding numbers."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Nonfinite precheck fingerprint input")
        return value
    if is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "__dict__") and set(vars(value)) != {field.name for field in fields(value)}:
            raise TypeError("Custom dataclass attributes require a fresh precheck")
        return [type(value).__module__, type(value).__qualname__,
                [[field.name, _encode_input(getattr(value, field.name))]
                 for field in fields(value)]]
    if isinstance(value, (tuple, list)):
        return [type(value).__name__, [_encode_input(item) for item in value]]
    if isinstance(value, dict):
        rows = [[_encode_input(key), _encode_input(item)] for key, item in value.items()]
        return ["dict", sorted(rows, key=lambda row: json.dumps(row[0], ensure_ascii=False))]
    raise TypeError(f"Unsupported precheck fingerprint input: {type(value).__name__}")


def strict_precheck_input_fingerprint(problem: CanonicalOptimizationProblem) -> str | None:
    """Return None for custom contexts so their live behavior is always checked.

    The relaxed path-cover precheck ignores energy state. All trips and dispatch
    rules are included, while fleet inputs retain exactly its availability,
    vehicle type, home-depot and count dependencies. SOC, fuel and PV must still
    be validated by the native model and independent physical checks each hour.
    """
    context = problem.dispatch_context
    if type(context) is not DispatchContext:
        return None
    if set(vars(context)) != {field.name for field in fields(DispatchContext)}:
        return None
    if any(type(trip) is not ProblemTrip for trip in problem.trips):
        return None
    if any(type(vehicle) is not ProblemVehicle for vehicle in problem.vehicles):
        return None
    if any(set(vars(vehicle)) != {field.name for field in fields(ProblemVehicle)}
           for vehicle in problem.vehicles):
        return None
    payload = {
        "schema": "strict_coverage_precheck_input_v1",
        "scenario": problem.scenario,
        "trips": tuple(problem.trips),
        "dispatch_context": context,
        "fleet": tuple((vehicle.vehicle_id, vehicle.vehicle_type,
                        vehicle.home_depot_id, bool(vehicle.available))
                       for vehicle in problem.vehicles),
        "controls": {key: problem.metadata.get(key) for key in (
            "service_coverage_mode", "fixed_route_band_mode", "allow_same_day_depot_cycles"
        )},
    }
    try:
        encoded = json.dumps(_encode_input(payload), ensure_ascii=False,
                             allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()
