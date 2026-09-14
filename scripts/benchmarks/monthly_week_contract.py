"""Calendar selection and materialized-input checks for balanced monthly weeks."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from src.optimization.common.date_series import validate_dated_timetable


EXPECTED_DAY_COUNTS = {"weekday": 5, "saturday": 1, "sunday_or_holiday": 1}


def select_monthly_weeks(year: int, holiday_dates: list[str]) -> list[str]:
    """Choose the earliest holiday-free complete week without consulting outcomes."""
    holidays = set(holiday_dates)
    selected = []
    for month in range(1, 13):
        start = date(year, month, 1)
        start += timedelta(days=(-start.weekday()) % 7)
        while (start + timedelta(days=6)).month == month:
            days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
            if not holidays.intersection(days):
                selected.append(start.isoformat())
                break
            start += timedelta(days=7)
        else:
            raise ValueError(f"No holiday-free complete week in {year}-{month:02d}")
    return selected


def validate_balanced_week(rows: list[dict], contract: dict, *, week: str) -> dict:
    """Reject calendar or actual service-template drift before any weekly solve."""
    start = date.fromisoformat(week)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    if start.weekday() != 0 or date.fromisoformat(dates[-1]).month != start.month:
        raise ValueError("Balanced week must be Monday-Sunday within one month")
    if contract.get("service_dates") != dates:
        raise ValueError("Balanced week dates differ from the declared evaluation week")
    holidays = sorted(set(contract.get("holiday_dates", [])).intersection(dates))
    if holidays:
        raise ValueError(f"Balanced week includes public holidays: {holidays}")
    validate_dated_timetable(rows, contract)
    counts = dict(Counter(day["day_type"] for day in contract["days"]))
    if counts != EXPECTED_DAY_COUNTS or any(day["trip_count"] <= 0 for day in contract["days"]):
        raise ValueError("Balanced week requires five weekday and two weekend service days")
    expected_services = ["WEEKDAY"] * 5 + ["SAT", "SUN_HOL"]
    for day, service in zip(dates, expected_services):
        if {row.get("service_id") for row in rows if row.get("service_date") == day} != {service}:
            raise ValueError(f"Materialized service IDs differ from balanced week on {day}")
    return {"status": "BALANCED_WEEK_VERIFIED", "service_dates": dates,
            "day_type_counts": counts, "holiday_dates_in_window": holidays,
            "trip_count": len(rows), "timetable_rows_sha256": contract["timetable_rows_sha256"]}
