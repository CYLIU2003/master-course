"""Fail-closed service-calendar and weather-comparison contracts."""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Mapping, Sequence

from src.service_day_types import normalize_service_day_type


_DAY_TOKEN = re.compile(
    r"(?:^|[.:_-])(Weekday|Saturday|Sunday|Holiday|SaturdayHoliday)(?:[.:_-]|$)",
    re.IGNORECASE,
)


FIXED_WEEKDAY_TIMETABLE_PV_COUNTERFACTUAL = (
    "fixed_weekday_timetable_pv_counterfactual"
)


def _normalize_day_type(value: Any) -> str | None:
    return normalize_service_day_type(value)


def _trip_day_type(row: Mapping[str, Any]) -> str | None:
    types, unknown = _trip_day_type_evidence(row)
    return next(iter(types)) if len(types) == 1 and not unknown else None


def _trip_day_type_evidence(row: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    types: set[str] = set()
    unknown: list[str] = []
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
        if row.get(key) in (None, ""):
            continue
        normalized = _normalize_day_type(row[key])
        if normalized:
            types.add(normalized)
        else:
            unknown.append(key)
    trip_id = str(row.get("trip_id") or row.get("tripId") or "")
    match = _DAY_TOKEN.search(trip_id)
    if match:
        types.add(_normalize_day_type(match.group(1)))
    return types, unknown


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
    if raw == FIXED_WEEKDAY_TIMETABLE_PV_COUNTERFACTUAL:
        return FIXED_WEEKDAY_TIMETABLE_PV_COUNTERFACTUAL
    if raw in {
        "counterfactual_weather_profile",
        "same_service_date_pv_counterfactual",
        "pv_curve_counterfactual",
    }:
        return "counterfactual_weather_profile"
    return "actual_service_day"


def _fixed_weekday_timetable_pv_counterfactual_waiver(
    *,
    service_date: date,
    observed_types: Sequence[str],
    simulation_config: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the narrowly-scoped weekday-on-Sunday waiver, if declared.

    The exception exists only for the explicitly labelled PV supply
    counterfactual used by the research runner.  It does not make a Sunday
    timetable interchangeable with a weekday timetable, and it deliberately
    cannot waive fleet, trip, SOC, charger, or energy-balance contracts.
    """

    policy = str(simulation_config.get("calendar_policy") or "").strip()
    enabled = bool(
        simulation_config.get(
            "allow_fixed_weekday_timetable_pv_counterfactual", False
        )
    )
    if (
        not enabled
        or policy != FIXED_WEEKDAY_TIMETABLE_PV_COUNTERFACTUAL
        or service_date.weekday() != 6
        or set(observed_types) != {"weekday"}
    ):
        return None
    return {
        "calendar_policy": FIXED_WEEKDAY_TIMETABLE_PV_COUNTERFACTUAL,
        "calendar_validation_status": "WAIVED_BY_EXPERIMENT_POLICY",
        "scope": "weekday_timetable_on_sunday_for_pv_only_counterfactual",
        "rationale": (
            "A Sunday weather/PV profile is evaluated with the weekday timetable "
            "held fixed. This is not actual Sunday operation."
        ),
    }


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
    observed: set[str] = set()
    unknown_rows: list[int] = []
    conflicting_rows: list[int] = []
    for index, row in enumerate(timetable_rows):
        types, unknown = _trip_day_type_evidence(row) if isinstance(row, Mapping) else (set(), ["row"])
        observed.update(types)
        if unknown or not types:
            unknown_rows.append(index)
        if len(types) > 1:
            conflicting_rows.append(index)
    observed_types = sorted(observed)
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
    if unknown_rows:
        errors.append("timetable_service_day_type_unknown_rows")
    if conflicting_rows:
        errors.append("timetable_service_day_type_conflicting_fields")
    waiver = _fixed_weekday_timetable_pv_counterfactual_waiver(
        service_date=service_date,
        observed_types=observed_types,
        simulation_config=simulation_config,
    )
    effective_comparison_type = (
        FIXED_WEEKDAY_TIMETABLE_PV_COUNTERFACTUAL
        if waiver is not None
        else comparison_type
    )
    if not observed_types:
        errors.append("timetable_service_day_type_unverifiable")
    elif any(
        observed_type != expected_type
        and not (
            observed_type == "weekend_or_holiday"
            and expected_type in {"saturday", "sunday_or_holiday"}
        )
        for observed_type in observed_types
    ) and waiver is None:
        errors.append("service_date_timetable_day_type_mismatch")
    if (
        effective_comparison_type == "actual_service_day"
        and weather_observation_date != service_date.isoformat()
    ):
        errors.append("actual_weather_date_differs_from_service_date")
    result = {
        "schema_version": "service_calendar_validation_v1",
        "status": (
            "ERROR"
            if errors
            else "WAIVED_BY_EXPERIMENT_POLICY"
            if waiver is not None
            else "OK"
        ),
        "strict": bool(strict),
        "service_date": service_date.isoformat(),
        "service_date_weekday": service_date.strftime("%A"),
        "service_date_declared_holiday": (
            service_date.isoformat() in declared_holiday_dates
        ),
        "expected_service_day_type": expected_type,
        "observed_timetable_day_types": observed_types,
        "timetable_row_count": len(timetable_rows),
        "unknown_timetable_row_count": len(unknown_rows),
        "unknown_timetable_row_indices": unknown_rows,
        "conflicting_timetable_row_indices": conflicting_rows,
        "comparison_type": effective_comparison_type,
        "weather_observation_date": weather_observation_date,
        "weather_profile_source": weather_profile_source or None,
        "service_date_weather_date_equal": (
            weather_observation_date == service_date.isoformat()
        ),
        "service_date_forecast_claim": (
            effective_comparison_type == "actual_service_day"
            and weather_observation_date == service_date.isoformat()
        ),
        "errors": errors,
        "calendar_policy": waiver.get("calendar_policy") if waiver else None,
        "calendar_validation_status": (
            waiver.get("calendar_validation_status") if waiver else "matched"
        ),
        "waiver": waiver,
    }
    if strict and errors:
        raise ValueError(
            "research service-calendar contract failed: " + ", ".join(errors)
        )
    return result
