"""Historical analog day selection without target-day weather leakage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .daily_weather_schema import DailyWeatherObservation


class NoAnalogCandidateError(ValueError):
    """Raised when no historical candidate satisfies the v1 contract."""


@dataclass(frozen=True)
class AnalogSelection:
    observation: DailyWeatherObservation
    metadata: Dict[str, Any]


def _parse_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def _service_class(value: date) -> str:
    if value.weekday() == 5:
        return "saturday"
    if value.weekday() == 6:
        return "holiday"
    return "weekday"


def _month_distance(a: date, d: date) -> float:
    raw = abs(a.month - d.month)
    return float(min(raw, 12 - raw))


def _day_of_year_distance(a: date, d: date) -> float:
    raw = abs(a.timetuple().tm_yday - d.timetuple().tm_yday)
    return float(min(raw, 366 - raw)) / 30.0


def _candidate_window(service_date: date, candidate_date: date, years: int) -> bool:
    return service_date - timedelta(days=365 * years) <= candidate_date < service_date


def _has_weather_signal(obs: DailyWeatherObservation) -> bool:
    return obs.sunshine_hours is not None or obs.precipitation_mm is not None


def _normalize_candidates(
    observations: Iterable[DailyWeatherObservation],
    *,
    station_id: str,
    service_date: date,
    years: int,
) -> List[DailyWeatherObservation]:
    candidates: List[DailyWeatherObservation] = []
    for obs in observations:
        obs_date = _parse_date(obs.date)
        if str(obs.station_id) != str(station_id):
            continue
        if not _candidate_window(service_date, obs_date, years):
            continue
        if str(obs.quality_flag).lower() == "missing":
            continue
        if not _has_weather_signal(obs):
            continue
        candidates.append(obs)
    return candidates


def _score_previous_day_features(
    candidate_prev: DailyWeatherObservation | None,
    target_prev: DailyWeatherObservation | None,
) -> tuple[float, list[str], str | None]:
    if target_prev is None:
        return 0.0, [], "missing_previous_day_actual"
    if candidate_prev is None:
        return 2.0, [], "missing_candidate_previous_day_actual"
    weighted_terms = (
        ("prev_tmax_c", 1.0, candidate_prev.tmax_c, target_prev.tmax_c, 10.0),
        ("prev_tmin_c", 1.0, candidate_prev.tmin_c, target_prev.tmin_c, 10.0),
        (
            "prev_sunshine_hours",
            1.5,
            candidate_prev.sunshine_hours,
            target_prev.sunshine_hours,
            10.0,
        ),
        (
            "prev_precipitation_mm",
            1.5,
            candidate_prev.precipitation_mm,
            target_prev.precipitation_mm,
            30.0,
        ),
    )
    total = 0.0
    weight_sum = 0.0
    features: list[str] = []
    for name, weight, candidate_value, target_value, divisor in weighted_terms:
        if candidate_value is None or target_value is None:
            continue
        total += weight * abs(float(candidate_value) - float(target_value)) / divisor
        weight_sum += weight
        features.append(name)
    if weight_sum <= 0.0:
        return 2.0, [], "missing_previous_day_comparable_features"
    return total / weight_sum, features, None


def _score_candidate(
    candidate: DailyWeatherObservation,
    *,
    service_date: date,
    previous_by_date: Mapping[date, DailyWeatherObservation],
) -> tuple[float, list[str], str | None]:
    candidate_date = _parse_date(candidate.date)
    calendar_score = (
        0.8 * _month_distance(candidate_date, service_date)
        + 0.5 * _day_of_year_distance(candidate_date, service_date)
        + 3.0 * float(_service_class(candidate_date) != _service_class(service_date))
    )
    candidate_prev = previous_by_date.get(candidate_date - timedelta(days=1))
    target_prev = previous_by_date.get(service_date - timedelta(days=1))
    previous_score, previous_features, fallback_reason = _score_previous_day_features(
        candidate_prev,
        target_prev,
    )
    features = ["month_distance", "day_of_year_distance", "service_class"]
    features.extend(previous_features)
    return calendar_score + previous_score, features, fallback_reason


def select_historical_analog(
    *,
    service_date: str,
    station_id: str,
    observations: Iterable[DailyWeatherObservation],
    default_years: int = 3,
    fallback_years: int = 5,
) -> AnalogSelection:
    target_date = _parse_date(service_date)
    all_observations = list(observations)
    observations_by_date = {
        _parse_date(obs.date): obs
        for obs in all_observations
        if str(obs.station_id) == str(station_id)
    }
    candidates = _normalize_candidates(
        all_observations,
        station_id=station_id,
        service_date=target_date,
        years=default_years,
    )
    expanded_to_fallback_years = False
    if not candidates and fallback_years > default_years:
        expanded_to_fallback_years = True
        candidates = _normalize_candidates(
            all_observations,
            station_id=station_id,
            service_date=target_date,
            years=fallback_years,
        )
    if not candidates:
        raise NoAnalogCandidateError(
            f"No historical analog candidates for station={station_id} before {service_date}"
        )

    scored: list[tuple[float, str, DailyWeatherObservation, list[str], str | None]] = []
    for candidate in candidates:
        score, features, fallback_reason = _score_candidate(
            candidate,
            service_date=target_date,
            previous_by_date=observations_by_date,
        )
        if not math.isfinite(score):
            continue
        scored.append((score, candidate.date, candidate, features, fallback_reason))
    if not scored:
        raise NoAnalogCandidateError("All analog candidates scored as invalid")
    score, _date_key, selected, features_used, fallback_reason = min(scored, key=lambda item: (item[0], item[1]))
    if _parse_date(selected.date) >= target_date:
        raise NoAnalogCandidateError("Future leakage guard rejected selected analog_date")
    metadata: Dict[str, Any] = {
        "candidate_count": len(candidates),
        "features_used": sorted(dict.fromkeys(features_used)),
        "analog_selection_method": "calendar_plus_previous_day_weather_v1",
        "analog_selection_score": float(score),
        "default_years": int(default_years),
        "fallback_years": int(fallback_years),
        "expanded_to_fallback_years": bool(expanded_to_fallback_years),
        "no_future_leakage": True,
    }
    if fallback_reason:
        metadata["analog_fallback_reason"] = fallback_reason
    return AnalogSelection(
        observation=selected,
        metadata=metadata,
    )
