"""Aggregate classified Solcast days into representative PV curves."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import fmean, pstdev
from typing import Any, Mapping

from src.preprocess.weather.daily_weather_schema import WeatherSchemaError

from .classify import WEATHER_CLASSES, SolcastClassificationResult, classify_solcast_daily_profiles
from .loader import SolcastDailyPvProfile

REPRESENTATIVE_CURVE_VERSION = "solcast_typical_pv_representative_curve_v1"


def _profiles_by_date(
    profiles: tuple[SolcastDailyPvProfile, ...] | list[SolcastDailyPvProfile],
) -> dict[str, SolcastDailyPvProfile]:
    return {profile.date: profile for profile in profiles}


def _average_curve(profiles: list[SolcastDailyPvProfile]) -> tuple[list[float], list[float]]:
    if not profiles:
        return [], []
    slot_minutes = profiles[0].slot_minutes
    slot_count = len(profiles[0].capacity_factor_by_slot)
    for profile in profiles:
        if profile.slot_minutes != slot_minutes or len(profile.capacity_factor_by_slot) != slot_count:
            raise WeatherSchemaError("All profiles in one representative set must share slot cadence")
    averages: list[float] = []
    stddevs: list[float] = []
    for slot_idx in range(slot_count):
        values = [float(profile.capacity_factor_by_slot[slot_idx]) for profile in profiles]
        averages.append(round(fmean(values), 6))
        stddevs.append(round(pstdev(values), 6) if len(values) > 1 else 0.0)
    return averages, stddevs


def build_representative_curve_payload(
    profiles: tuple[SolcastDailyPvProfile, ...] | list[SolcastDailyPvProfile],
    *,
    station_id: str | None = None,
    station_name: str | None = None,
    depot_id: str | None = None,
    classification: SolcastClassificationResult | None = None,
) -> dict[str, Any]:
    if not profiles:
        raise WeatherSchemaError("profiles must not be empty")
    profiles_tuple = tuple(profiles)
    classification_result = classification or classify_solcast_daily_profiles(profiles_tuple)
    by_date = _profiles_by_date(profiles_tuple)
    curves: dict[str, dict[str, Any]] = {}
    for weather_class in WEATHER_CLASSES:
        source_days = [
            day
            for day in classification_result.classified_days
            if day.weather_class == weather_class and day.date in by_date
        ]
        class_profiles = [by_date[day.date] for day in source_days]
        capacity_factor_by_slot, stddev_by_slot = _average_curve(class_profiles)
        if class_profiles:
            slot_minutes = int(class_profiles[0].slot_minutes)
            daily_cf_hours_values = [float(day.daily_cf_hours) for day in source_days]
            daily_cf_hours_avg = round(fmean(daily_cf_hours_values), 6)
        else:
            slot_minutes = int(profiles_tuple[0].slot_minutes)
            daily_cf_hours_avg = 0.0
        curves[weather_class] = {
            "weather_class": weather_class,
            "slot_minutes": slot_minutes,
            "slot_count": int(1440 // max(slot_minutes, 1)),
            "capacity_factor_by_slot": capacity_factor_by_slot,
            "capacity_factor_stddev_by_slot": stddev_by_slot,
            "source_dates": [day.date for day in source_days],
            "source_profile_count": len(source_days),
            "daily_cf_hours_avg": daily_cf_hours_avg,
        }

    source_dates = sorted({profile.date for profile in profiles_tuple})
    depot_ids = sorted({profile.depot_id for profile in profiles_tuple})
    return {
        "version": REPRESENTATIVE_CURVE_VERSION,
        "source": "solcast_daily_pv_profiles",
        "station_id": str(station_id or ""),
        "station_name": str(station_name or ""),
        "depot_id": str(depot_id or (depot_ids[0] if len(depot_ids) == 1 else "")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_date_start": source_dates[0],
        "source_date_end": source_dates[-1],
        "source_dates": source_dates,
        "source_date_count": len(source_dates),
        "classification": classification_result.to_dict(),
        "curves": curves,
    }


def representative_curve_for_class(
    payload: Mapping[str, Any],
    weather_class: str,
) -> dict[str, Any]:
    curves = payload.get("curves")
    if not isinstance(curves, Mapping):
        raise WeatherSchemaError("representative curve payload must contain curves")
    curve = curves.get(str(weather_class))
    if not isinstance(curve, Mapping):
        raise WeatherSchemaError(f"representative curve missing weather_class={weather_class!r}")
    return dict(curve)
