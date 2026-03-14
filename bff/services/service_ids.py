from __future__ import annotations

from typing import Any, Dict, Optional


_SERVICE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "WEEKDAY": {
        "name": "平日",
        "mon": 1,
        "tue": 1,
        "wed": 1,
        "thu": 1,
        "fri": 1,
        "sat": 0,
        "sun": 0,
    },
    "SAT": {
        "name": "土曜",
        "mon": 0,
        "tue": 0,
        "wed": 0,
        "thu": 0,
        "fri": 0,
        "sat": 1,
        "sun": 0,
    },
    "SUN_HOL": {
        "name": "日曜・休日",
        "mon": 0,
        "tue": 0,
        "wed": 0,
        "thu": 0,
        "fri": 0,
        "sat": 0,
        "sun": 1,
    },
    "SAT_HOL": {
        "name": "土曜・休日",
        "mon": 0,
        "tue": 0,
        "wed": 0,
        "thu": 0,
        "fri": 0,
        "sat": 1,
        "sun": 1,
    },
}

_ODPT_SERVICE_ID_ALIASES = {
    "weekday": "WEEKDAY",
    "saturday": "SAT",
    "holiday": "SUN_HOL",
    "sunday": "SUN_HOL",
    "sundayholiday": "SUN_HOL",
    "saturdayholiday": "SAT_HOL",
    "unknown": "WEEKDAY",
}


def _compact_token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def canonical_service_id(value: Any, default: str = "WEEKDAY") -> str:
    raw = str(value or "").strip()
    if not raw:
        return default

    short = raw.split(":")[-1].split("/")[-1].strip()
    compact_short = _compact_token(short)
    if compact_short in _ODPT_SERVICE_ID_ALIASES:
        return _ODPT_SERVICE_ID_ALIASES[compact_short]

    compact_raw = _compact_token(raw)
    if compact_raw in _ODPT_SERVICE_ID_ALIASES:
        return _ODPT_SERVICE_ID_ALIASES[compact_raw]

    if raw in _SERVICE_DEFINITIONS:
        return raw

    return raw


def build_service_calendar_entry(
    service_id: Any,
    *,
    calendar_raw: Optional[str] = None,
    source: str = "seed",
) -> Dict[str, Any]:
    canonical = canonical_service_id(service_id)
    definition = _SERVICE_DEFINITIONS.get(canonical)
    entry: Dict[str, Any] = {
        "service_id": canonical,
        "name": definition.get("name") if definition else canonical,
        "source": source,
    }
    if definition:
        entry.update(
            {
                "mon": definition["mon"],
                "tue": definition["tue"],
                "wed": definition["wed"],
                "thu": definition["thu"],
                "fri": definition["fri"],
                "sat": definition["sat"],
                "sun": definition["sun"],
            }
        )
    if calendar_raw:
        entry["calendar_raw"] = calendar_raw
    return entry
