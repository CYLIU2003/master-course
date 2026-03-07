from __future__ import annotations

from typing import Any, Dict, List


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_stops_from_normalized(dataset: Dict[str, Any]) -> List[Dict[str, Any]]:
    stops = dataset.get("stops") or {}
    items: List[Dict[str, Any]] = []

    for stop_id, stop in sorted(stops.items()):
        if not isinstance(stop, dict):
            continue
        items.append(
            {
                "id": str(stop_id),
                "code": str(stop.get("poleNumber") or stop_id.split(":")[-1]),
                "name": str(stop.get("name") or stop_id.split(":")[-1]),
                "lat": _as_float(stop.get("lat")),
                "lon": _as_float(stop.get("lon")),
                "poleNumber": stop.get("poleNumber"),
                "source": "odpt",
            }
        )

    return items


def summarize_stop_import(
    stops: List[Dict[str, Any]], dataset: Dict[str, Any]
) -> Dict[str, Any]:
    geo_count = 0
    named_count = 0
    pole_number_count = 0

    for stop in stops:
        if stop.get("name"):
            named_count += 1
        if stop.get("poleNumber"):
            pole_number_count += 1
        if stop.get("lat") is not None and stop.get("lon") is not None:
            geo_count += 1

    return {
        "stopCount": len(stops),
        "namedCount": named_count,
        "geoCount": geo_count,
        "poleNumberCount": pole_number_count,
        "warningCount": len((dataset.get("meta") or {}).get("warnings") or []),
    }
