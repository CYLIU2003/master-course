"""
src.preprocess.energy_model — BEV 電費推定 (Level 0 / 1 / 2)

spec_v3 §5.3 / agent_route_editable §2.3
説明可能な component breakdown を返す。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from src.schemas.route_entities import Segment, GeneratedTrip
from src.schemas.fleet_entities import VehicleType


# ---------------------------------------------------------------------------
# デフォルト係数 (spec_v3 §5.3 Level 1 標準式)
# ---------------------------------------------------------------------------
_DEFAULT_BETA = {
    "dist": 1.20,  # [kWh/km]  base distance energy rate
    "time": 0.00,  # [kWh/h]   idle/aux per hour (speed-dependent)
    "grade_up": 0.05,  # [kWh / (%·km)]
    "grade_down": 0.02,  # [kWh / (%·km)]  回生で一部回収
    "stop": 0.03,  # [kWh/stop]  stop-start penalty
    "load": 0.30,  # [kWh/km per load_factor=1.0]
    "cong": 0.10,  # [kWh/km per unit congestion_index]
    "hvac": 1.00,  # [kWh/h]  HVAC average power
    "min_idle": 0.05,  # [kWh/km]  lower bound (aux only)
}


def _get_beta(vt: VehicleType, key: str) -> float:
    """VehicleType の属性 or デフォルトから係数取得。"""
    attr_map = {
        "dist": "base_energy_rate_kwh_per_km",
    }
    if key == "dist" and vt.base_energy_rate_kwh_per_km is not None:
        return vt.base_energy_rate_kwh_per_km
    return _DEFAULT_BETA.get(key, 0.0)


def estimate_segment_energy_bev(
    segment: Segment,
    vehicle_type: VehicleType,
    passenger_load_factor: float = 0.5,
    hvac_power_kw: float = 0.0,
) -> Tuple[float, Dict[str, float]]:
    """1 Segment の BEV 電力消費を Level 2 で推定する。

    spec_v3 §5.3 Level 2 標準式:
        e_seg = dist * alpha_dist
              + runtime_h * alpha_time
              + max(grade, 0) * dist * alpha_up
              - max(-grade, 0) * dist * alpha_regen
              + signal_count * alpha_stopstart
              + traffic * dist * alpha_traffic
              + load * dist * alpha_load

    Returns
    -------
    (energy_kwh, breakdown_dict)
    """
    dist = segment.distance_km
    runtime_h = (segment.scheduled_run_time_min or 0.0) / 60.0
    grade = segment.grade_avg_pct or 0.0
    signals = segment.signal_count or 0
    traffic = segment.traffic_level or 0.0
    congestion = segment.congestion_index or 0.0

    beta_d = _get_beta(vehicle_type, "dist")
    beta_g_up = _DEFAULT_BETA["grade_up"]
    beta_g_dn = _DEFAULT_BETA["grade_down"]
    beta_ss = _DEFAULT_BETA["stop"]
    beta_tr = _DEFAULT_BETA["cong"]
    beta_ld = _DEFAULT_BETA["load"]
    beta_time = _DEFAULT_BETA["time"]

    # override from segment
    if segment.energy_factor_override is not None:
        beta_d = segment.energy_factor_override

    e_dist = beta_d * dist
    e_grade_up = max(grade, 0.0) * dist * beta_g_up
    e_grade_regen = max(-grade, 0.0) * dist * beta_g_dn  # regen recovery
    e_stop = signals * beta_ss
    e_traffic = congestion * dist * beta_tr
    e_load = passenger_load_factor * dist * beta_ld
    e_time = runtime_h * beta_time
    e_hvac = hvac_power_kw * runtime_h

    raw = (
        e_dist
        + e_grade_up
        - e_grade_regen
        + e_stop
        + e_traffic
        + e_load
        + e_time
        + e_hvac
    )
    e_min = _DEFAULT_BETA["min_idle"] * dist
    energy = max(raw, e_min)

    breakdown = {
        "distance": round(e_dist, 5),
        "grade_up": round(e_grade_up, 5),
        "grade_regen": round(-e_grade_regen, 5),
        "stop_start": round(e_stop, 5),
        "traffic": round(e_traffic, 5),
        "load": round(e_load, 5),
        "hvac": round(e_hvac, 5),
        "time_idle": round(e_time, 5),
    }
    return round(energy, 6), breakdown


def estimate_trip_energy_bev(
    segments: List[Segment],
    vehicle_type: VehicleType,
    level: int = 1,
    passenger_load_factor: float = 0.5,
    hvac_runtime_h: float = 0.0,
) -> Tuple[float, Dict[str, float]]:
    """Trip 全体の BEV 電力消費を推定する。

    Parameters
    ----------
    level : int
        0: base_rate × distance のみ
        1: route-factor linear (spec_v3 §5.3 Level 1)
        2: segment aggregation (spec_v3 §5.3 Level 2)
    """
    if not segments:
        return 0.0, {}

    total_dist = sum(s.distance_km for s in segments)

    if level == 0:
        rate = vehicle_type.base_energy_rate_kwh_per_km or 1.2
        energy = rate * total_dist
        return round(energy, 4), {"distance": round(energy, 4)}

    if level == 1:
        # Level 1: trip-level aggregated route factors
        total_run_h = sum((s.scheduled_run_time_min or 0.0) for s in segments) / 60.0
        grade_up_dist = sum(
            max((s.grade_avg_pct or 0.0), 0.0) * s.distance_km for s in segments
        )
        grade_dn_dist = sum(
            max(-(s.grade_avg_pct or 0.0), 0.0) * s.distance_km for s in segments
        )
        stop_count = sum((s.signal_count or 0) for s in segments)
        cong_index = (
            sum((s.congestion_index or 0.0) * s.distance_km for s in segments)
            / total_dist
            if total_dist > 0
            else 0.0
        )

        beta_d = _get_beta(vehicle_type, "dist")
        hvac_kw = (
            (vehicle_type.hvac_power_kw_cooling or 0.0)
            + (vehicle_type.hvac_power_kw_heating or 0.0)
        ) / 2.0

        e_dist = beta_d * total_dist
        e_gu = grade_up_dist * _DEFAULT_BETA["grade_up"]
        e_gd = grade_dn_dist * _DEFAULT_BETA["grade_down"]
        e_stop = stop_count * _DEFAULT_BETA["stop"]
        e_load = passenger_load_factor * total_dist * _DEFAULT_BETA["load"]
        e_cong = cong_index * total_dist * _DEFAULT_BETA["cong"]
        e_hvac = hvac_kw * total_run_h
        e_time = total_run_h * _DEFAULT_BETA["time"]

        raw = e_dist + e_gu - e_gd + e_stop + e_load + e_cong + e_hvac + e_time
        energy = max(raw, _DEFAULT_BETA["min_idle"] * total_dist)
        bd = {
            "distance": round(e_dist, 4),
            "grade_up": round(e_gu, 4),
            "grade_regen": round(-e_gd, 4),
            "stop_start": round(e_stop, 4),
            "load": round(e_load, 4),
            "traffic": round(e_cong, 4),
            "hvac": round(e_hvac, 4),
        }
        return round(energy, 4), bd

    # Level 2: segment aggregation
    total_energy = 0.0
    combined_bd: Dict[str, float] = {}
    for seg in segments:
        hvac_kw = vehicle_type.hvac_power_kw_cooling or 0.0
        e_seg, bd_seg = estimate_segment_energy_bev(
            seg, vehicle_type, passenger_load_factor, hvac_kw
        )
        total_energy += e_seg
        for k, v in bd_seg.items():
            combined_bd[k] = combined_bd.get(k, 0.0) + v

    return round(total_energy, 4), {k: round(v, 4) for k, v in combined_bd.items()}


def estimate_trip_fuel_ice_from_segments(
    segments: List[Segment],
    vehicle_type: VehicleType,
    passenger_load_factor: float = 0.5,
) -> Tuple[float, Dict[str, float]]:
    """BEV と同一 route データから ICE 燃料消費 [L/trip] を推定する（proxy）。"""
    total_dist = sum(s.distance_km for s in segments)
    rate = vehicle_type.base_fuel_rate_l_per_km or 0.3
    fuel = rate * total_dist
    # 簡易補正: grade / congestion / load
    for s in segments:
        grade_pen = max((s.grade_avg_pct or 0.0), 0.0) * s.distance_km * 0.005
        cong_pen = (s.congestion_index or 0.0) * s.distance_km * 0.02
        load_pen = passenger_load_factor * s.distance_km * 0.01
        fuel += grade_pen + cong_pen + load_pen
    bd = {
        "distance": round(rate * total_dist, 4),
        "correction": round(fuel - rate * total_dist, 4),
    }
    return round(fuel, 4), bd


def apply_energy_uncertainty(
    base_energy_kwh: float,
    energy_multiplier: float = 1.0,
    travel_time_multiplier: float = 1.0,
) -> float:
    """シナリオ変動を基準値に適用して不確実性サンプルを生成する。

    spec_v3 §6.3:
        e_bev_scenario[t,k,omega] = e_bev[t,k] * energy_multiplier[omega,t]
    """
    return round(base_energy_kwh * energy_multiplier, 4)
