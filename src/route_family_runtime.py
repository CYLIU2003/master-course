from __future__ import annotations

from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class DeadheadMetric:
    from_stop: str
    to_stop: str
    travel_time_min: int
    distance_km: float = 0.0
    source: str = "scenario_rule"
    route_family_code: Optional[str] = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return unicodedata.normalize("NFKC", raw)


def _normalize_stop_name(value: Any) -> str:
    return _normalize_text(value).replace(" ", "")


def _normalize_stop_platform_family(value: Any) -> str:
    raw = _normalize_text(value)
    if not raw:
        return ""
    return re.sub(r"(\.\d{8})\.\w*$", r"\1", raw)


def normalize_direction(value: Any, default: str = "outbound") -> str:
    text = _normalize_text(value).strip().lower()
    if text in {"outbound", "out", "up", "0", "上り", "上り便", "↗"}:
        return "outbound"
    if text in {"inbound", "in", "down", "1", "下り", "下り便", "↙"}:
        return "inbound"
    if text in {"circular", "loop", "循環", "循環線"}:
        return "circular"
    return default


def normalize_variant_type(value: Any, *, direction: str = "outbound") -> str:
    text = _normalize_text(value).strip().lower()
    if text in {"main_outbound", "main-outbound"}:
        return "main_outbound"
    if text in {"main_inbound", "main-inbound"}:
        return "main_inbound"
    if text in {"main", "本線"}:
        if direction == "outbound":
            return "main_outbound"
        if direction == "inbound":
            return "main_inbound"
        return "main"
    if text in {"short_turn", "short-turn", "short turn", "区間", "区間便"}:
        return "short_turn"
    if text in {"branch", "枝線"}:
        return "branch"
    if text in {"depot_out", "depot-out", "pull_out", "pull-out", "出庫"}:
        return "depot_out"
    if text in {"depot_in", "depot-in", "pull_in", "pull-in", "入庫"}:
        return "depot_in"
    if text in {"depot", "入出庫", "入出庫便"}:
        if direction == "outbound":
            return "depot_out"
        if direction == "inbound":
            return "depot_in"
        return "depot"
    if text == "unknown":
        return "unknown"
    if direction == "outbound":
        return "main_outbound"
    if direction == "inbound":
        return "main_inbound"
    if direction == "circular":
        return "main"
    return "main"


def route_variant_bucket(value: Any, *, direction: str = "outbound") -> str:
    variant = normalize_variant_type(value, direction=direction)
    if variant in {"main", "main_outbound", "main_inbound"}:
        return "main"
    if variant == "short_turn":
        return "short_turn"
    if variant in {"depot", "depot_in", "depot_out"}:
        return "depot"
    if variant == "branch":
        return "branch"
    return "unknown"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _stop_coord_lookup(stops: Sequence[Mapping[str, Any]]) -> Dict[str, Tuple[float, float]]:
    lookup: Dict[str, Tuple[float, float]] = {}
    for stop in stops:
        stop_id = str(stop.get("id") or stop.get("stop_id") or "").strip()
        if not stop_id:
            continue
        lat = _safe_float(stop.get("lat", stop.get("stop_lat")), 0.0)
        lon = _safe_float(stop.get("lon", stop.get("stop_lon")), 0.0)
        if lat == 0.0 and lon == 0.0:
            continue
        lookup[stop_id] = (lat, lon)
    return lookup


