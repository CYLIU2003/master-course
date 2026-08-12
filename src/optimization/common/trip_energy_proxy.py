"""Deterministic trip-level energy-demand proxies for research sensitivities.

The proxy intentionally preserves the configured fleet-average daily demand.
It changes only the relative allocation across trips, so enabling it does not
silently create or remove aggregate energy from the experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.dispatch.models import Trip


LITERATURE_PROXY_MODEL_ID = "literature_proxy_v1"


@dataclass(frozen=True)
class TripDemandProxy:
    energy_kwh_by_trip: Mapping[str, float]
    fuel_l_by_trip: Mapping[str, float]
    provenance: Mapping[str, object]


def build_literature_proxy_trip_demands(
    trips: Sequence[Trip],
    *,
    bev_kwh_per_km: float,
    ice_l_per_km: float,
    sensitivity_scale: float = 1.0,
) -> TripDemandProxy:
    """Allocate fleet-average demand to individual trips deterministically.

    BEV relative weights use the positive distance and duration elasticities
    reported by Ji et al. (2022).  ICE relative weights use that paper's
    reported peak/off-peak fuel-consumption ratio (3.27 / 2.84).  Each set of
    weights is normalized back to the configured aggregate distance-based
    demand before the explicit sensitivity multiplier is applied.
    """

    scale = max(float(sensitivity_scale), 0.0)
    total_distance_km = sum(max(float(trip.distance_km), 0.0) for trip in trips)
    bev_target_kwh = total_distance_km * max(float(bev_kwh_per_km), 0.0) * scale
    ice_target_l = total_distance_km * max(float(ice_l_per_km), 0.0) * scale

    bev_weights: dict[str, float] = {}
    ice_weights: dict[str, float] = {}
    peak_ratio = 3.27 / 2.84
    for trip in trips:
        distance_km = max(float(trip.distance_km), 0.0)
        duration_min = max(float(trip.arrival_min - trip.departure_min), 1.0)
        bev_weights[trip.trip_id] = (
            distance_km**0.553 * duration_min**0.353
            if distance_km > 0.0
            else 0.0
        )
        minute_of_day = int(trip.departure_min) % (24 * 60)
        is_peak = (5 * 60 <= minute_of_day < 10 * 60) or (
            16 * 60 <= minute_of_day < 20 * 60
        )
        ice_weights[trip.trip_id] = distance_km * (peak_ratio if is_peak else 1.0)

    return TripDemandProxy(
        energy_kwh_by_trip=_normalize_weights(bev_weights, bev_target_kwh),
        fuel_l_by_trip=_normalize_weights(ice_weights, ice_target_l),
        provenance={
            "schema_version": "trip_energy_model_provenance_v1",
            "model_id": LITERATURE_PROXY_MODEL_ID,
            "bev_relative_weight": "distance_km^0.553 * duration_min^0.353",
            "ice_relative_weight": "distance_km * peak_multiplier",
            "ice_peak_multiplier": peak_ratio,
            "peak_windows_local": ["05:00-10:00", "16:00-20:00"],
            "aggregate_normalization": "configured_fleet_average_demand",
            "sensitivity_scale": scale,
            "source_doi": "10.1016/j.commtr.2022.100069",
            "model_role": "deterministic_literature_proxy_not_measured_trip_data",
        },
    )


def _normalize_weights(weights: Mapping[str, float], target: float) -> dict[str, float]:
    denominator = sum(max(float(value), 0.0) for value in weights.values())
    if denominator <= 0.0 or target <= 0.0:
        return {str(key): 0.0 for key in weights}
    return {
        str(key): target * max(float(value), 0.0) / denominator
        for key, value in weights.items()
    }
