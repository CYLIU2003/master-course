from __future__ import annotations

from typing import Any, Dict, List

from bff.services.odpt_routes import _stop_label
from bff.services.service_ids import canonical_service_id


def build_stop_timetables_from_normalized(
    dataset: Dict[str, Any],
) -> List[Dict[str, Any]]:
    stops = dataset.get("stops") or {}
    stop_timetables = dataset.get("stopTimetables") or {}
    items: List[Dict[str, Any]] = []

    for timetable_id, timetable in sorted(stop_timetables.items()):
        if not isinstance(timetable, dict):
            continue
        stop_id = str(timetable.get("stop_id") or "")
        items.append(
            {
                "id": timetable_id,
                "source": "odpt",
                "stopId": stop_id,
                "stopName": _stop_label(stops, stop_id),
                "calendar": timetable.get("calendar"),
                "service_id": canonical_service_id(
                    timetable.get("calendar") or timetable.get("service_id")
                ),
                "items": list(timetable.get("items") or []),
            }
        )

    return items


def summarize_stop_timetable_import(
    items: List[Dict[str, Any]], dataset: Dict[str, Any]
) -> Dict[str, Any]:
    service_counts: Dict[str, int] = {}
    total_entries = 0
    for item in items:
        service_id = canonical_service_id(item.get("service_id"))
        service_counts[service_id] = service_counts.get(service_id, 0) + 1
        total_entries += len(item.get("items") or [])

    return {
        "stopTimetableCount": len(items),
        "entryCount": total_entries,
        "serviceCounts": dict(sorted(service_counts.items())),
        "warningCount": len((dataset.get("meta") or {}).get("warnings") or []),
    }
