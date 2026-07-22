"""Canonical fingerprints for research optimization inputs."""

from __future__ import annotations

import hashlib
import json
from typing import Any


INPUT_FINGERPRINT_SCHEMA = "canonical_optimization_input_v3"


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_trip_input_hash(problem: Any) -> str:
    """Hash every canonical trip field that can change model behavior."""

    payload = [
        {
            "trip_id": str(trip.trip_id),
            "route_id": str(trip.route_id),
            "route_family_code": str(trip.route_family_code),
            "route_variant_type": str(trip.route_variant_type),
            "direction": str(trip.direction),
            # The selected service date is fingerprinted separately by every
            # research runner.  Once the canonical trip set is built, this
            # label does not alter assignment or energy behavior and would
            # make controlled sunny/rainy dates look structurally different.
            "origin": str(trip.origin),
            "destination": str(trip.destination),
            "departure_min": int(trip.departure_min),
            "arrival_min": int(trip.arrival_min),
            "distance_km": float(trip.distance_km),
            "energy_kwh": float(trip.energy_kwh),
            "fuel_l": float(trip.fuel_l),
            "required_soc_departure_percent": (
                None
                if trip.required_soc_departure_percent is None
                else float(trip.required_soc_departure_percent)
            ),
            "allowed_vehicle_types": list(trip.allowed_vehicle_types),
        }
        for trip in sorted(problem.trips, key=lambda item: str(item.trip_id))
    ]
    return _canonical_hash(payload)


def canonical_vehicle_input_hash(problem: Any) -> str:
    """Hash every concrete-vehicle field used by assignment or energy logic."""

    payload = [
        {
            "vehicle_id": str(vehicle.vehicle_id),
            "vehicle_type": str(vehicle.vehicle_type),
            "home_depot_id": str(vehicle.home_depot_id),
            "available": bool(vehicle.available),
            "initial_soc": vehicle.initial_soc,
            "battery_capacity_kwh": vehicle.battery_capacity_kwh,
            "reserve_soc": vehicle.reserve_soc,
            "energy_consumption_kwh_per_km": (
                vehicle.energy_consumption_kwh_per_km
            ),
            "initial_fuel_l": vehicle.initial_fuel_l,
            "fuel_tank_capacity_l": vehicle.fuel_tank_capacity_l,
            "fuel_reserve_l": vehicle.fuel_reserve_l,
            "fuel_consumption_l_per_km": vehicle.fuel_consumption_l_per_km,
            "fixed_use_cost_jpy": float(vehicle.fixed_use_cost_jpy or 0.0),
            "charge_power_max_kw": vehicle.charge_power_max_kw,
            "compatible_charger_ids": list(vehicle.compatible_charger_ids),
        }
        for vehicle in sorted(
            problem.vehicles,
            key=lambda item: str(item.vehicle_id),
        )
    ]
    return _canonical_hash(payload)
