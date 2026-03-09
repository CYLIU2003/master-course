"""
src.tokyubus_gtfs.normalizers.routes — BusroutePattern normalizer.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..constants import ROUTE_FAMILY_MAP_PATH, TOKYU_OPERATOR_ID
from ..models import CanonicalRoute, CanonicalRoutePattern, CanonicalRouteStop, RouteVariantType
from .helpers import extract_route_family_code, nfkc_normalize, route_color_from_seed, short_id, stable_id

_log = logging.getLogger(__name__)

_SPECIAL_FAMILY_PREFIXES = ("空港", "高速", "直行", "出入庫", "ハチ公")
_DEPOT_KEYWORDS = ("営業所", "車庫", "操車所")


def _load_manual_route_family_map(path: Path = ROUTE_FAMILY_MAP_PATH) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {
        str(row.get("pattern_route_id") or "").strip(): row
        for row in rows
        if str(row.get("pattern_route_id") or "").strip()
    }


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _slugify(value: str) -> str:
    text = nfkc_normalize(value).strip().lower()
    text = re.sub(r"[()（）\[\]{}]", " ", text)
    text = re.sub(r"[^0-9a-zA-Z一-龯ぁ-んァ-ン]+", "_", text)
    return text.strip("_")


def _infer_family_id(route_code: str, origin_name: str, destination_name: str) -> str:
    family_code = extract_route_family_code(route_code) or route_code or f"{origin_name}_{destination_name}"
    family_key = nfkc_normalize(family_code)
    if any(family_key.startswith(prefix) for prefix in _SPECIAL_FAMILY_PREFIXES):
        family_key = f"{family_key}_{origin_name}_{destination_name}"
    slug = _slugify(family_key)
    return f"tokyu:{slug or stable_id('family', family_key)}_family"


def _infer_pattern_role(origin_name: str, destination_name: str) -> RouteVariantType:
    origin_is_depot = any(keyword in origin_name for keyword in _DEPOT_KEYWORDS)
    destination_is_depot = any(keyword in destination_name for keyword in _DEPOT_KEYWORDS)
    if origin_is_depot and not destination_is_depot:
        return RouteVariantType.depot_in
    if destination_is_depot and not origin_is_depot:
        return RouteVariantType.depot_out
    return RouteVariantType.main


def _coerce_variant(value: Any, default: RouteVariantType) -> RouteVariantType:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return RouteVariantType(text)
    except ValueError:
        return default


def normalize_busroute_patterns(
    raw_data: list,
    stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[
    List[CanonicalRoute],
    List[CanonicalRoutePattern],
    List[CanonicalRouteStop],
    Dict[str, Dict[str, Any]],
    List[str],
]:
    """
    Normalize ``odpt:BusroutePattern`` into public route families and raw patterns.
    """
    stops = stop_lookup or {}
    manual_map = _load_manual_route_family_map()
    routes: List[CanonicalRoute] = []
    route_patterns: List[CanonicalRoutePattern] = []
    route_stops: List[CanonicalRouteStop] = []
    pattern_lookup: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    def _stop_label(stop_id: Optional[str]) -> str:
        if not stop_id:
            return ""
        info = stops.get(stop_id, {})
        return str(info.get("name", "")) or short_id(stop_id, stop_id or "")

    pattern_records: List[Dict[str, Any]] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue

        odpt_pattern_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        if not odpt_pattern_id:
            continue

        pattern_id = stable_id("route", odpt_pattern_id)
        manual = manual_map.get(pattern_id, {})

        busstop_order = item.get("odpt:busstopPoleOrder") or []
        stop_sequence: List[str] = []
        cumulative_distances: List[Optional[float]] = []
        cumulative = 0.0
        for bs in busstop_order:
            if not isinstance(bs, dict):
                continue
            pole = bs.get("odpt:busstopPole")
            if not pole:
                continue
            stop_sequence.append(str(pole))
            dist = bs.get("odpt:distance")
            if dist is not None:
                try:
                    cumulative += float(dist)
                except (TypeError, ValueError):
                    pass
            cumulative_distances.append(cumulative)

        if len(stop_sequence) < 2:
            warnings.append(f"Pattern {odpt_pattern_id} has < 2 stops, skipped")
            continue

        title = str(item.get("dc:title") or "")
        origin_name = _stop_label(stop_sequence[0])
        destination_name = _stop_label(stop_sequence[-1])
        route_name = (
            str(manual.get("route_long_name") or "")
            or (f"{title} ({origin_name} -> {destination_name})" if title else f"{origin_name} -> {destination_name}")
        )
        route_short_name = str(manual.get("route_short_name") or title or short_id(odpt_pattern_id, pattern_id))
        family_id = str(manual.get("gtfs_route_family_id") or _infer_family_id(route_short_name, origin_name, destination_name))
        family_short_name = str(manual.get("gtfs_route_short_name") or route_short_name)
        family_long_name = str(manual.get("gtfs_route_long_name") or family_short_name)
        distance_km = round(cumulative / 1000.0, 3) if cumulative > 0 else 0.0
        inferred_role = _infer_pattern_role(origin_name, destination_name)
        pattern_role = _coerce_variant(manual.get("pattern_role"), inferred_role)
        include_in_public_gtfs = _as_bool(manual.get("include_in_gtfs"), True)
        direction_bucket_raw = manual.get("direction_bucket")
        direction_bucket = None
        if direction_bucket_raw not in (None, ""):
            try:
                direction_bucket = int(direction_bucket_raw)
            except (TypeError, ValueError):
                direction_bucket = None

        record = {
            "pattern_id": pattern_id,
            "route_id": family_id,
            "route_short_name": family_short_name,
            "route_long_name": family_long_name,
            "route_code": family_short_name,
            "pattern_route_name": route_name,
            "origin_stop_id": stop_sequence[0],
            "destination_stop_id": stop_sequence[-1],
            "origin_name": origin_name,
            "destination_name": destination_name,
            "distance_km": distance_km,
            "stop_count": len(stop_sequence),
            "stop_sequence": stop_sequence,
            "cumulative_distances": cumulative_distances,
            "shape_id": f"shape_{pattern_id}",
            "pattern_role": pattern_role,
            "direction_bucket": direction_bucket,
            "include_in_public_gtfs": include_in_public_gtfs,
            "is_passenger_service": include_in_public_gtfs or pattern_role not in {RouteVariantType.depot_in, RouteVariantType.depot_out},
            "odpt_pattern_id": odpt_pattern_id,
            "odpt_busroute_id": str(item.get("odpt:busroute") or ""),
            "odpt_raw_title": title,
        }
        pattern_records.append(record)

    records_by_family: Dict[str, List[Dict[str, Any]]] = {}
    for record in pattern_records:
        records_by_family.setdefault(record["route_id"], []).append(record)

    for family_id, records in records_by_family.items():
        primary = max(
            records,
            key=lambda rec: (
                rec["include_in_public_gtfs"],
                rec["pattern_role"] == RouteVariantType.main,
                rec["stop_count"],
                rec["distance_km"],
            ),
        )
        trunk_origin = primary["origin_name"]
        trunk_destination = primary["destination_name"]

        for record in records:
            if record["direction_bucket"] is None:
                if record["origin_name"] == trunk_origin or record["destination_name"] == trunk_destination:
                    record["direction_bucket"] = 0
                elif record["origin_name"] == trunk_destination or record["destination_name"] == trunk_origin:
                    record["direction_bucket"] = 1
                else:
                    record["direction_bucket"] = 0

            route_patterns.append(
                CanonicalRoutePattern(
                    pattern_id=record["pattern_id"],
                    route_id=family_id,
                    pattern_role=record["pattern_role"],
                    direction_bucket=record["direction_bucket"],
                    shape_id=record["shape_id"],
                    first_stop_id=record["origin_stop_id"],
                    last_stop_id=record["destination_stop_id"],
                    first_stop_name=record["origin_name"],
                    last_stop_name=record["destination_name"],
                    stop_count=record["stop_count"],
                    distance_km=record["distance_km"],
                    is_passenger_service=record["is_passenger_service"],
                    include_in_public_gtfs=record["include_in_public_gtfs"],
                    route_short_name_hint=record["route_short_name"],
                    route_long_name_hint=record["pattern_route_name"],
                    odpt_pattern_id=record["odpt_pattern_id"],
                    odpt_busroute_id=record["odpt_busroute_id"],
                    odpt_raw_title=record["odpt_raw_title"],
                    classification_confidence=1.0 if manual_map.get(record["pattern_id"]) else 0.4,
                    classification_reasons=["manual_map"] if manual_map.get(record["pattern_id"]) else ["heuristic_family"],
                )
            )

            pattern_lookup[record["odpt_pattern_id"]] = {
                "route_id": family_id,
                "pattern_id": record["pattern_id"],
                "shape_id": record["shape_id"],
                "direction_bucket": record["direction_bucket"],
                "pattern_role": record["pattern_role"].value,
                "is_passenger_service": record["is_passenger_service"],
                "include_in_public_gtfs": record["include_in_public_gtfs"],
                "total_distance_km": record["distance_km"],
                "stop_count": record["stop_count"],
                "origin_name": record["origin_name"],
                "destination_name": record["destination_name"],
            }

            for idx, stop_id in enumerate(record["stop_sequence"]):
                route_stops.append(
                    CanonicalRouteStop(
                        pattern_id=record["pattern_id"],
                        route_id=family_id,
                        stop_id=stop_id,
                        stop_sequence=idx,
                        stop_name=_stop_label(stop_id),
                        odpt_pattern_id=record["odpt_pattern_id"],
                        distance_from_start_m=record["cumulative_distances"][idx] if idx < len(record["cumulative_distances"]) else None,
                    )
                )

        routes.append(
            CanonicalRoute(
                route_id=family_id,
                route_code=primary["route_code"],
                route_name=primary["route_long_name"],
                operator_id=TOKYU_OPERATOR_ID,
                route_color=route_color_from_seed(family_id),
                origin_stop_id=primary["origin_stop_id"],
                destination_stop_id=primary["destination_stop_id"],
                origin_name=primary["origin_name"],
                destination_name=primary["destination_name"],
                distance_km=max((rec["distance_km"] for rec in records), default=0.0),
                stop_count=max((rec["stop_count"] for rec in records), default=0),
                route_family_code=extract_route_family_code(primary["route_code"]) or primary["route_code"],
                route_family_label=primary["route_long_name"],
                primary_pattern_id=primary["pattern_id"],
                classification_confidence=1.0 if any(manual_map.get(rec["pattern_id"]) for rec in records) else 0.4,
                classification_reasons=["manual_map"] if any(manual_map.get(rec["pattern_id"]) for rec in records) else ["heuristic_family"],
            )
        )

    routes.sort(key=lambda route: (route.route_code, route.route_id))
    route_patterns.sort(key=lambda pattern: (pattern.route_id, pattern.direction_bucket or 0, pattern.pattern_id))
    route_stops.sort(key=lambda stop: (stop.pattern_id, stop.stop_sequence))
    _log.info(
        "Normalised %d BusroutePattern records -> %d public routes, %d route patterns, %d route stops",
        len(raw_data),
        len(routes),
        len(route_patterns),
        len(route_stops),
    )
    return routes, route_patterns, route_stops, pattern_lookup, warnings
