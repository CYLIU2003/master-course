"""Classify Solcast daily PV profiles into sunny/cloudy/rainy classes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import quantiles
from typing import Any, Mapping

from src.preprocess.weather.daily_weather_schema import WeatherSchemaError

from .loader import SolcastDailyPvProfile

WEATHER_CLASSES = ("rainy", "cloudy", "sunny")
MIN_NONZERO_SLOTS = 3
MIN_DAILY_CF_HOURS = 0.1
MIN_QUANTILE_DAYS = 15
FIXED_RAINY_THRESHOLD_CF_HOURS = 4.0
FIXED_SUNNY_THRESHOLD_CF_HOURS = 5.5


@dataclass(frozen=True)
class SolcastClassifiedDay:
    date: str
    weather_class: str
    daily_cf_hours: float
    nonzero_slots: int
    depot_id: str
    source_path: str


@dataclass(frozen=True)
class SolcastClassificationResult:
    method: str
    thresholds: Mapping[str, float]
    classified_days: tuple[SolcastClassifiedDay, ...]
    excluded_dates: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "thresholds": dict(self.thresholds),
            "classified_days": [asdict(item) for item in self.classified_days],
            "excluded_dates": [dict(item) for item in self.excluded_dates],
        }


def daily_cf_hours(profile: SolcastDailyPvProfile) -> float:
    return float(sum(profile.capacity_factor_by_slot)) * float(profile.slot_minutes) / 60.0


def nonzero_slot_count(profile: SolcastDailyPvProfile) -> int:
    return sum(1 for value in profile.capacity_factor_by_slot if float(value) > 1.0e-6)


def _is_valid_profile(profile: SolcastDailyPvProfile) -> tuple[bool, str]:
    if nonzero_slot_count(profile) < MIN_NONZERO_SLOTS:
        return False, "nonzero_slots_lt_3"
    if daily_cf_hours(profile) <= MIN_DAILY_CF_HOURS:
        return False, "daily_cf_hours_le_0.1"
    return True, ""


def _quantile_thresholds(values: list[float]) -> tuple[float, float]:
    cuts = quantiles(sorted(values), n=3, method="inclusive")
    return float(cuts[0]), float(cuts[1])


def _classify_value(value: float, rainy_threshold: float, sunny_threshold: float) -> str:
    if value <= rainy_threshold:
        return "rainy"
    if value >= sunny_threshold:
        return "sunny"
    return "cloudy"


def classify_solcast_daily_profiles(
    profiles: tuple[SolcastDailyPvProfile, ...] | list[SolcastDailyPvProfile],
    *,
    min_quantile_days: int = MIN_QUANTILE_DAYS,
) -> SolcastClassificationResult:
    valid: list[tuple[SolcastDailyPvProfile, float, int]] = []
    excluded: list[dict[str, Any]] = []
    for profile in profiles:
        cf_hours = round(daily_cf_hours(profile), 6)
        nonzero_slots = nonzero_slot_count(profile)
        is_valid, reason = _is_valid_profile(profile)
        if not is_valid:
            excluded.append(
                {
                    "date": profile.date,
                    "depot_id": profile.depot_id,
                    "reason": reason,
                    "daily_cf_hours": cf_hours,
                    "nonzero_slots": nonzero_slots,
                    "source_path": profile.source_path,
                }
            )
            continue
        valid.append((profile, cf_hours, nonzero_slots))
    if not valid:
        raise WeatherSchemaError("No valid Solcast PV days remain after missing-day exclusion")

    values = [cf_hours for _, cf_hours, _ in valid]
    if len(valid) >= int(min_quantile_days):
        rainy_threshold, sunny_threshold = _quantile_thresholds(values)
        method = "quantile_33_67_by_daily_cf_hours"
    else:
        rainy_threshold = FIXED_RAINY_THRESHOLD_CF_HOURS
        sunny_threshold = FIXED_SUNNY_THRESHOLD_CF_HOURS
        method = "fixed_threshold_daily_cf_hours_fallback"

    classified = tuple(
        SolcastClassifiedDay(
            date=profile.date,
            weather_class=_classify_value(cf_hours, rainy_threshold, sunny_threshold),
            daily_cf_hours=cf_hours,
            nonzero_slots=nonzero_slots,
            depot_id=profile.depot_id,
            source_path=profile.source_path,
        )
        for profile, cf_hours, nonzero_slots in sorted(valid, key=lambda item: item[0].date)
    )
    return SolcastClassificationResult(
        method=method,
        thresholds={
            "rainy_daily_cf_hours_max": round(rainy_threshold, 6),
            "sunny_daily_cf_hours_min": round(sunny_threshold, 6),
            "min_nonzero_slots": float(MIN_NONZERO_SLOTS),
            "min_daily_cf_hours": float(MIN_DAILY_CF_HOURS),
            "min_quantile_days": float(min_quantile_days),
        },
        classified_days=classified,
        excluded_dates=tuple(excluded),
    )
