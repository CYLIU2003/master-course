from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


log = logging.getLogger("build_tokyu_shards")

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
CANONICAL_ROOT = DATA_ROOT / "tokyubus" / "canonical"
SEED_ROOT = DATA_ROOT / "seed" / "tokyu"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "built" / "tokyu"
SCHEMA_ROOT = REPO_ROOT / "schema" / "tokyu_shards"
SHARD_VERSION = "1.0.0"
OPERATOR_ID = "tokyu"
OPERATOR_NAME = "Tokyu"
DAY_TYPES = ("weekday", "saturday", "holiday")
SERVICE_ID_TO_DAY_TYPE = {
    "WEEKDAY": "weekday",
    "SAT": "saturday",
    "SATURDAY": "saturday",
    "SAT_HOL": "saturday",
    "SAT_HOLIDAY": "saturday",
    "SUN_HOL": "holiday",
    "SUN_HOLIDAY": "holiday",
    "HOLIDAY": "holiday",
}
PATTERN_ROLE_TO_SERVICE_VARIANT = {
    "main": "main",
    "short_turn": "short_turn",
    "depot_in": "depot_in",
    "depot_out": "depot_out",
}
SPECIAL_ROUTE_ALIASES = {
    "サンマバス": "さんまバス",
    "さんま": "さんまバス",
    "目黒区地域交通バスさんまバス": "さんまバス",
    "トランセ": "トランセ",
}
INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def normalize_route_code(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    if "さんま" in text:
        return "さんまバス"
    if "トランセ" in text:
        return "トランセ"
    return SPECIAL_ROUTE_ALIASES.get(text, text)


def _safe_segment(value: str) -> str:
    normalized = INVALID_PATH_CHARS.sub("_", _normalize_text(value))
    normalized = normalized.replace(" ", "_")
    return normalized or "_"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json_schema(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON schema is not an object: {path}")
    return payload


def _validate_with_schema(schema_name: str, payload: dict[str, Any], schema_root: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required to validate Tokyu shard outputs.") from exc
    schema = _load_json_schema(schema_root / schema_name)
    jsonschema.Draft202012Validator(schema).validate(payload)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _latest_snapshot_id(canonical_root: Path) -> str:
    snapshots = sorted(
        path.name
        for path in canonical_root.iterdir()
        if path.is_dir()
    )
    if not snapshots:
        raise RuntimeError(f"No canonical snapshots found under {canonical_root}")
    return snapshots[-1]


def _dataset_definition(seed_root: Path, dataset_id: str) -> dict[str, Any]:
    path = seed_root / "datasets" / f"{dataset_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Dataset definition not found: {path}")
    payload = _read_json(path)
    payload.setdefault("dataset_id", dataset_id)
    return payload


def _seed_version(seed_root: Path) -> dict[str, Any]:
    path = seed_root / "version.json"
    return _read_json(path) if path.exists() else {}


def _load_seed_depots(seed_root: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(seed_root / "depots.json")
    return {
        str(item.get("id") or item.get("depotId") or "").strip(): dict(item)
        for item in payload.get("depots") or []
        if isinstance(item, dict) and str(item.get("id") or item.get("depotId") or "").strip()
    }


def _load_route_to_depot_rows(seed_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with (seed_root / "route_to_depot.csv").open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            route_code = normalize_route_code(row.get("route_code"))
            depot_id = _normalize_text(row.get("depot_id"))
            if not route_code or not depot_id:
                continue
            rows.append(
                {
                    "route_code": route_code,
                    "depot_id": depot_id,
                    "depot_name": _normalize_text(row.get("depot_name")),
                    "region": _normalize_text(row.get("region")),
                    "notes": _normalize_text(row.get("notes")),
                }
            )
    return rows


def _selected_route_scope(
    definition: dict[str, Any],
    route_rows: Iterable[dict[str, str]],
    *,
    depot_filter: str | None,
) -> tuple[list[str], dict[str, list[str]]]:
    included_depots = [
        _normalize_text(item)
        for item in definition.get("included_depots") or []
        if _normalize_text(item)
    ]
    if depot_filter:
        normalized_depot = _normalize_text(depot_filter)
        if normalized_depot not in included_depots:
            raise RuntimeError(
                f"Depot '{normalized_depot}' is not part of dataset '{definition.get('dataset_id')}'."
            )
        included_depots = [normalized_depot]

    included_routes_raw = definition.get("included_routes")
    included_routes = None
    if included_routes_raw != "ALL":
        included_routes = {
            normalize_route_code(item)
            for item in included_routes_raw or []
            if normalize_route_code(item)
        }

    route_to_depots: dict[str, list[str]] = defaultdict(list)
    for row in route_rows:
        route_code = normalize_route_code(row.get("route_code"))
        depot_id = _normalize_text(row.get("depot_id"))
        if not route_code or not depot_id:
            continue
        if included_depots and depot_id not in included_depots:
            continue
        if included_routes is not None and route_code not in included_routes:
            continue
        if depot_id not in route_to_depots[route_code]:
            route_to_depots[route_code].append(depot_id)

    return included_depots, dict(route_to_depots)


def _service_day_type(service_id: Any) -> str:
    normalized = _normalize_text(service_id).upper() or "WEEKDAY"
    return SERVICE_ID_TO_DAY_TYPE.get(normalized, "weekday")


def _normalize_direction(value: Any, direction_id: Any = None) -> str:
    text = _normalize_text(value).lower()
    if text in {"outbound", "out", "up"}:
        return "outbound"
    if text in {"inbound", "in", "down"}:
        return "inbound"
    if direction_id in {0, "0"}:
        return "outbound"
    if direction_id in {1, "1"}:
        return "inbound"
    return "outbound"


def _normalize_service_variant(pattern_role: Any) -> str:
    normalized = _normalize_text(pattern_role).lower()
    return PATTERN_ROLE_TO_SERVICE_VARIANT.get(normalized, "other")


def _normalize_time_string(value: Any) -> str:
    text = _normalize_text(value)
    if len(text) == 5:
        return f"{text}:00"
    return text


def _route_long_name(candidate_names: Iterable[str], route_code: str) -> str:
    for value in candidate_names:
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return route_code


def _trip_item_stop_time_count(
    stop_times_by_trip_id: dict[str, list[dict[str, Any]]],
    trip_id: str,
) -> int:
    return len(stop_times_by_trip_id.get(trip_id) or [])


def _relative_path(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _build_shard_state(
    *,
    dataset_id: str,
    snapshot_id: str,
    seed_version: dict[str, Any],
    route_to_depots: dict[str, list[str]],
    depots_master: dict[str, dict[str, Any]],
    canonical_root: Path,
    warnings: list[str],
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
    dict[str, Any],
    dict[str, int],
]:
    routes_rows = _read_jsonl(canonical_root / "routes.jsonl")
    route_pattern_rows = _read_jsonl(canonical_root / "route_patterns.jsonl")
    service_rows = _read_jsonl(canonical_root / "services.jsonl")
    trip_rows = _read_jsonl(canonical_root / "trips.jsonl")
    stop_time_rows = _read_jsonl(canonical_root / "stop_times.jsonl")

    route_info_by_route_id: dict[str, dict[str, Any]] = {}
    route_profile_by_code: dict[str, dict[str, Any]] = {}
    for row in routes_rows:
        route_id = _normalize_text(row.get("route_id"))
        route_code = normalize_route_code(
            row.get("route_family_code")
            or row.get("route_code")
            or row.get("route_name")
            or row.get("route_id")
        )
        if not route_id or not route_code:
            continue
        route_info = {
            "route_id": route_id,
            "route_code": route_code,
            "route_name": _normalize_text(row.get("route_name")),
            "route_short_name": _normalize_text(
                row.get("route_family_code") or row.get("route_code") or route_code
            ),
            "route_long_name": _normalize_text(row.get("route_name")),
            "origin_stop_id": _normalize_text(row.get("origin_stop_id")),
            "destination_stop_id": _normalize_text(row.get("destination_stop_id")),
            "origin_name": _normalize_text(row.get("origin_name")),
            "destination_name": _normalize_text(row.get("destination_name")),
            "distance_km": float(row.get("distance_km") or 0.0),
        }
        route_info_by_route_id[route_id] = route_info
        profile = route_profile_by_code.setdefault(
            route_code,
            {
                "route_short_name": route_code,
                "name_candidates": [],
                "directions": set(),
                "service_variants": set(),
            },
        )
        profile["name_candidates"].extend(
            [
                route_info["route_long_name"],
                route_info["route_name"],
            ]
        )

    pattern_info_by_id: dict[str, dict[str, Any]] = {}
    for row in route_pattern_rows:
        pattern_id = _normalize_text(row.get("pattern_id"))
        route_id = _normalize_text(row.get("route_id"))
        route_info = route_info_by_route_id.get(route_id, {})
        route_code = normalize_route_code(
            route_info.get("route_code")
            or row.get("route_short_name_hint")
            or row.get("odpt_raw_title")
            or route_id
        )
        if not pattern_id or not route_code:
            continue
        info = {
            "pattern_id": pattern_id,
            "route_id": route_id,
            "route_code": route_code,
            "pattern_role": _normalize_service_variant(row.get("pattern_role")),
            "direction": _normalize_direction(
                row.get("direction"),
                row.get("direction_bucket"),
            ),
            "origin_stop_id": _normalize_text(row.get("first_stop_id")),
            "destination_stop_id": _normalize_text(row.get("last_stop_id")),
            "origin_name": _normalize_text(row.get("first_stop_name")),
            "destination_name": _normalize_text(row.get("last_stop_name")),
            "route_short_name_hint": _normalize_text(row.get("route_short_name_hint")),
            "route_long_name_hint": _normalize_text(row.get("route_long_name_hint")),
            "distance_km": float(row.get("distance_km") or 0.0),
        }
        pattern_info_by_id[pattern_id] = info
        profile = route_profile_by_code.setdefault(
            route_code,
            {
                "route_short_name": route_code,
                "name_candidates": [],
                "directions": set(),
                "service_variants": set(),
            },
        )
        profile["route_short_name"] = info["route_short_name_hint"] or route_code
        profile["name_candidates"].append(info["route_long_name_hint"])
        profile["directions"].add(info["direction"])
        profile["service_variants"].add(info["pattern_role"])

    services_payload = {
        _normalize_text(row.get("service_id")).upper(): dict(row)
        for row in service_rows
        if _normalize_text(row.get("service_id"))
    }

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    trip_headers_by_id: dict[str, dict[str, Any]] = {}
    trip_memberships: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    route_day_types: dict[str, set[str]] = defaultdict(set)
    route_directions: dict[str, set[str]] = defaultdict(set)
    route_variants: dict[str, set[str]] = defaultdict(set)
    route_depot_ids: dict[str, set[str]] = defaultdict(set)
    source_counts = {
        "routes": len(routes_rows),
        "route_patterns": len(route_pattern_rows),
        "services": len(service_rows),
        "trips": len(trip_rows),
        "stop_times": len(stop_time_rows),
    }

    for row in trip_rows:
        trip_id = _normalize_text(row.get("trip_id"))
        route_id = _normalize_text(row.get("route_id"))
        pattern_id = _normalize_text(row.get("pattern_id"))
        if not trip_id:
            warnings.append("Trip row missing trip_id; skipped.")
            continue
        pattern_info = pattern_info_by_id.get(pattern_id, {})
        route_info = route_info_by_route_id.get(route_id, {})
        route_code = normalize_route_code(
            route_info.get("route_code")
            or pattern_info.get("route_code")
            or row.get("route_code")
            or row.get("route_short_name")
            or route_id
        )
        if not route_code:
            warnings.append(f"Trip '{trip_id}' missing route_code; skipped.")
            continue
        candidate_depots = list(route_to_depots.get(route_code) or [])
        if not candidate_depots:
            continue
        day_type = _service_day_type(row.get("service_id"))
        direction = _normalize_direction(row.get("direction"), row.get("direction_id"))
        service_variant = pattern_info.get("pattern_role") or "other"
        origin_stop_id = (
            _normalize_text(row.get("origin_stop_id"))
            or _normalize_text(pattern_info.get("origin_stop_id"))
            or _normalize_text(route_info.get("origin_stop_id"))
        )
        destination_stop_id = (
            _normalize_text(row.get("destination_stop_id"))
            or _normalize_text(pattern_info.get("destination_stop_id"))
            or _normalize_text(route_info.get("destination_stop_id"))
        )
        origin_name = (
            _normalize_text(row.get("origin_name"))
            or _normalize_text(pattern_info.get("origin_name"))
            or _normalize_text(route_info.get("origin_name"))
            or origin_stop_id
        )
        destination_name = (
            _normalize_text(row.get("destination_name"))
            or _normalize_text(pattern_info.get("destination_name"))
            or _normalize_text(route_info.get("destination_name"))
            or destination_stop_id
        )
        if not origin_stop_id or not destination_stop_id:
            warnings.append(
                f"Trip '{trip_id}' missing terminal stop ids; kept with available values."
            )
        item_base = {
            "trip_id": trip_id,
            "route_id": route_code,
            "day_type": day_type,
            "direction": direction,
            "service_variant": service_variant,
            "origin_stop_id": origin_stop_id,
            "destination_stop_id": destination_stop_id,
            "origin_name": origin_name,
            "destination_name": destination_name,
            "departure_time": _normalize_time_string(row.get("departure_time")),
            "arrival_time": _normalize_time_string(row.get("arrival_time")),
            "block_hint": _normalize_text(row.get("office_id")) or None,
            "distance_hint_km": float(
                row.get("distance_km")
                or pattern_info.get("distance_km")
                or route_info.get("distance_km")
                or 0.0
            ),
            "runtime_minutes": float(row.get("runtime_min") or 0.0),
            "allowed_vehicle_types": list(row.get("allowed_vehicle_types") or ["BEV", "ICE"]),
            "trip_index": int(row.get("trip_index") or 0),
            "operator_id": OPERATOR_ID,
            "pattern_id": pattern_id,
            "service_id": _normalize_text(row.get("service_id")).upper() or "WEEKDAY",
        }
        trip_headers_by_id[trip_id] = dict(item_base)
        route_day_types[route_code].add(day_type)
        route_directions[route_code].add(direction)
        route_variants[route_code].add(service_variant)
        profile = route_profile_by_code.setdefault(
            route_code,
            {
                "route_short_name": route_code,
                "name_candidates": [],
                "directions": set(),
                "service_variants": set(),
            },
        )
        profile["directions"].add(direction)
        profile["service_variants"].add(service_variant)
        profile["name_candidates"].extend(
            [
                (
                    origin_name and destination_name
                    and f"{route_code} ({origin_name} -> {destination_name})"
                ),
                route_info.get("route_long_name"),
                pattern_info.get("route_long_name_hint"),
            ]
        )
        for depot_id in candidate_depots:
            route_depot_ids[route_code].add(depot_id)
            item = dict(item_base)
            item["depot_id"] = depot_id
            groups[(depot_id, route_code, day_type)].append(item)
            trip_memberships[trip_id].add((depot_id, route_code, day_type))

    stop_times_by_trip_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    included_trip_ids = set(trip_headers_by_id)
    for row in stop_time_rows:
        trip_id = _normalize_text(row.get("trip_id"))
        if trip_id not in included_trip_ids:
            continue
        sequence = int(row.get("stop_sequence") or 0)
        stop_times_by_trip_id[trip_id].append(
            {
                "seq": sequence,
                "stop_id": _normalize_text(row.get("stop_id")),
                "stop_name": _normalize_text(row.get("stop_name")),
                "arrival_time": _normalize_time_string(row.get("arrival_time")),
                "departure_time": _normalize_time_string(row.get("departure_time")),
            }
        )

    for trip_id, items in stop_times_by_trip_id.items():
        items.sort(key=lambda item: (int(item.get("seq") or 0), str(item.get("stop_id") or "")))
        last_seq = -1
        for item in items:
            seq = int(item.get("seq") or 0)
            if seq < last_seq:
                raise RuntimeError(f"stop_time sequence is not ascending for trip '{trip_id}'")
            last_seq = seq

    route_catalog: dict[str, dict[str, Any]] = {}
    for route_code, depot_ids in route_to_depots.items():
        profile = route_profile_by_code.get(route_code) or {
            "route_short_name": route_code,
            "name_candidates": [],
            "directions": set(),
            "service_variants": set(),
        }
        route_catalog[route_code] = {
            "route_id": route_code,
            "route_short_name": _normalize_text(profile.get("route_short_name")) or route_code,
            "route_long_name": _route_long_name(profile.get("name_candidates") or [], route_code),
            "operator_id": OPERATOR_ID,
            "depot_ids": sorted(depot_ids),
            "available_day_types": sorted(route_day_types.get(route_code) or []),
            "direction_count": max(
                1,
                len(route_directions.get(route_code) or profile.get("directions") or []),
            ),
            "service_variant_types": sorted(
                route_variants.get(route_code)
                or profile.get("service_variants")
                or {"other"}
            ),
        }

    context = {
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "seed_version": seed_version,
        "services": services_payload,
        "route_catalog": route_catalog,
        "trip_headers_by_id": trip_headers_by_id,
        "trip_memberships": trip_memberships,
        "route_day_types": route_day_types,
        "route_depot_ids": route_depot_ids,
        "depots_master": depots_master,
    }
    return groups, stop_times_by_trip_id, route_catalog, context, source_counts


def _build_depots_payload(
    *,
    dataset_id: str,
    route_to_depots: dict[str, list[str]],
    depots_master: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    route_ids_by_depot: dict[str, list[str]] = defaultdict(list)
    for route_code, depot_ids in route_to_depots.items():
        for depot_id in depot_ids:
            if route_code not in route_ids_by_depot[depot_id]:
                route_ids_by_depot[depot_id].append(route_code)

    items: list[dict[str, Any]] = []
    for depot_id in sorted(route_ids_by_depot):
        depot = depots_master.get(depot_id) or {}
        items.append(
            {
                "depot_id": depot_id,
                "depot_name": depot.get("name") or depot.get("depotName") or depot_id,
                "operator_id": OPERATOR_ID,
                "lat": float(depot.get("lat") or 0.0),
                "lon": float(depot.get("lon") or 0.0),
                "route_ids": sorted(route_ids_by_depot.get(depot_id) or []),
                "notes": depot.get("notes") or None,
            }
        )

    return {
        "dataset_id": dataset_id,
        "operator_id": OPERATOR_ID,
        "depots": items,
    }


def _build_route_index_payload(
    *,
    dataset_id: str,
    route_to_depots: dict[str, list[str]],
    route_catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    depots: list[dict[str, Any]] = []
    depot_map: dict[str, list[str]] = defaultdict(list)
    for route_code, depot_ids in route_to_depots.items():
        for depot_id in depot_ids:
            if route_code not in depot_map[depot_id]:
                depot_map[depot_id].append(route_code)
    for depot_id in sorted(depot_map):
        depots.append(
            {
                "depot_id": depot_id,
                "route_ids": sorted(depot_map[depot_id]),
            }
        )

    routes: list[dict[str, Any]] = []
    for route_code in sorted(route_catalog):
        item = route_catalog[route_code]
        routes.append(
            {
                "route_id": route_code,
                "depot_ids": sorted(route_to_depots.get(route_code) or []),
                "available_day_types": sorted(item.get("available_day_types") or []),
            }
        )

    return {
        "dataset_id": dataset_id,
        "operator_id": OPERATOR_ID,
        "depots": depots,
        "routes": routes,
    }


def _build_route_summary_payload(
    *,
    dataset_id: str,
    route_to_depots: dict[str, list[str]],
    groups: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for route_code, depot_ids in sorted(route_to_depots.items()):
        for depot_id in sorted(depot_ids):
            day_groups = {
                day_type: list(groups.get((depot_id, route_code, day_type)) or [])
                for day_type in DAY_TYPES
            }
            all_trips = [
                trip
                for trip_items in day_groups.values()
                for trip in trip_items
            ]
            departures = [str(item.get("departure_time") or "") for item in all_trips if item.get("departure_time")]
            variants = Counter(str(item.get("service_variant") or "other") for item in all_trips)
            items.append(
                {
                    "depot_id": depot_id,
                    "route_id": route_code,
                    "weekday_trip_count": len(day_groups["weekday"]),
                    "saturday_trip_count": len(day_groups["saturday"]),
                    "holiday_trip_count": len(day_groups["holiday"]),
                    "first_departure": min(departures) if departures else None,
                    "last_departure": max(departures) if departures else None,
                    "main_trip_count": int(variants.get("main", 0)),
                    "short_turn_trip_count": int(variants.get("short_turn", 0)),
                    "depot_in_trip_count": int(variants.get("depot_in", 0)),
                    "depot_out_trip_count": int(variants.get("depot_out", 0)),
                }
            )
    return {
        "dataset_id": dataset_id,
        "operator_id": OPERATOR_ID,
        "items": items,
    }


def _build_trip_shard_payload(
    *,
    dataset_id: str,
    snapshot_id: str,
    depot_id: str,
    route_id: str,
    day_type: str,
    trips: list[dict[str, Any]],
    stop_times_by_trip_id: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sorted_items = sorted(
        trips,
        key=lambda item: (
            str(item.get("departure_time") or ""),
            str(item.get("trip_id") or ""),
        ),
    )
    items: list[dict[str, Any]] = []
    for item in sorted_items:
        trip_id = str(item.get("trip_id") or "")
        items.append(
            {
                "trip_id": trip_id,
                "depot_id": depot_id,
                "route_id": route_id,
                "day_type": day_type,
                "direction": item.get("direction") or "outbound",
                "service_variant": item.get("service_variant") or "other",
                "origin_stop_id": item.get("origin_stop_id") or "",
                "destination_stop_id": item.get("destination_stop_id") or "",
                "origin_name": item.get("origin_name") or item.get("origin_stop_id") or "",
                "destination_name": item.get("destination_name") or item.get("destination_stop_id") or "",
                "departure_time": item.get("departure_time") or "",
                "arrival_time": item.get("arrival_time") or "",
                "block_hint": item.get("block_hint"),
                "distance_hint_km": float(item.get("distance_hint_km") or 0.0),
                "runtime_minutes": float(item.get("runtime_minutes") or 0.0),
                "allowed_vehicle_types": list(item.get("allowed_vehicle_types") or ["BEV", "ICE"]),
                "trip_index": int(item.get("trip_index") or 0),
                "stop_time_count": _trip_item_stop_time_count(stop_times_by_trip_id, trip_id),
            }
        )
    return {
        "dataset_id": dataset_id,
        "operator_id": OPERATOR_ID,
        "source_version": snapshot_id,
        "artifact_kind": "trip_shard",
        "depot_id": depot_id,
        "route_id": route_id,
        "day_type": day_type,
        "items": items,
    }


def _build_timetable_like_payload(
    *,
    dataset_id: str,
    snapshot_id: str,
    depot_id: str,
    route_id: str,
    day_type: str,
    artifact_kind: str,
    trips: list[dict[str, Any]],
    stop_times_by_trip_id: dict[str, list[dict[str, Any]]],
    include_stop_name: bool,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for trip in sorted(
        trips,
        key=lambda item: (
            str(item.get("departure_time") or ""),
            str(item.get("trip_id") or ""),
        ),
    ):
        stop_times: list[dict[str, Any]] = []
        for stop_time in stop_times_by_trip_id.get(str(trip.get("trip_id") or ""), []):
            item = {
                "seq": int(stop_time.get("seq") or 0),
                "stop_id": stop_time.get("stop_id") or "",
                "arrival_time": stop_time.get("arrival_time") or "",
                "departure_time": stop_time.get("departure_time") or "",
            }
            if include_stop_name:
                item["stop_name"] = stop_time.get("stop_name") or stop_time.get("stop_id") or ""
            stop_times.append(item)
        items.append(
            {
                "trip_id": trip.get("trip_id") or "",
                "depot_id": depot_id,
                "route_id": route_id,
                "day_type": day_type,
                "direction": trip.get("direction") or "outbound",
                "service_variant": trip.get("service_variant") or "other",
                "origin_stop_id": trip.get("origin_stop_id") or "",
                "destination_stop_id": trip.get("destination_stop_id") or "",
                "origin_name": trip.get("origin_name") or trip.get("origin_stop_id") or "",
                "destination_name": trip.get("destination_name") or trip.get("destination_stop_id") or "",
                "departure_time": trip.get("departure_time") or "",
                "arrival_time": trip.get("arrival_time") or "",
                "stop_times": stop_times,
            }
        )
    return {
        "dataset_id": dataset_id,
        "operator_id": OPERATOR_ID,
        "source_version": snapshot_id,
        "artifact_kind": artifact_kind,
        "depot_id": depot_id,
        "route_id": route_id,
        "day_type": day_type,
        "items": items,
    }


def _write_shard_payload(
    *,
    root: Path,
    schema_root: Path,
    relative_dir: str,
    route_id: str,
    day_type: str,
    payload: dict[str, Any],
    schema_name: str,
) -> tuple[Path, int, int]:
    target = root / relative_dir / _safe_segment(route_id) / f"{day_type}.json"
    _validate_with_schema(schema_name, payload, schema_root)
    _write_json(target, payload)
    trip_count = len(payload.get("items") or [])
    stop_time_count = 0
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("stop_times"), list):
            stop_time_count += len(item.get("stop_times") or [])
        else:
            stop_time_count += int(item.get("stop_time_count") or 0)
    return target, trip_count, stop_time_count


def _validate_output_root(
    root: Path,
    schema_root: Path,
    *,
    expected_dataset_id: str | None = None,
) -> dict[str, Any]:
    if not root.exists():
        raise RuntimeError(f"Tokyu shard output root does not exist: {root}")
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Tokyu shard manifest does not exist: {manifest_path}")

    manifest = _read_json(manifest_path)
    _validate_with_schema("manifest.schema.json", manifest, schema_root)
    if expected_dataset_id and str(manifest.get("dataset_id") or "") != expected_dataset_id:
        raise RuntimeError(
            f"Tokyu shard manifest dataset_id '{manifest.get('dataset_id')}' does not match '{expected_dataset_id}'."
        )

    depots_payload = _read_json(root / "depots.json")
    routes_payload = _read_json(root / "routes.json")
    index_payload = _read_json(root / "depot_route_index.json")
    summary_payload = _read_json(root / "depot_route_summary.json")
    shard_manifest_payload = _read_json(root / "shard_manifest.json")

    _validate_with_schema("depot_route_index.schema.json", index_payload, schema_root)
    _validate_with_schema("depot_route_summary.schema.json", summary_payload, schema_root)
    _validate_with_schema("shard_manifest.schema.json", shard_manifest_payload, schema_root)
    if not isinstance(depots_payload.get("depots"), list):
        raise RuntimeError("depots.json is missing depots[]")
    if not isinstance(routes_payload.get("routes"), list):
        raise RuntimeError("routes.json is missing routes[]")

    trip_ids_by_key: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    timetable_trip_ids_by_key: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for entry in shard_manifest_payload.get("items") or []:
        if not isinstance(entry, dict):
            raise RuntimeError("shard_manifest.json contains non-object item")
        artifact_path = str(entry.get("artifact_path") or "").strip()
        if not artifact_path:
            raise RuntimeError("shard_manifest.json item missing artifact_path")
        payload_path = root / artifact_path
        if not payload_path.exists():
            raise RuntimeError(f"Shard artifact listed in manifest does not exist: {payload_path}")
        payload = _read_json(payload_path)
        artifact_kind = str(entry.get("artifact_kind") or "")
        if artifact_kind == "trip_shard":
            _validate_with_schema("trip_shard.schema.json", payload, schema_root)
        elif artifact_kind == "timetable_shard":
            _validate_with_schema("timetable_shard.schema.json", payload, schema_root)
        elif artifact_kind == "stop_time_shard":
            _validate_with_schema("stop_time_shard.schema.json", payload, schema_root)
        else:
            raise RuntimeError(f"Unknown artifact_kind '{artifact_kind}' in shard_manifest.json")

        items = [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]
        actual_trip_count = len(items)
        actual_stop_time_count = 0
        key = (
            str(entry.get("depot_id") or ""),
            str(entry.get("route_id") or ""),
            str(entry.get("day_type") or ""),
        )
        for item in items:
            if artifact_kind == "trip_shard":
                actual_stop_time_count += int(item.get("stop_time_count") or 0)
                if item.get("trip_id"):
                    trip_ids_by_key[key].add(str(item["trip_id"]))
            else:
                stop_times = [dict(row) for row in item.get("stop_times") or [] if isinstance(row, dict)]
                actual_stop_time_count += len(stop_times)
                last_seq = -1
                for stop_time in stop_times:
                    seq = int(stop_time.get("seq") or 0)
                    if seq < last_seq:
                        raise RuntimeError(
                            f"stop_time sequence is not ascending in {payload_path} for trip '{item.get('trip_id')}'"
                        )
                    last_seq = seq
                if item.get("trip_id") and artifact_kind == "timetable_shard":
                    timetable_trip_ids_by_key[key].add(str(item["trip_id"]))

        if int(entry.get("trip_count") or 0) != actual_trip_count:
            raise RuntimeError(
                f"trip_count mismatch for {payload_path}: manifest={entry.get('trip_count')} actual={actual_trip_count}"
            )
        if int(entry.get("stop_time_count") or 0) != actual_stop_time_count:
            raise RuntimeError(
                f"stop_time_count mismatch for {payload_path}: manifest={entry.get('stop_time_count')} actual={actual_stop_time_count}"
            )
        if int(entry.get("size_bytes") or 0) != payload_path.stat().st_size:
            raise RuntimeError(f"size_bytes mismatch for {payload_path}")
        if str(entry.get("hash") or "") != _hash_file(payload_path):
            raise RuntimeError(f"hash mismatch for {payload_path}")

    summary_pairs = {
        (str(item.get("depot_id") or ""), str(item.get("route_id") or ""))
        for item in summary_payload.get("items") or []
        if isinstance(item, dict)
    }
    for depot_item in index_payload.get("depots") or []:
        if not isinstance(depot_item, dict):
            raise RuntimeError("depot_route_index.json contains non-object depot item")
        depot_id = str(depot_item.get("depot_id") or "")
        for route_id in depot_item.get("route_ids") or []:
            pair = (depot_id, str(route_id or ""))
            if pair not in summary_pairs:
                raise RuntimeError(
                    f"depot_route_index route {pair} is missing from depot_route_summary.json"
                )

    for key, trip_ids in timetable_trip_ids_by_key.items():
        if not trip_ids.issubset(trip_ids_by_key.get(key) or set()):
            raise RuntimeError(
                f"timetable_shard contains trip_ids not present in trip_shard for key={key}"
            )

    return manifest


def build_tokyu_shards(
    dataset_id: str,
    *,
    validate_only: bool = False,
    depot_id: str | None = None,
    snapshot_id: str | None = None,
    canonical_root: Path = CANONICAL_ROOT,
    seed_root: Path = SEED_ROOT,
    output_root: Path = OUTPUT_ROOT,
    schema_root: Path = SCHEMA_ROOT,
) -> dict[str, Any]:
    if validate_only:
        manifest = _validate_output_root(output_root, schema_root, expected_dataset_id=dataset_id)
        return {
            "mode": "validate_only",
            "dataset_id": dataset_id,
            "manifest_path": str(output_root / "manifest.json"),
            "build_timestamp": manifest.get("build_timestamp"),
        }

    definition = _dataset_definition(seed_root, dataset_id)
    seed_version = _seed_version(seed_root)
    depots_master = _load_seed_depots(seed_root)
    route_rows = _load_route_to_depot_rows(seed_root)
    selected_depots, route_to_depots = _selected_route_scope(
        definition,
        route_rows,
        depot_filter=depot_id,
    )
    if not selected_depots:
        raise RuntimeError(f"Dataset '{dataset_id}' resolved to zero depots.")
    if not route_to_depots:
        raise RuntimeError(f"Dataset '{dataset_id}' resolved to zero route-to-depot assignments.")

    snapshot_id = snapshot_id or _latest_snapshot_id(canonical_root)
    snapshot_root = canonical_root / snapshot_id
    if not snapshot_root.exists():
        raise RuntimeError(f"Canonical snapshot does not exist: {snapshot_root}")

    warnings: list[str] = []
    (
        groups,
        stop_times_by_trip_id,
        route_catalog,
        build_context,
        source_counts,
    ) = _build_shard_state(
        dataset_id=dataset_id,
        snapshot_id=snapshot_id,
        seed_version=seed_version,
        route_to_depots=route_to_depots,
        depots_master=depots_master,
        canonical_root=snapshot_root,
        warnings=warnings,
    )

    staging_root = output_root.with_name(f"{output_root.name}.staging")
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    depots_payload = _build_depots_payload(
        dataset_id=dataset_id,
        route_to_depots=route_to_depots,
        depots_master=depots_master,
    )
    routes_payload = {
        "dataset_id": dataset_id,
        "operator_id": OPERATOR_ID,
        "routes": [route_catalog[route_id] for route_id in sorted(route_catalog)],
    }
    index_payload = _build_route_index_payload(
        dataset_id=dataset_id,
        route_to_depots=route_to_depots,
        route_catalog=route_catalog,
    )
    summary_payload = _build_route_summary_payload(
        dataset_id=dataset_id,
        route_to_depots=route_to_depots,
        groups=groups,
    )

    _write_json(staging_root / "depots.json", depots_payload)
    _write_json(staging_root / "routes.json", routes_payload)
    _validate_with_schema("depot_route_index.schema.json", index_payload, schema_root)
    _validate_with_schema("depot_route_summary.schema.json", summary_payload, schema_root)
    _write_json(staging_root / "depot_route_index.json", index_payload)
    _write_json(staging_root / "depot_route_summary.json", summary_payload)

    shard_manifest_items: list[dict[str, Any]] = []
    output_files: list[str] = [
        "depots.json",
        "routes.json",
        "depot_route_index.json",
        "depot_route_summary.json",
    ]

    for (depot_key, route_key, day_type), trips in sorted(groups.items()):
        trip_payload = _build_trip_shard_payload(
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            depot_id=depot_key,
            route_id=route_key,
            day_type=day_type,
            trips=trips,
            stop_times_by_trip_id=stop_times_by_trip_id,
        )
        timetable_payload = _build_timetable_like_payload(
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            depot_id=depot_key,
            route_id=route_key,
            day_type=day_type,
            artifact_kind="timetable_shard",
            trips=trips,
            stop_times_by_trip_id=stop_times_by_trip_id,
            include_stop_name=False,
        )
        stop_time_payload = _build_timetable_like_payload(
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            depot_id=depot_key,
            route_id=route_key,
            day_type=day_type,
            artifact_kind="stop_time_shard",
            trips=trips,
            stop_times_by_trip_id=stop_times_by_trip_id,
            include_stop_name=True,
        )

        for artifact_kind, relative_dir, payload, schema_name in (
            ("trip_shard", f"trip_shards/{_safe_segment(depot_key)}", trip_payload, "trip_shard.schema.json"),
            ("timetable_shard", f"timetable_shards/{_safe_segment(depot_key)}", timetable_payload, "timetable_shard.schema.json"),
            ("stop_time_shard", f"stop_time_shards/{_safe_segment(depot_key)}", stop_time_payload, "stop_time_shard.schema.json"),
        ):
            payload_path, trip_count, stop_time_count = _write_shard_payload(
                root=staging_root,
                schema_root=schema_root,
                relative_dir=relative_dir,
                route_id=route_key,
                day_type=day_type,
                payload=payload,
                schema_name=schema_name,
            )
            relative_path = _relative_path(staging_root, payload_path)
            output_files.append(relative_path)
            shard_manifest_items.append(
                {
                    "artifact_kind": artifact_kind,
                    "depot_id": depot_key,
                    "route_id": route_key,
                    "day_type": day_type,
                    "trip_count": trip_count,
                    "stop_time_count": stop_time_count,
                    "artifact_path": relative_path,
                    "hash": _hash_file(payload_path),
                    "size_bytes": payload_path.stat().st_size,
                }
            )

    shard_manifest_payload = {
        "dataset_id": dataset_id,
        "operator_id": OPERATOR_ID,
        "items": shard_manifest_items,
    }
    _validate_with_schema("shard_manifest.schema.json", shard_manifest_payload, schema_root)
    _write_json(staging_root / "shard_manifest.json", shard_manifest_payload)
    output_files.append("shard_manifest.json")

    included_trip_ids = set(build_context["trip_headers_by_id"])
    unassigned_trip_ids = sorted(
        trip_id
        for trip_id in included_trip_ids
        if not build_context["trip_memberships"].get(trip_id)
    )
    if unassigned_trip_ids:
        raise RuntimeError(
            f"{len(unassigned_trip_ids)} trips did not resolve to any shard. Sample={unassigned_trip_ids[:10]}"
        )

    manifest_payload = {
        "dataset_id": dataset_id,
        "operator": OPERATOR_NAME,
        "operator_id": OPERATOR_ID,
        "build_timestamp": _now_iso(),
        "source_version": snapshot_id,
        "seed_version": seed_version.get("seed_version"),
        "dataset_version": seed_version.get("dataset_version"),
        "shard_version": SHARD_VERSION,
        "available_depots": sorted(selected_depots),
        "available_routes": sorted(route_to_depots),
        "available_day_types": [
            day_type
            for day_type in DAY_TYPES
            if any(
                day_type in (item.get("available_day_types") or [])
                for item in route_catalog.values()
            )
        ],
        "output_files": sorted(set(output_files + ["manifest.json"])),
        "warnings": warnings,
        "warning_count": len(warnings),
        "selection": {
            "depot_filter": _normalize_text(depot_id) or None,
        },
        "source_counts": source_counts,
    }
    _validate_with_schema("manifest.schema.json", manifest_payload, schema_root)
    _write_json(staging_root / "manifest.json", manifest_payload)

    _validate_output_root(staging_root, schema_root, expected_dataset_id=dataset_id)

    if output_root.exists():
        shutil.rmtree(output_root)
    shutil.move(str(staging_root), str(output_root))
    return {
        "dataset_id": dataset_id,
        "output_root": str(output_root),
        "build_timestamp": manifest_payload["build_timestamp"],
        "warning_count": len(warnings),
        "shard_count": len(shard_manifest_items),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--depot", default=None)
    parser.add_argument("--snapshot", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = build_tokyu_shards(
            args.dataset,
            validate_only=bool(args.validate_only),
            depot_id=args.depot,
            snapshot_id=args.snapshot,
        )
    except Exception as exc:
        log.error("Tokyu shard build failed: %s", exc)
        return 1
    log.info("Tokyu shard build completed: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
