"""
src.preprocess.fuel_model — ICE / HEV 燃料消費推定

spec_v3 §5.4 / agent_route_editable §2.4
BEV と同一 route データから計算し、powertrain 比較を可能にする。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.schemas.route_entities import Segment
from src.schemas.fleet_entities import VehicleType


# デフォルト係数 (spec_v3 §5.4)
_DEFAULT_GAMMA = {
    "dist":   0.30,   # [L/km]
    "time":   0.00,   # [L/h]
    "stop":   0.008,  # [L/stop]  stop-and-go penalty
    "grade":  0.003,  # [L / (%·km)] grade penalty
    "cong":   0.015,  # [L / (congestion_index · km)]
    "hvac":   0.20,   # [L/h]  HVAC compensation
    "load":   0.05,   # [L/km per load_factor=1.0]
}


def estimate_trip_fuel_ice(
    segments: List[Segment],
    vehicle_type: VehicleType,
    passenger_load_factor: float = 0.5,
    hvac_runtime_h: float = 0.0,
) -> Tuple[float, Dict[str, float]]:
    """ICE trip 燃料消費 [L/trip] を推定する。

    spec_v3 §5.4 標準式:
        f_ice = dist * gamma0
              + runtime_h * gamma_time
              + stop_count * gamma_stop
              + positive_grade_dist * gamma_grade
              + congestion * dist * gamma_cong
              + hvac_fuel_penalty
              + load_factor * dist * gamma_load

    Returns
    -------
    (fuel_l, breakdown_dict)
    """
    total_dist = sum(s.distance_km for s in segments)
    total_run_h = sum((s.scheduled_run_time_min or 0.0) for s in segments) / 60.0

    gamma0 = vehicle_type.base_fuel_rate_l_per_km or _DEFAULT_GAMMA["dist"]
    if vehicle_type.energy_factor_override_fuel is not None if hasattr(vehicle_type, "energy_factor_override_fuel") else False:
        pass  # will use segment override below

    f_dist = gamma0 * total_dist
    f_time = _DEFAULT_GAMMA["time"] * total_run_h

    grade_up_dist = sum(max((s.grade_avg_pct or 0.0), 0.0) * s.distance_km for s in segments)
    stop_count = sum((s.signal_count or 0) for s in segments)
    cong_dist = sum((s.congestion_index or 0.0) * s.distance_km for s in segments)

    f_grade = grade_up_dist * _DEFAULT_GAMMA["grade"]
    f_stop = stop_count * _DEFAULT_GAMMA["stop"]
    f_cong = cong_dist * _DEFAULT_GAMMA["cong"]
    f_load = passenger_load_factor * total_dist * _DEFAULT_GAMMA["load"]
    f_hvac = _DEFAULT_GAMMA["hvac"] * hvac_runtime_h

    total_fuel = f_dist + f_time + f_grade + f_stop + f_cong + f_load + f_hvac

    breakdown = {
        "distance": round(f_dist, 5),
        "time": round(f_time, 5),
        "grade": round(f_grade, 5),
        "stop_start": round(f_stop, 5),
        "congestion": round(f_cong, 5),
        "load": round(f_load, 5),
        "hvac": round(f_hvac, 5),
    }
    return round(total_fuel, 4), breakdown


def estimate_trip_fuel_hev(
    segments: List[Segment],
    vehicle_type: VehicleType,
    passenger_load_factor: float = 0.5,
    hvac_runtime_h: float = 0.0,
    hev_efficiency_factor: float = 0.75,
) -> Tuple[float, Dict[str, float]]:
    """HEV trip 燃料消費 [L/trip] を推定する。

    ICE 推定値に効率係数を掛けた簡易モデル。
    HEV は回生・アイドルストップにより ICE より低燃費 (hev_efficiency_factor < 1.0)。

    Returns
    -------
    (fuel_l, breakdown_dict)
    """
    ice_fuel, ice_bd = estimate_trip_fuel_ice(
        segments, vehicle_type, passenger_load_factor, hvac_runtime_h
    )
    hev_fuel = ice_fuel * hev_efficiency_factor
    hev_bd = {k: round(v * hev_efficiency_factor, 5) for k, v in ice_bd.items()}
    hev_bd["hev_efficiency_factor"] = hev_efficiency_factor
    return round(hev_fuel, 4), hev_bd
