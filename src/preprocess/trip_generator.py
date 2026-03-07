"""
src.preprocess.trip_generator — route-detail layer から GeneratedTrip を生成

spec_v3 §4.1 / §10.3 / agent_route_editable §2.2
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.schemas.route_entities import (
    GeneratedTrip,
    RouteVariant,
    Segment,
    TimetablePattern,
)
from src.schemas.fleet_entities import VehicleType
from src.preprocess.timetable_generator import generate_departure_times
from src.preprocess.energy_model import estimate_trip_energy_bev, estimate_trip_fuel_ice_from_segments


def _parse_time(time_str: str) -> datetime:
    return datetime.strptime(time_str, "%H:%M")


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def generate_trip_from_variant(
    variant: RouteVariant,
    segments: List[Segment],
    departure_time_str: str,
    service_day_type: str,
    energy_model_level: int = 1,
    vehicle_type: Optional[VehicleType] = None,
    trip_id_prefix: str = "trip",
    trip_index: int = 0,
) -> GeneratedTrip:
    """RouteVariant + 出発時刻 → GeneratedTrip を生成する。

    Parameters
    ----------
    variant : RouteVariant
    segments : List[Segment]   variant に対応する Segment リスト (sequence 順)
    departure_time_str : str   "HH:MM"
    service_day_type   : str   "weekday" | "saturday" | "holiday"
    energy_model_level : int   0 | 1 | 2  (spec_v3 §5.2)
    vehicle_type : Optional[VehicleType]  None の場合デフォルト係数使用
    """
    total_dist = sum(s.distance_km for s in segments)
    total_run_min = sum(s.scheduled_run_time_min for s in segments)

    departure_dt = _parse_time(departure_time_str)
    arrival_dt = departure_dt + timedelta(minutes=total_run_min)

    origin_stop = segments[0].from_stop_id if segments else ""
    dest_stop = segments[-1].to_stop_id if segments else ""

    trip_id = f"{trip_id_prefix}_{variant.route_id}_{variant.direction_id}_{trip_index:04d}"

    trip = GeneratedTrip(
        trip_id=trip_id,
        route_id=variant.route_id,
        direction_id=variant.direction_id,
        variant_id=variant.variant_id,
        service_day_type=service_day_type,
        departure_time=departure_time_str,
        arrival_time=_fmt_time(arrival_dt),
        origin_terminal_id=origin_stop,
        destination_terminal_id=dest_stop,
        distance_km=round(total_dist, 4),
        scheduled_runtime_min=round(total_run_min, 2),
        trip_category="revenue",
    )

    if energy_model_level >= 1 and vehicle_type is not None:
        energy_kwh, energy_bd = estimate_trip_energy_bev(
            segments=segments,
            vehicle_type=vehicle_type,
            level=energy_model_level,
        )
        fuel_l, fuel_bd = estimate_trip_fuel_ice_from_segments(
            segments=segments,
            vehicle_type=vehicle_type,
        )
        trip.estimated_energy_kwh_bev = round(energy_kwh, 4)
        trip.estimated_fuel_l_ice = round(fuel_l, 4)
        trip.estimated_energy_rate_kwh_per_km = round(energy_kwh / total_dist, 4) if total_dist > 0 else None
        trip.estimated_fuel_rate_l_per_km = round(fuel_l / total_dist, 4) if total_dist > 0 else None
        trip.energy_breakdown = energy_bd
        trip.fuel_breakdown = fuel_bd
    elif energy_model_level == 0 and vehicle_type is not None:
        # Level 0: base rate × distance
        rate_e = vehicle_type.base_energy_rate_kwh_per_km or 1.2
        rate_f = vehicle_type.base_fuel_rate_l_per_km or 0.3
        trip.estimated_energy_kwh_bev = round(rate_e * total_dist, 4)
        trip.estimated_fuel_l_ice = round(rate_f * total_dist, 4)
        trip.energy_breakdown = {"distance": trip.estimated_energy_kwh_bev}
        trip.fuel_breakdown = {"distance": trip.estimated_fuel_l_ice}

    return trip


def generate_all_trips(
    variants: List[RouteVariant],
    seg_index: Dict[str, Segment],
    patterns: List[TimetablePattern],
    service_day_type: str = "weekday",
    energy_model_level: int = 1,
    vehicle_type: Optional[VehicleType] = None,
) -> List[GeneratedTrip]:
    """全 Variant × TimetablePattern から GeneratedTrip を一括生成する。

    Parameters
    ----------
    variants : List[RouteVariant]
    seg_index : Dict[str, Segment]  segment_id → Segment
    patterns : List[TimetablePattern]
    service_day_type : str
    energy_model_level : int
    vehicle_type : Optional[VehicleType]

    Returns
    -------
    List[GeneratedTrip] : 全 trip リスト（departure_time 昇順）
    """
    # variant_id → pattern マッピング
    pattern_map: Dict[str, TimetablePattern] = {}
    for p in patterns:
        if p.service_day_type == service_day_type:
            pattern_map[p.variant_id] = p

    all_trips: List[GeneratedTrip] = []
    global_idx = 0

    for variant in variants:
        pattern = pattern_map.get(variant.variant_id)
        if pattern is None:
            continue

        segments = [seg_index[sid] for sid in variant.segment_id_list if sid in seg_index]
        if not segments:
            continue

        dep_times = generate_departure_times(pattern)
        for dep in dep_times:
            trip = generate_trip_from_variant(
                variant=variant,
                segments=segments,
                departure_time_str=dep,
                service_day_type=service_day_type,
                energy_model_level=energy_model_level,
                vehicle_type=vehicle_type,
                trip_index=global_idx,
            )
            all_trips.append(trip)
            global_idx += 1

    all_trips.sort(key=lambda t: t.departure_time)
    return all_trips