def _stop_name_lookup(stops: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for stop in stops:
        stop_id = str(stop.get("id") or stop.get("stop_id") or "").strip()
        if not stop_id:
            continue
        name = _normalize_stop_name(
            stop.get("name") or stop.get("stop_name") or stop.get("label") or ""
        )
        if name and name not in lookup:
            lookup[name] = stop_id
    return lookup


def _resolve_terminal_stop_id(
    stop_id: Any,
    stop_name: Any,
    *,
    stop_coords: Mapping[str, Tuple[float, float]],
    stop_ids_by_name: Mapping[str, str],
) -> str:
    candidate = str(stop_id or "").strip()
    if candidate and candidate in stop_coords:
        return candidate
    name_key = _normalize_stop_name(stop_name)
    resolved = str(stop_ids_by_name.get(name_key) or "").strip()
    if resolved and resolved in stop_coords:
        return resolved
    return ""


def _route_family_code(trip_like: Mapping[str, Any], route_like: Mapping[str, Any]) -> str:
    return str(
        trip_like.get("routeFamilyCode")
        or trip_like.get("route_family_code")
        or trip_like.get("routeSeriesCode")
        or trip_like.get("route_series_code")
        or route_like.get("routeFamilyCode")
        or route_like.get("route_family_code")
        or route_like.get("routeSeriesCode")
        or trip_like.get("route_id")
        or route_like.get("id")
        or ""
    ).strip()


def _coerce_existing_metric(
    key: Tuple[str, str],
    item: Any,
) -> Optional[DeadheadMetric]:
    from_stop, to_stop = key
    if isinstance(item, DeadheadMetric):
        return item
    if isinstance(item, Mapping):
        travel_time_min = max(
            1,
            int(float(item.get("travel_time_min") or item.get("time_min") or 1)),
        )
        distance_km = _safe_float(item.get("distance_km", item.get("distanceKm")), 0.0)
        source = str(item.get("source") or "scenario_rule")
        route_family_code = str(item.get("routeFamilyCode") or item.get("route_family_code") or "").strip() or None
        return DeadheadMetric(
            from_stop=from_stop,
            to_stop=to_stop,
            travel_time_min=travel_time_min,
            distance_km=distance_km,
            source=source,
            route_family_code=route_family_code,
        )
    try:
        travel_time_min = max(1, int(float(item)))
    except (TypeError, ValueError):
        return None
    return DeadheadMetric(
        from_stop=from_stop,
        to_stop=to_stop,
        travel_time_min=travel_time_min,
        source="scenario_rule",
    )


def merge_deadhead_metrics(
    *,
    existing_rules: Iterable[Mapping[str, Any]] | Mapping[Tuple[str, str], Any] | None,
    trip_rows: Sequence[Mapping[str, Any]],
    routes: Sequence[Mapping[str, Any]],
    stops: Sequence[Mapping[str, Any]],
    max_deadhead_km: float = 20.0,
    detour_factor: float = 1.35,
    assumed_speed_kmh: float = 18.0,
    min_deadhead_min: int = 3,
) -> Dict[Tuple[str, str], DeadheadMetric]:
    metrics: Dict[Tuple[str, str], DeadheadMetric] = {}
    if isinstance(existing_rules, Mapping):
        for key, item in existing_rules.items():
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            from_stop = str(key[0] or "").strip()
            to_stop = str(key[1] or "").strip()
            if not from_stop or not to_stop:
                continue
            metric = _coerce_existing_metric((from_stop, to_stop), item)
            if metric is not None:
                metrics[(from_stop, to_stop)] = metric
    else:
        for item in existing_rules or []:
            if not isinstance(item, Mapping):
                continue
            from_stop = str(item.get("from_stop") or item.get("origin") or "").strip()
            to_stop = str(item.get("to_stop") or item.get("destination") or "").strip()
            if not from_stop or not to_stop:
                continue
            metric = _coerce_existing_metric((from_stop, to_stop), item)
            if metric is not None:
                metrics[(from_stop, to_stop)] = metric

    stop_coords = _stop_coord_lookup(stops)
    stop_ids_by_name = _stop_name_lookup(stops)
    stop_ids_by_platform_family: Dict[str, set[str]] = {}
    for stop in stops:
        if not isinstance(stop, Mapping):
            continue
        stop_id = str(stop.get("id") or stop.get("stop_id") or stop.get("stopId") or "").strip()
        family_id = _normalize_stop_platform_family(stop_id)
        if not stop_id or not family_id:
            continue
        stop_ids_by_platform_family.setdefault(family_id, set()).add(stop_id)
    for family_stop_ids in stop_ids_by_platform_family.values():
        if len(family_stop_ids) < 2:
            continue
        for from_stop in sorted(family_stop_ids):
            for to_stop in sorted(family_stop_ids):
                if from_stop == to_stop:
                    continue
                key = (from_stop, to_stop)
                if key in metrics:
                    continue
                metrics[key] = DeadheadMetric(
                    from_stop=from_stop,
                    to_stop=to_stop,
                    travel_time_min=0,
                    distance_km=0.0,
                    source="stop_platform_alias",
                    route_family_code=None,
                )
    if not stop_coords:
        return metrics

    route_lookup = {
        str(route.get("id") or route.get("route_id") or "").strip(): route
        for route in routes
        if str(route.get("id") or route.get("route_id") or "").strip()
    }

    origins_by_family: Dict[str, set[str]] = {}
    destinations_by_family: Dict[str, set[str]] = {}
    for row in trip_rows:
        route_id = str(row.get("route_id") or "").strip()
        route_like = route_lookup.get(route_id) or {}
        family_code = _route_family_code(row, route_like)
        if not family_code:
            continue
        origin_stop_id = _resolve_terminal_stop_id(
            row.get("origin_stop_id"),
            row.get("origin"),
            stop_coords=stop_coords,
            stop_ids_by_name=stop_ids_by_name,
        )
        destination_stop_id = _resolve_terminal_stop_id(
            row.get("destination_stop_id"),
            row.get("destination"),
            stop_coords=stop_coords,
            stop_ids_by_name=stop_ids_by_name,
        )
        if origin_stop_id:
            origins_by_family.setdefault(family_code, set()).add(origin_stop_id)
        if destination_stop_id:
            destinations_by_family.setdefault(family_code, set()).add(destination_stop_id)

    if assumed_speed_kmh <= 0:
        assumed_speed_kmh = 18.0

    for family_code in sorted(set(origins_by_family) | set(destinations_by_family)):
        origin_ids = sorted(origins_by_family.get(family_code) or ())
        destination_ids = sorted(destinations_by_family.get(family_code) or ())
        if not origin_ids or not destination_ids:
            continue
        for from_stop in destination_ids:
            from_coords = stop_coords.get(from_stop)
            if not from_coords:
                continue
            for to_stop in origin_ids:
                if from_stop == to_stop:
                    continue
                key = (from_stop, to_stop)
                if key in metrics:
                    continue
                to_coords = stop_coords.get(to_stop)
                if not to_coords:
                    continue
                straight_km = _haversine_km(
                    from_coords[0],
                    from_coords[1],
                    to_coords[0],
                    to_coords[1],
                )
                distance_km = round(straight_km * max(detour_factor, 1.0), 4)
                if distance_km <= 0.0 or distance_km > max_deadhead_km:
                    continue
                travel_time_min = max(
                    int(min_deadhead_min),
                    int(math.ceil((distance_km / assumed_speed_kmh) * 60.0)),
                )
                metrics[key] = DeadheadMetric(
                    from_stop=from_stop,
                    to_stop=to_stop,
                    travel_time_min=travel_time_min,
                    distance_km=distance_km,
                    source="route_family_terminal_inference",
                    route_family_code=family_code,
                )

    all_origin_ids = sorted(
        {
            stop_id
            for family_stop_ids in origins_by_family.values()
            for stop_id in family_stop_ids
        }
    )
    all_destination_ids = sorted(
        {
            stop_id
            for family_stop_ids in destinations_by_family.values()
            for stop_id in family_stop_ids
        }
    )

    for from_stop in all_destination_ids:
        from_coords = stop_coords.get(from_stop)
        if not from_coords:
            continue
        for to_stop in all_origin_ids:
            if from_stop == to_stop:
                continue
            key = (from_stop, to_stop)
            if key in metrics:
                continue
            to_coords = stop_coords.get(to_stop)
            if not to_coords:
                continue
            straight_km = _haversine_km(
                from_coords[0],
                from_coords[1],
                to_coords[0],
                to_coords[1],
            )
            distance_km = round(straight_km * max(detour_factor, 1.0), 4)
            if distance_km <= 0.0 or distance_km > max_deadhead_km:
                continue
            travel_time_min = max(
                int(min_deadhead_min),
                int(math.ceil((distance_km / assumed_speed_kmh) * 60.0)),
            )
            metrics[key] = DeadheadMetric(
                from_stop=from_stop,
                to_stop=to_stop,
                travel_time_min=travel_time_min,
                distance_km=distance_km,
                source="cross_family_terminal_inference",
                route_family_code=None,
            )
    return metrics
