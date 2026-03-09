"""
src.tokyubus_gtfs.normalizers.services — Calendar / service normalizer.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List, Tuple

from ..models import CanonicalService, ServiceDayType
from .helpers import service_id_from_odpt, short_id

_log = logging.getLogger(__name__)

# Default date range (GTFS requires explicit dates)
_DEFAULT_START = date(2025, 4, 1)
_DEFAULT_END = date(2026, 3, 31)


def build_service_calendars(
    calendar_keys: set[str],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Tuple[List[CanonicalService], List[str]]:
    """
    Build ``CanonicalService`` entries from observed ODPT calendar keys.

    Parameters
    ----------
    calendar_keys
        Set of raw ODPT calendar strings encountered during normalisation
        (e.g., ``{"odpt.Calendar:Weekday", "odpt.Calendar:Saturday", ...}``).
    start_date, end_date
        Calendar validity period (GTFS ``calendar.txt``).

    Returns
    -------
    services
        List of ``CanonicalService`` models.
    warnings
        List of warning messages.
    """
    sd = start_date or _DEFAULT_START
    ed = end_date or _DEFAULT_END
    warnings: List[str] = []
    seen: Dict[str, CanonicalService] = {}

    for raw_key in calendar_keys:
        short = short_id(raw_key, "unknown")
        sid = service_id_from_odpt(short)

        if sid in seen:
            continue

        if sid == ServiceDayType.weekday.value:
            svc = CanonicalService(
                service_id=sid,
                service_name="Weekday",
                monday=True,
                tuesday=True,
                wednesday=True,
                thursday=True,
                friday=True,
                saturday=False,
                sunday=False,
                start_date=sd,
                end_date=ed,
                odpt_calendar_raw=raw_key,
            )
        elif sid == ServiceDayType.saturday.value:
            svc = CanonicalService(
                service_id=sid,
                service_name="Saturday",
                monday=False,
                tuesday=False,
                wednesday=False,
                thursday=False,
                friday=False,
                saturday=True,
                sunday=False,
                start_date=sd,
                end_date=ed,
                odpt_calendar_raw=raw_key,
            )
        elif sid == ServiceDayType.sunday_holiday.value:
            svc = CanonicalService(
                service_id=sid,
                service_name="Sunday / Holiday",
                monday=False,
                tuesday=False,
                wednesday=False,
                thursday=False,
                friday=False,
                saturday=False,
                sunday=True,
                start_date=sd,
                end_date=ed,
                odpt_calendar_raw=raw_key,
            )
        else:
            warnings.append(f"Unknown calendar key: {raw_key} → defaulted to WEEKDAY")
            svc = CanonicalService(
                service_id="WEEKDAY",
                service_name="Weekday (fallback)",
                monday=True,
                tuesday=True,
                wednesday=True,
                thursday=True,
                friday=True,
                start_date=sd,
                end_date=ed,
                odpt_calendar_raw=raw_key,
            )

        seen[sid] = svc

    services = list(seen.values())
    _log.info(
        "Built %d service calendars from %d raw keys", len(services), len(calendar_keys)
    )
    return services, warnings
