"""Explicit initial-SOC policies for controlled optimization experiments."""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

from .problem import CanonicalOptimizationProblem, ProblemVehicle


class InitialSocPolicy(StrEnum):
    ACTUAL_VEHICLE_INVENTORY = "actual_vehicle_inventory"
    UNIFORM_SCENARIO_VALUE = "uniform_scenario_value"
    PER_VEHICLE_SCENARIO_OVERRIDE = "per_vehicle_scenario_override"


def normalize_initial_soc_policy(value: Any) -> InitialSocPolicy:
    try:
        return InitialSocPolicy(str(value or InitialSocPolicy.ACTUAL_VEHICLE_INVENTORY))
    except ValueError as exc:
        allowed = ", ".join(policy.value for policy in InitialSocPolicy)
        raise ValueError(f"Unknown initial SOC policy {value!r}; expected one of {allowed}") from exc


def apply_initial_soc_policy_to_scenario(
    scenario: Mapping[str, Any],
    *,
    policy: InitialSocPolicy | str,
    uniform_percent: float | None = None,
) -> dict[str, Any]:
    """Return a scenario copy with an explicit, auditable SOC input policy."""
    normalized_policy = normalize_initial_soc_policy(policy)
    result = dict(scenario)
    simulation = dict(result.get("simulation_config") or {})
    vehicles = [dict(raw) for raw in list(result.get("vehicles") or []) if isinstance(raw, Mapping)]

    if normalized_policy is InitialSocPolicy.UNIFORM_SCENARIO_VALUE:
        if uniform_percent is None:
            raise ValueError("uniform_scenario_value requires initial_soc_percent")
        ratio = _percent_to_ratio(uniform_percent)
        for vehicle in vehicles:
            if _is_electric_vehicle(vehicle):
                vehicle["initialSoc"] = ratio
        simulation["initial_soc_percent"] = ratio
    elif normalized_policy is InitialSocPolicy.PER_VEHICLE_SCENARIO_OVERRIDE:
        missing = [str(vehicle.get("id") or vehicle.get("vehicle_id") or "") for vehicle in vehicles if _is_electric_vehicle(vehicle) and vehicle.get("initialSoc") is None]
        if missing:
            raise ValueError("per_vehicle_scenario_override requires initialSoc for every BEV: " + ", ".join(missing))

    simulation["initial_soc_policy"] = normalized_policy.value
    result["simulation_config"] = simulation
    result["vehicles"] = vehicles
    return result


def initial_soc_input_metadata(
    problem: CanonicalOptimizationProblem,
    *,
    policy: InitialSocPolicy | str,
) -> dict[str, Any]:
    """Return the exact BEV SOC inputs handed to the optimization model."""
    normalized_policy = normalize_initial_soc_policy(policy)
    rows = []
    for vehicle in sorted(problem.vehicles, key=lambda item: str(item.vehicle_id)):
        if not _is_electric_problem_vehicle(vehicle):
            continue
        capacity = max(float(vehicle.battery_capacity_kwh or 0.0), 0.0)
        initial_kwh = _vehicle_initial_soc_kwh(vehicle, capacity)
        minimum_kwh = _vehicle_minimum_soc_kwh(vehicle, capacity)
        rows.append(
            {
                "vehicle_id": str(vehicle.vehicle_id),
                "initial_soc_kwh": initial_kwh,
                "initial_soc_percent": initial_kwh / capacity if capacity > 0.0 else None,
                "battery_capacity_kwh": capacity,
                "minimum_soc_kwh": minimum_kwh,
                # The controlled case clears optional terminal floors/targets,
                # so the physical reserve is also the effective terminal
                # lower bound.  Record it separately to prevent a semantic
                # mix-up between initial and terminal SOC policies.
                "terminal_soc_minimum_kwh": minimum_kwh,
            }
        )
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "initial_soc_policy": normalized_policy.value,
        "initial_soc_source": normalized_policy.value,
        "initial_soc_input_hash": hashlib.sha256(encoded).hexdigest(),
        "initial_soc_by_vehicle": rows,
    }


def _percent_to_ratio(value: float) -> float:
    ratio = float(value)
    if ratio > 1.0:
        ratio /= 100.0
    if not 0.0 <= ratio <= 1.0:
        raise ValueError("initial_soc_percent must be in [0, 100]")
    return ratio


def _is_electric_vehicle(vehicle: Mapping[str, Any]) -> bool:
    vehicle_type = str(vehicle.get("type") or vehicle.get("vehicle_type") or vehicle.get("vehicleType") or "").upper()
    return vehicle_type in {"BEV", "PHEV", "FCEV"}


def _is_electric_problem_vehicle(vehicle: ProblemVehicle) -> bool:
    return str(vehicle.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}


def _vehicle_initial_soc_kwh(vehicle: ProblemVehicle, capacity: float) -> float:
    value = vehicle.initial_soc
    if value is None:
        return 0.8 * capacity
    numeric = float(value)
    if numeric <= 1.0:
        numeric *= capacity
    return min(max(numeric, 0.0), capacity)


def _vehicle_minimum_soc_kwh(vehicle: ProblemVehicle, capacity: float) -> float:
    value = vehicle.reserve_soc
    if value is None:
        return 0.15 * capacity
    numeric = float(value)
    if numeric <= 1.0:
        numeric *= capacity
    return min(max(numeric, 0.0), capacity)
