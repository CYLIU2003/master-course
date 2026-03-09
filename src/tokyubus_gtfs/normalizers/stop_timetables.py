"""
src.tokyubus_gtfs.normalizers.stop_timetables — BusstopPoleTimetable normalizer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..models import CanonicalStopTimetable
from .helpers import safe_time_hhmm, service_id_from_odpt, short_id

_log = logging.getLogger(__name__)


def normalize_busstop_pole_timetables(
    raw_data: list,
    stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[CanonicalStopTimetable], List[str]]:
    """
    Normalize ``odpt:BusstopPoleTimetable`` for reconciliation.

    Returns
    -------
    timetables
        List of ``CanonicalStopTimetable`` models.
    warnings
        List of warning messages.
    """
    stops = stop_lookup or {}
    timetables: List[CanonicalStopTimetable] = []
    warnings: List[str] = []

    def _stop_label(stop_id: Optional[str]) -> str:
        if not stop_id:
            return ""
        info = stops.get(stop_id, {})
        return str(info.get("name", "")) or short_id(stop_id, stop_id or "")

    for item in raw_data:
        if not isinstance(item, dict):
            continue

        tt_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        stop_id = str(item.get("odpt:busstopPole") or "")
        calendar_raw = str(item.get("odpt:calendar") or "")
        service_key = short_id(calendar_raw, "unknown")
        service_id = service_id_from_odpt(service_key)

        tt_objects = item.get("odpt:busstopPoleTimetableObject") or []
        entries: List[Dict[str, Any]] = []

        for obj in tt_objects:
            if not isinstance(obj, dict):
                continue
            entries.append(
                {
                    "departure": safe_time_hhmm(obj.get("odpt:departureTime")),
                    "destination": str(obj.get("odpt:destinationBusstopPole") or ""),
                    "busroutePattern": str(obj.get("odpt:busroutePattern") or ""),
                    "busroute": str(obj.get("odpt:busroute") or ""),
                    "isMidnight": bool(obj.get("odpt:isMidnight")),
                    "note": str(obj.get("odpt:note") or ""),
                }
            )

        timetables.append(
            CanonicalStopTimetable(
                timetable_id=tt_id,
                stop_id=stop_id,
                stop_name=_stop_label(stop_id),
                service_id=service_id,
                odpt_calendar_raw=calendar_raw,
                items=entries,
            )
        )

    _log.info("Normalised %d BusstopPoleTimetable records", len(timetables))
    return timetables, warnings
