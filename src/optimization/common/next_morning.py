"""Verified energy-horizon extension for a dated bus service period.

The following morning has no service trips in the optimization. Its timetable is
evidence for the charging deadline; PV and the declared tariff cover every
additional energy slot. A slot ending after the first departure is excluded.
"""

from __future__ import annotations

from datetime import date, timedelta
import math
from typing import Any, Mapping, Sequence

from .date_series import content_hash, timetable_hash


SCHEMA = "bev_next_morning_overnight_v1"
PRICE_POLICY = "repeat_the_declared_fixed_daily_tariff"


def _clock_minute(value: object) -> int:
    parts = str(value).split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("NEXT_MORNING_INVALID_CLOCK")
    hour, minute = map(int, parts)
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError("NEXT_MORNING_INVALID_CLOCK")
    return hour * 60 + minute


def _first_departure(rows: Sequence[Mapping[str, Any]], day: str) -> int:
    selected = [row for row in rows if row.get("service_date") == day]
    if not selected:
        raise ValueError(f"NEXT_MORNING_TIMETABLE_MISSING: {day}")
    if any(
        not str(row.get("operator_id") or "").strip()
        or str(row["operator_id"]).upper() == "UNKNOWN"
        or not row.get("distance_source")
        or not math.isfinite(float(row.get("distance_km") or 0))
        or float(row.get("distance_km") or 0) <= 0
        for row in selected
    ):
        raise ValueError(f"NEXT_MORNING_TIMETABLE_INVALID: {day}")
    return min(_clock_minute(row.get("source_departure")) for row in selected)


def resolve_next_morning_contract(
    config: Mapping[str, Any],
    *,
    timestep_min: int,
    timetable_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return slot indices only after the extra timetable/PV evidence agrees."""
    contract = config.get("terminal_overnight_contract")
    if not isinstance(contract, Mapping) or contract.get("schema_version") != SCHEMA:
        raise ValueError("NEXT_MORNING_CONTRACT_MISSING")
    dates = config.get("service_dates")
    if not isinstance(dates, list) or not 1 <= len(dates) <= 7:
        raise ValueError("NEXT_MORNING_REQUIRES_ONE_TO_SEVEN_SERVICE_DATES")
    day_count = len(dates)
    try:
        first = date.fromisoformat(str(dates[0]))
        expected_dates = [(first + timedelta(days=index)).isoformat() for index in range(day_count)]
        next_date = (first + timedelta(days=day_count)).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("NEXT_MORNING_INVALID_SERVICE_DATES") from exc
    if list(dates) != expected_dates or contract.get("service_dates") != expected_dates:
        raise ValueError("NEXT_MORNING_SERVICE_DATES_MISMATCH")
    if contract.get("next_service_date") != next_date:
        raise ValueError("NEXT_MORNING_NEXT_DATE_MISMATCH")
    if contract.get("price_calendar_policy") != PRICE_POLICY:
        raise ValueError("NEXT_MORNING_TARIFF_UNVERIFIED")
    step = int(timestep_min)
    if step <= 0 or 1440 % step:
        raise ValueError("NEXT_MORNING_INVALID_TIMESTEP")
    next_rows = contract.get("next_day_timetable_rows")
    if not isinstance(next_rows, list) or not next_rows or any(
        row.get("service_date") != next_date or row.get("day_index") != day_count
        for row in next_rows if isinstance(row, Mapping)
    ) or any(not isinstance(row, Mapping) for row in next_rows):
        raise ValueError("NEXT_MORNING_NEXT_TIMETABLE_INVALID")
    if timetable_hash(next_rows) != contract.get("next_day_timetable_rows_sha256"):
        raise ValueError("NEXT_MORNING_NEXT_TIMETABLE_HASH_MISMATCH")
    first_minutes = contract.get("first_departure_minute_by_next_day")
    if not isinstance(first_minutes, list) or len(first_minutes) != day_count or any(
        isinstance(value, bool) or not isinstance(value, int) or not step <= value < 1440
        for value in first_minutes
    ):
        raise ValueError("NEXT_MORNING_DEADLINES_INVALID")
    if first_minutes[-1] != _first_departure(next_rows, next_date):
        raise ValueError("NEXT_MORNING_FINAL_DEADLINE_MISMATCH")
    if timetable_rows is not None:
        for index in range(day_count - 1):
            if first_minutes[index] != _first_departure(timetable_rows, dates[index + 1]):
                raise ValueError("NEXT_MORNING_DAILY_DEADLINE_MISMATCH")
    def verified_pv_factors(row_key: str, hash_key: str) -> list[float]:
        row = contract.get(row_key)
        if not isinstance(row, Mapping) or row.get("date") != next_date:
            raise ValueError("NEXT_MORNING_PV_DATE_MISMATCH")
        pv_step = row.get("slot_minutes")
        if isinstance(pv_step, bool) or pv_step != step:
            raise ValueError("NEXT_MORNING_PV_STEP_MISMATCH")
        values = row.get("capacity_factor_by_slot")
        if not isinstance(values, list) or len(values) != 1440 // step or any(
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in values
        ):
            raise ValueError("NEXT_MORNING_PV_INCOMPLETE")
        if content_hash(row) != contract.get(hash_key):
            raise ValueError("NEXT_MORNING_PV_HASH_MISMATCH")
        return values

    forecast_factors = verified_pv_factors("next_day_pv_capacity_factor", "next_day_pv_sha256")
    actual_factors = verified_pv_factors(
        "next_day_actual_pv_capacity_factor", "next_day_actual_pv_sha256"
    )
    source_hashes = contract.get("next_day_actual_pv_source_sha256")
    if not isinstance(source_hashes, list) or not source_hashes or any(
        not isinstance(value, str) or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in source_hashes
    ):
        raise ValueError("NEXT_MORNING_ACTUAL_PV_SOURCE_MISSING")
    slots_per_day = 1440 // step
    extra_slots = first_minutes[-1] // step
    return {
        "extra_slots": extra_slots,
        "target_slots": [
            (index + 1) * slots_per_day + departure // step - 1
            for index, departure in enumerate(first_minutes)
        ],
        "next_day_pv_factors": tuple(float(value) for value in forecast_factors[:extra_slots]),
        "next_day_actual_pv_factors": tuple(float(value) for value in actual_factors[:extra_slots]),
        "next_service_date": next_date,
        "first_departure_minute_by_next_day": list(first_minutes),
    }
