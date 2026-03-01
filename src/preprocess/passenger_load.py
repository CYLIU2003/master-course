"""
src.preprocess.passenger_load — 乗客負荷プロファイル読込・energy model 反映

乗車率 (passenger_load_factor) が車両のエネルギー消費に影響するため、
data/external/passenger_load_profile.csv を読み込んで trip ごとの負荷率を推定する。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.schemas.route_entities import GeneratedTrip


def load_passenger_load_profile(
    csv_path: Path,
) -> List[Dict[str, str]]:
    """passenger_load_profile.csv を読み込む。

    CSV 形式:
        route_id, direction_id, time_band, load_factor, boarding_rate, alighting_rate

    Returns
    -------
    List[Dict[str, str]]
    """
    if not csv_path.exists():
        print(f"  [warn] {csv_path} が存在しません")
        return []
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_load_factor_map(
    profile_rows: List[Dict[str, str]],
) -> Dict[Tuple[str, str, str], float]:
    """(route_id, direction_id, time_band) → load_factor マッピングを構築。

    time_band: "morning_peak" | "midday" | "evening_peak" | "night" | "all_day"
    """
    mapping: Dict[Tuple[str, str, str], float] = {}
    for row in profile_rows:
        route_id = row.get("route_id", "")
        direction_id = row.get("direction_id", "")
        time_band = row.get("time_band", "all_day")
        try:
            lf = float(row.get("load_factor", "0.5"))
        except (ValueError, TypeError):
            lf = 0.5
        mapping[(route_id, direction_id, time_band)] = lf
    return mapping


def _classify_time_band(departure_time: str) -> str:
    """出発時刻 → time_band に分類する。"""
    try:
        hour = int(departure_time.split(":")[0])
    except (ValueError, IndexError):
        return "all_day"
    if 7 <= hour < 9:
        return "morning_peak"
    elif 9 <= hour < 16:
        return "midday"
    elif 16 <= hour < 19:
        return "evening_peak"
    else:
        return "night"


def apply_load_factor_to_trips(
    trips: List[GeneratedTrip],
    load_factor_map: Dict[Tuple[str, str, str], float],
    default_load_factor: float = 0.5,
) -> Dict[str, float]:
    """各 trip に対する passenger_load_factor を決定する。

    Returns
    -------
    Dict[trip_id, load_factor]
    """
    result: Dict[str, float] = {}
    for trip in trips:
        band = _classify_time_band(trip.departure_time)
        key = (trip.route_id, trip.direction_id, band)
        lf = load_factor_map.get(key)
        if lf is None:
            # fallback: route_id + all_day
            lf = load_factor_map.get((trip.route_id, trip.direction_id, "all_day"))
        if lf is None:
            # fallback: route_id のみ
            lf = load_factor_map.get((trip.route_id, "", "all_day"))
        if lf is None:
            lf = default_load_factor
        result[trip.trip_id] = lf
    return result


def compute_demand_kpi(
    trips: List[GeneratedTrip],
    trip_load_factors: Dict[str, float],
    vehicle_capacity: int = 70,
) -> Dict[str, float]:
    """需要関連 KPI を計算する。

    Returns
    -------
    dict:
        avg_load_factor, max_load_factor,
        overcrowded_trips (立ち席率 > 1.0), unserved_demand_proxy
    """
    if not trips:
        return {"avg_load_factor": 0.0, "max_load_factor": 0.0,
                "overcrowded_trips": 0, "pct_overcrowded": 0.0}

    factors = [trip_load_factors.get(t.trip_id, 0.5) for t in trips]
    overcrowded = sum(1 for f in factors if f > 1.0)

    return {
        "avg_load_factor": round(sum(factors) / len(factors), 4),
        "max_load_factor": round(max(factors), 4),
        "overcrowded_trips": overcrowded,
        "pct_overcrowded": round(overcrowded / len(trips), 4),
    }
