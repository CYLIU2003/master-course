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
    csv_path,
) -> List[Dict[str, str]]:
    """passenger_load_profile.csv を読み込む。

    CSV 形式:
        route_id, direction_id, time_band, load_factor, boarding_rate, alighting_rate

    Returns
    -------
    List[Dict[str, str]]
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"  [warn] {csv_path} が存在しません")
        return []
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_load_factor_map(
    profile_rows: List[Dict[str, str]],
) -> Dict[Tuple[str, str, str], float]:
    """(route_id, direction_id, time_band) → load_factor マッピングを構築。

    2 つの CSV 形式に対応:
      - 形式A: route_id, direction_id, time_band, load_factor
      - 形式B: period_start, period_end, passenger_load_factor, day_type  (HH:MM)

    形式B の場合は period を time_band に自動変換し、route_id="" として格納する。
    """
    mapping: Dict[Tuple[str, str, str], float] = {}

    if profile_rows and "period_start" in profile_rows[0]:
        # 形式B: 時刻帯ベース → time_band に変換
        for row in profile_rows:
            try:
                ps = row.get("period_start", "00:00")
                lf = float(row.get("passenger_load_factor", row.get("load_factor", "0.5")))
                day_type = row.get("day_type", "weekday")
            except (ValueError, TypeError):
                continue
            band = _classify_time_band(ps)
            # route_id="", direction_id="" で全路線共通
            key = ("", "", f"{band}_{day_type}")
            mapping[key] = lf
            # day_type なしのフォールバックも登録
            mapping.setdefault(("", "", band), lf)
    else:
        # 形式A: route_id / direction_id / time_band
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
    default_factor: float = 0.5,
) -> List[GeneratedTrip]:
    """各 trip に対する passenger_load_factor を決定し、trip に付与して返す。

    Returns
    -------
    List[GeneratedTrip]  (元のリストをそのまま返す; load_factor は trip 属性に設定)
    """
    for trip in trips:
        band = _classify_time_band(trip.departure_time)
        key = (trip.route_id, trip.direction_id, band)
        lf = load_factor_map.get(key)
        if lf is None:
            # fallback: route_id + all_day
            lf = load_factor_map.get((trip.route_id, trip.direction_id, "all_day"))
        if lf is None:
            # fallback: route_id="" (全路線共通)
            lf = load_factor_map.get(("", "", band))
        if lf is None:
            lf = load_factor_map.get(("", "", "all_day"))
        if lf is None:
            lf = default_factor
        # GeneratedTrip にload_factor属性を動的に付与
        trip.passenger_load_factor = lf  # type: ignore[attr-defined]
    return trips


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
