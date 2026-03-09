"""
src.tokyubus_gtfs.normalizers.routes — BusroutePattern → CanonicalRoute normalizer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..models import (
    CanonicalDirection,
    CanonicalRoute,
    CanonicalRouteStop,
    RouteVariantType,
)
from .helpers import (
    data_hash,
    extract_route_family_code,
    route_color_from_seed,
    short_id,
    stable_id,
)

_log = logging.getLogger(__name__)


def normalize_busroute_patterns(
    raw_data: list,
    stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[
    List[CanonicalRoute], List[CanonicalRouteStop], Dict[str, Dict[str, Any]], List[str]
]:
    """
    Normalize ``odpt:BusroutePattern`` into canonical routes and route stops.

    Returns
    -------
    routes
        List of ``CanonicalRoute`` models.
    route_stops
        List of ``CanonicalRouteStop`` models (stop sequences per route).
    pattern_lookup
        Dict mapping ODPT pattern_id → route metadata for timetable linking.
    warnings
        List of warning messages.
    """
    stops = stop_lookup or {}
    routes: List[CanonicalRoute] = []
    route_stops: List[CanonicalRouteStop] = []
    pattern_lookup: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    def _stop_label(stop_id: Optional[str]) -> str:
        if not stop_id:
            return ""
        info = stops.get(stop_id, {})
        return str(info.get("name", "")) or short_id(stop_id, stop_id or "")

    for item in raw_data:
        if not isinstance(item, dict):
            continue

        pattern_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        if not pattern_id:
            continue

        # Extract stop sequence
        busstop_order = item.get("odpt:busstopPoleOrder") or []
        stop_sequence: List[str] = []
        cumulative_distances: List[Optional[float]] = []
        cumulative = 0.0

        for bs in busstop_order:
            if isinstance(bs, dict):
                pole = bs.get("odpt:busstopPole")
                if pole:
                    stop_sequence.append(str(pole))
                    dist = bs.get("odpt:distance")
                    if dist is not None:
                        try:
                            cumulative += float(dist)
                        except (TypeError, ValueError):
                            pass
                    cumulative_distances.append(cumulative)

        if len(stop_sequence) < 2:
            warnings.append(f"Pattern {pattern_id} has < 2 stops, skipped")
            continue

        route_id = stable_id("route", pattern_id)
        title = str(item.get("dc:title") or "")
        origin_name = _stop_label(stop_sequence[0])
        dest_name = _stop_label(stop_sequence[-1])
        route_name = (
            f"{title} ({origin_name} → {dest_name})"
            if title
            else f"{origin_name} → {dest_name}"
        )

        total_distance_km = cumulative / 1000.0 if cumulative > 0 else 0.0
        family_code = extract_route_family_code(title) if title else None

        route = CanonicalRoute(
            route_id=route_id,
            route_code=title or short_id(pattern_id, route_id),
            route_name=route_name,
            operator_id="odpt.Operator:TokyuBus",
            route_color=route_color_from_seed(pattern_id),
            origin_stop_id=stop_sequence[0],
            destination_stop_id=stop_sequence[-1],
            origin_name=origin_name,
            destination_name=dest_name,
            distance_km=round(total_distance_km, 3),
            stop_count=len(stop_sequence),
            odpt_pattern_id=pattern_id,
            odpt_busroute_id=str(item.get("odpt:busroute") or ""),
            odpt_raw_title=title,
            route_family_code=family_code,
        )
        routes.append(route)

        # Build pattern lookup for timetable normalizer
        pattern_lookup[pattern_id] = {
            "route_id": route_id,
            "total_distance_km": round(total_distance_km, 3),
            "stop_count": len(stop_sequence),
            "origin_name": origin_name,
            "destination_name": dest_name,
        }

        # Build route stop entries
        for idx, sid in enumerate(stop_sequence):
            dist_m = (
                cumulative_distances[idx] if idx < len(cumulative_distances) else None
            )
            route_stops.append(
                CanonicalRouteStop(
                    route_id=route_id,
                    stop_id=sid,
                    stop_sequence=idx,
                    stop_name=_stop_label(sid),
                    odpt_pattern_id=pattern_id,
                    distance_from_start_m=dist_m,
                )
            )

    _log.info(
        "Normalised %d BusroutePattern records → %d routes, %d route stops",
        len(raw_data),
        len(routes),
        len(route_stops),
    )
    return routes, route_stops, pattern_lookup, warnings
