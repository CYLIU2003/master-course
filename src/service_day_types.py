"""Shared service-day identifiers; unknown values never mean weekday."""

from __future__ import annotations

from typing import Any
import unicodedata


SERVICE_ID_BY_DAY_TYPE = {
    "weekday": "WEEKDAY",
    "saturday": "SAT",
    "sunday_or_holiday": "SUN_HOL",
    "weekend_or_holiday": "SAT_HOL",
}

_ALIASES = {
    "weekday": "weekday", "weekdays": "weekday", "平日": "weekday",
    "sat": "saturday", "saturday": "saturday", "土曜": "saturday", "土曜日": "saturday",
    "sun": "sunday_or_holiday", "sunday": "sunday_or_holiday",
    "holiday": "sunday_or_holiday", "sunhol": "sunday_or_holiday",
    "sunholiday": "sunday_or_holiday", "sundayholiday": "sunday_or_holiday",
    "sundayorholiday": "sunday_or_holiday", "日曜": "sunday_or_holiday",
    "日曜日": "sunday_or_holiday", "休日": "sunday_or_holiday", "祝日": "sunday_or_holiday",
    "sathol": "weekend_or_holiday", "satholiday": "weekend_or_holiday",
    "saturdayholiday": "weekend_or_holiday", "weekendholiday": "weekend_or_holiday",
    "weekendorholiday": "weekend_or_holiday", "土休日": "weekend_or_holiday",
}


def normalize_service_day_type(value: Any) -> str | None:
    """Resolve documented aliases, including ODPT calendar URNs."""
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    short = raw.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    token = "".join(character for character in short.lower() if character.isalnum())
    return _ALIASES.get(token)
