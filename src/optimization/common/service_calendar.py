"""Fail-closed service-calendar and weather-comparison contracts."""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Mapping, Sequence


_DAY_TOKEN = re.compile(
    r"(?:^|[.:_-])(Weekday|Saturday|Sunday|Holiday|SaturdayHoliday)(?:[.:_-]|$)",
    re.IGNORECASE,
)


def _normalize_day_type(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace("-", "").replace("_", "")
    if not text:
        return None
    if text in {"weekday", "weekdays", "平日"}:
        return "weekday"
    if text in {"saturday", "sat", "土曜", "土曜日"}:
        return "saturday"
    if text in {
        "sunday",
        "sun",
        "holiday",
        "日曜",
        "日曜日",
        "休日",
        "祝日",
    }:
        return "sunday_or_holiday"
    if text in {"saturdayholiday", "weekendholiday", "土休日"}:
        return "weekend_or_holiday"
    return None


def _trip_day_type(row: Mapping[str, Any]) -> str | None:
    for key in (
        "service_day_type",
        "serviceDayType",
        "day_type",
        "dayType",
        "calendar_type",
        "calendarType",
        "service_id",
        "serviceId",
    ):
        normalized = _normalize_day_type(row.get(key))
        if normalized:
            return normalized
    trip_id = str(row.get("trip_id") or row.get("tripId") or "")
    match = _DAY_TOKEN.search(trip_id)
    return _normalize_day_type(match.group(1)) if match else None


def _declared_holiday_dates(
    simulation_config: Mapping[str, Any],
) -> set[str]:
    raw = (
        simulation_config.get("holiday_dates")
        or simulation_config.get("holidayDates")
        or simulation_config.get("service_calendar_holidays")
        or ()
    )
    if isinstance(raw, Mapping):
        raw = [key for key, enabled in raw.items() if bool(enabled)]
    if isinstance(raw, (str, bytes)):
        raw = [raw]
    return {str(item)[:10] for item in raw if str(item).strip()}


def _calendar_day_type(
    service_date: date,
    *,
    declared_holiday_dates: set[str],
) -> str:
    if service_date.isoformat() in declared_holiday_dates:
        return "sunday_or_holiday"
    if service_date.weekday() < 5:
        return "weekday"
    if service_date.weekday() == 5:
        return "saturday"
    return "sunday_or_holiday"


def _comparison_type(simulation_config: Mapping[str, Any]) -> str:
    raw = str(
        simulation_config.get("comparison_type")
        or simulation_config.get("comparisonType")
        or simulation_config.get("comparison_design")
        or ""
    ).strip().lower()
    if raw in {
        "counterfactual_weather_profile",
        "same_service_date_pv_counterfactual",
        "pv_curve_counterfactual",
    }:
        return "counterfactual_weather_profile"
    return "actual_service_day"


def validate_service_calendar_contract(
    *,
    service_date_text: str,
    timetable_rows: Sequence[Mapping[str, Any]],
    scenario_metadata: Mapping[str, Any],
    strict: bool,
) -> dict[str, Any]:
    """Validate dates before timetable rows become canonical solver trips."""

    try:
        service_date = date.fromisoformat(str(service_date_text)[:10])
    except ValueError as exc:
        raise ValueError(
            f"service_date must be ISO date YYYY-MM-DD, got {service_date_text!r}"
        ) from exc
    simulation_config = dict(
        scenario_metadata.get("simulation_config") or {}
    )
    observed_types = sorted(
        {
            day_type
            for row in timetable_rows
            if isinstance(row, Mapping)
            for day_type in [_trip_day_type(row)]
            if day_type
        }
    )
    declared_holiday_dates = _declared_holiday_dates(simulation_config)
    expected_type = _calendar_day_type(
        service_date,
        declared_holiday_dates=declared_holiday_dates,
    )
    comparison_type = _comparison_type(simulation_config)
    weather_observation_date = str(
        simulation_config.get("weather_observation_date")
        or simulation_config.get("weatherObservationDate")
        or simulation_config.get("weather_reference_date")
        or service_date.isoformat()
    )[:10]
    weather_profile_source = str(
        simulation_config.get("weather_profile_source")
        or simulation_config.get("weatherProfileSource")
        or simulation_config.get("weather_source")
        or ""
    ).strip()
    errors: list[str] = []
    if not observed_types:
        errors.append("timetable_service_day_type_unverifiable")
    elif any(
        observed_type != expected_type
        and not (
            observed_type == "weekend_or_holiday"
            and expected_type in {"saturday", "sunday_or_holiday"}
        )
        for observed_type in observed_types
    ):
        errors.append("service_date_timetable_day_type_mismatch")
    if (
        comparison_type == "actual_service_day"
        and weather_observation_date != service_date.isoformat()
    ):
        errors.append("actual_weather_date_differs_from_service_date")
    result = {
        "schema_version": "service_calendar_validation_v1",
        "status": "ERROR" if errors else "OK",
        "strict": bool(strict),
        "service_date": service_date.isoformat(),
        "service_date_weekday": service_date.strftime("%A"),
        "service_date_declared_holiday": (
            service_date.isoformat() in declared_holiday_dates
        ),
        "expected_service_day_type": expected_type,
        "observed_timetable_day_types": observed_types,
        "timetable_row_count": len(timetable_rows),
        "comparison_type": comparison_type,
        "weather_observation_date": weather_observation_date,
        "weather_profile_source": weather_profile_source or None,
        "service_date_weather_date_equal": (
            weather_observation_date == service_date.isoformat()
        ),
        "service_date_forecast_claim": (
            comparison_type == "actual_service_day"
            and weather_observation_date == service_date.isoformat()
        ),
        "errors": errors,
    }
    if strict and errors:
        raise ValueError(
            "research service-calendar contract failed: " + ", ".join(errors)
        )
    return result
