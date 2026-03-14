from __future__ import annotations

import csv
import importlib.util
import json
import logging
import sys
import unicodedata
from collections import defaultdict
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GTFS_FEED_PATH = REPO_ROOT / "GTFS" / "TokyuBus-GTFS"
_log = logging.getLogger(__name__)
SPECIAL_ROUTE_ALIASES = {
    "サンマバス": "さんまバス",
    "さんま": "さんまバス",
    "目黒区地域交通バスさんまバス": "さんまバス",
    "トランセ": "トランセ",
}


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple | set):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return [value]
            return _coerce_list(loaded)
        return [value]
    if hasattr(value, "tolist"):
        try:
            return _coerce_list(value.tolist())
        except Exception:
            pass
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _load_module(module_name: str, relative_path: str) -> Any:
    if module_name in sys.modules:
        return sys.modules[module_name]
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=2)
def _load_gtfs_core_bundle(feed_path: str) -> dict[str, Any]:
    gtfs_import = _load_module(
        "tokyu_gtfs_import_for_built",
        "lib/catalog_builder/gtfs_import.py",
    )
    return dict(gtfs_import.load_gtfs_core_bundle(feed_path=feed_path))


def _read_dataset_definition(seed_root: Path, dataset_id: str) -> dict[str, Any]:
    path = seed_root / "datasets" / f"{dataset_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Dataset definition not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


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


def _normalize_vehicle_types(value: Any) -> list[str]:
    if value is None:
        return ["BEV", "ICE"]
    if isinstance(value, str):
        return [value] if value else ["BEV", "ICE"]
    if isinstance(value, Iterable):
        items = [str(item) for item in value if item is not None and str(item)]
        return items or ["BEV", "ICE"]
    return ["BEV", "ICE"]


def _load_route_to_depot_map(seed_root: Path) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    with (seed_root / "route_to_depot.csv").open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            route_code = normalize_route_code(row.get("route_code"))
            depot_id = _normalize_text(row.get("depot_id"))
            if not route_code or not depot_id:
                continue
            if depot_id not in mapping[route_code]:
                mapping[route_code].append(depot_id)
    return dict(mapping)


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
                }
            )
    return rows


def _dataset_scope(seed_root: Path, dataset_id: str) -> tuple[set[str], set[str] | None]:
    definition = _read_dataset_definition(seed_root, dataset_id)
    included_depots = {_normalize_text(item) for item in definition.get("included_depots") or [] if _normalize_text(item)}
    included_routes_raw = definition.get("included_routes")
    if included_routes_raw == "ALL":
        included_routes = None
    else:
        included_routes = {
            normalize_route_code(item)
            for item in included_routes_raw or []
            if normalize_route_code(item)
        }
    return included_depots, included_routes


def _route_code_from_route(route: dict[str, Any]) -> str:
    return normalize_route_code(
        route.get("routeFamilyCode")
        or route.get("routeCode")
        or route.get("routeLabel")
        or route.get("name")
        or route.get("id")
    )


def _resolved_feed_path(feed_path: str | Path | None) -> Path:
    path = Path(feed_path) if feed_path else DEFAULT_GTFS_FEED_PATH
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Tokyu GTFS feed not found: {path}. "
            "Rebuild GTFS/TokyuBus-GTFS or pass --feed-path."
        )
    return path


def build_routes_artifact(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    *,
    force: bool = False,
    feed_path: str | Path | None = None,
) -> Path:
    built_dir.mkdir(parents=True, exist_ok=True)
    output_path = built_dir / "routes.parquet"
    if output_path.exists() and force:
        output_path.unlink()

    included_depots, included_routes = _dataset_scope(seed_root, dataset_id)
    route_to_depots = _load_route_to_depot_map(seed_root)
    feed_root = _resolved_feed_path(feed_path)
    bundle = _load_gtfs_core_bundle(str(feed_root))

    rows: list[dict[str, Any]] = []
    seen_route_ids: set[str] = set()
    for route in list(bundle.get("routes") or []):
        route_code = _route_code_from_route(route)
        if not route_code:
            continue
        if included_routes is not None and route_code not in included_routes:
            continue
        candidate_depots = list(route_to_depots.get(route_code) or [])
        if included_depots:
            candidate_depots = [depot_id for depot_id in candidate_depots if depot_id in included_depots]
        for depot_id in candidate_depots:
            route_id = f"tokyu:{depot_id}:{route_code}"
            if route_id in seen_route_ids:
                continue
            seen_route_ids.add(route_id)
            rows.append(
                {
                    "id": route_id,
                    "routeCode": route_code,
                    "routeLabel": route.get("routeLabel") or route.get("routeCode") or route_code,
                    "name": route.get("name") or route.get("routeLabel") or route_code,
                    "startStop": route.get("startStop") or "",
                    "endStop": route.get("endStop") or "",
                    "distanceKm": float(route.get("distanceKm") or route.get("distance_km") or 0.0),
                    "durationMin": int(float(route.get("durationMin") or route.get("duration_min") or 0)),
                    "color": route.get("color") or "",
                    "enabled": bool(route.get("enabled", True)),
                    "source": "gtfs_build",
                    "depotId": depot_id,
                    "routeFamilyCode": route.get("routeFamilyCode") or route_code,
                    "routeFamilyLabel": route.get("routeFamilyLabel") or route.get("routeLabel") or route_code,
                    "routeVariantType": route.get("routeVariantType"),
                    "canonicalDirection": route.get("canonicalDirection"),
                    "tripCount": int(float(route.get("tripCount") or route.get("trip_count") or 0)),
                    "stopSequence": list(route.get("stopSequence") or route.get("stop_sequence") or []),
                    "assignmentType": "authority_csv",
                    "assignmentConfidence": 1.0,
                    "assignmentReason": "route_to_depot_seed",
                    "gtfsRouteId": route.get("id"),
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError(
            f"No GTFS routes matched dataset '{dataset_id}'. "
            f"Check GTFS feed '{feed_root}' and route_to_depot.csv."
        )
    if included_routes is not None:
        matched_route_codes = {str(item.get("routeCode") or "") for item in rows}
        missing_route_codes = sorted(code for code in included_routes if code not in matched_route_codes)
        if missing_route_codes:
            _log.warning(
                "GTFS feed did not contain dataset route codes for '%s': %s",
                dataset_id,
                ", ".join(missing_route_codes),
            )
    frame.to_parquet(output_path, index=False)
    return output_path


def build_trips_artifact(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    *,
    feed_path: str | Path | None = None,
) -> Path:
    del dataset_id, seed_root
    built_dir.mkdir(parents=True, exist_ok=True)
    routes_path = built_dir / "routes.parquet"
    if not routes_path.exists():
        raise FileNotFoundError(f"Routes artifact not found: {routes_path}")

    routes = pd.read_parquet(routes_path).to_dict(orient="records")
    route_ids_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for route in routes:
        route_code = normalize_route_code(route.get("routeCode"))
        if route_code:
            route_ids_by_code[route_code].append(route)

    feed_root = _resolved_feed_path(feed_path)
    bundle = _load_gtfs_core_bundle(str(feed_root))
    route_code_by_gtfs_route_id = {
        str(route.get("id") or ""): _route_code_from_route(route)
        for route in list(bundle.get("routes") or [])
        if route.get("id")
    }

    trip_rows: list[dict[str, Any]] = []
    for row in list(bundle.get("timetable_rows") or []):
        gtfs_route_id = str(row.get("route_id") or "")
        route_code = route_code_by_gtfs_route_id.get(gtfs_route_id, "")
        if not route_code:
            continue
        matched_routes = route_ids_by_code.get(route_code) or []
        for route in matched_routes:
            route_id = str(route.get("id") or "")
            trip_rows.append(
                {
                    "trip_id": f"{route_id}::{row.get('trip_id')}",
                    "route_id": route_id,
                    "service_id": str(row.get("service_id") or "WEEKDAY"),
                    "departure": str(row.get("departure") or ""),
                    "arrival": str(row.get("arrival") or ""),
                    "origin": row.get("origin") or "",
                    "destination": row.get("destination") or "",
                    "distance_km": float(row.get("distance_km") or 0.0),
                    "allowed_vehicle_types": _normalize_vehicle_types(row.get("allowed_vehicle_types")),
                    "direction": row.get("direction") or "outbound",
                    "source": "gtfs_build",
                    "gtfs_trip_id": row.get("trip_id"),
                    "gtfs_route_id": gtfs_route_id,
                }
            )

    frame = pd.DataFrame(trip_rows)
    if frame.empty:
        raise RuntimeError(
            f"No GTFS timetable rows matched exported routes in '{routes_path}'. "
            f"Check route_to_depot.csv coverage for '{feed_root}'."
        )
    frame.to_parquet(built_dir / "trips.parquet", index=False)
    return built_dir / "trips.parquet"


def build_timetables_artifact(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
) -> Path:
    del dataset_id, seed_root
    built_dir.mkdir(parents=True, exist_ok=True)
    trips_path = built_dir / "trips.parquet"
    if not trips_path.exists():
        raise FileNotFoundError(f"Trips artifact not found: {trips_path}")

    trips = pd.read_parquet(trips_path)
    if trips.empty:
        raise RuntimeError(f"Trips artifact is empty: {trips_path}")

    timetable_rows = []
    for trip in trips.to_dict(orient="records"):
        timetable_rows.append(
            {
                "trip_id": trip.get("trip_id"),
                "route_id": trip.get("route_id"),
                "service_id": trip.get("service_id"),
                "origin": trip.get("origin") or "",
                "destination": trip.get("destination") or "",
                "departure": trip.get("departure") or "",
                "arrival": trip.get("arrival") or "",
                "distance_km": float(trip.get("distance_km") or 0.0),
                "allowed_vehicle_types": _normalize_vehicle_types(trip.get("allowed_vehicle_types")),
                "direction": trip.get("direction") or "outbound",
                "source": "gtfs_build",
                "gtfs_trip_id": trip.get("gtfs_trip_id"),
                "gtfs_route_id": trip.get("gtfs_route_id"),
            }
        )

    frame = pd.DataFrame(timetable_rows)
    if frame.empty:
        raise RuntimeError(f"No timetable rows were derived from trips artifact: {trips_path}")
    frame.to_parquet(built_dir / "timetables.parquet", index=False)
    return built_dir / "timetables.parquet"


def build_stops_artifact(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    *,
    feed_path: str | Path | None = None,
) -> Path:
    del dataset_id, seed_root
    built_dir.mkdir(parents=True, exist_ok=True)
    routes_path = built_dir / "routes.parquet"
    trips_path = built_dir / "trips.parquet"
    if not routes_path.exists():
        raise FileNotFoundError(f"Routes artifact not found: {routes_path}")
    if not trips_path.exists():
        raise FileNotFoundError(f"Trips artifact not found: {trips_path}")

    routes = pd.read_parquet(routes_path).to_dict(orient="records")
    trips = pd.read_parquet(trips_path).to_dict(orient="records")
    feed_root = _resolved_feed_path(feed_path)
    bundle = _load_gtfs_core_bundle(str(feed_root))
    stop_times_by_trip = dict(bundle.get("stop_times_by_trip") or {})
    stop_index = {
        str(item.get("id") or ""): item
        for item in list(bundle.get("stops") or [])
        if item.get("id")
    }

    scoped_stop_ids: set[str] = set()
    for route in routes:
        scoped_stop_ids.update(
            str(item)
            for item in _coerce_list(route.get("stopSequence"))
            if str(item).strip()
        )
    for trip in trips:
        gtfs_trip_id = str(trip.get("gtfs_trip_id") or "").strip()
        for stop_time in list(stop_times_by_trip.get(gtfs_trip_id) or []):
            stop_id = str(stop_time.get("stop_id") or "").strip()
            if stop_id:
                scoped_stop_ids.add(stop_id)

    rows: list[dict[str, Any]] = []
    for stop_id in sorted(scoped_stop_ids):
        stop = dict(stop_index.get(stop_id) or {})
        rows.append(
            {
                "id": stop_id,
                "code": stop.get("code") or stop_id,
                "name": stop.get("name") or stop_id,
                "kana": stop.get("kana") or "",
                "lat": stop.get("lat"),
                "lon": stop.get("lon"),
                "poleNumber": stop.get("poleNumber") or stop.get("platformCode") or "",
                "operatorId": stop.get("operatorId") or "tokyu",
                "source": "gtfs_build",
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError(
            f"No GTFS stops matched exported routes/trips in '{built_dir}'."
        )
    output_path = built_dir / "stops.parquet"
    frame.to_parquet(output_path, index=False)
    return output_path


def build_stop_timetables_artifact(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    *,
    feed_path: str | Path | None = None,
) -> Path:
    del dataset_id, seed_root
    built_dir.mkdir(parents=True, exist_ok=True)
    trips_path = built_dir / "trips.parquet"
    if not trips_path.exists():
        raise FileNotFoundError(f"Trips artifact not found: {trips_path}")

    trips = pd.read_parquet(trips_path).to_dict(orient="records")
    feed_root = _resolved_feed_path(feed_path)
    bundle = _load_gtfs_core_bundle(str(feed_root))
    stop_times_by_trip = dict(bundle.get("stop_times_by_trip") or {})
    stop_name_by_id = dict(bundle.get("stop_name_by_id") or {})
    headsign_by_trip = dict(bundle.get("headsign_by_trip") or {})

    grouped_entries: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trip in trips:
        dataset_trip_id = str(trip.get("trip_id") or "").strip()
        route_id = str(trip.get("route_id") or "").strip()
        service_id = str(trip.get("service_id") or "WEEKDAY").strip() or "WEEKDAY"
        gtfs_trip_id = str(trip.get("gtfs_trip_id") or "").strip()
        if not dataset_trip_id or not route_id or not gtfs_trip_id:
            continue
        for stop_time in list(stop_times_by_trip.get(gtfs_trip_id) or []):
            stop_id = str(stop_time.get("stop_id") or "").strip()
            if not stop_id:
                continue
            grouped_entries[(stop_id, service_id)].append(
                {
                    "arrival": stop_time.get("arrival"),
                    "departure": stop_time.get("departure"),
                    "busroutePattern": route_id,
                    "busTimetable": dataset_trip_id,
                    "destinationSign": trip.get("destination")
                    or headsign_by_trip.get(gtfs_trip_id)
                    or "",
                }
            )

    rows: list[dict[str, Any]] = []
    for (stop_id, service_id), entries in sorted(grouped_entries.items()):
        sorted_entries = sorted(
            entries,
            key=lambda item: (
                str(item.get("departure") or item.get("arrival") or ""),
                str(item.get("arrival") or item.get("departure") or ""),
                str(item.get("busTimetable") or ""),
            ),
        )
        rows.append(
            {
                "id": f"{stop_id}::{service_id}",
                "stopId": stop_id,
                "stopName": str(stop_name_by_id.get(stop_id) or stop_id),
                "calendar": service_id,
                "service_id": service_id,
                "source": "gtfs_build",
                "items": [
                    {
                        "index": index,
                        "arrival": entry.get("arrival"),
                        "departure": entry.get("departure"),
                        "busroutePattern": entry.get("busroutePattern"),
                        "busTimetable": entry.get("busTimetable"),
                        "destinationSign": entry.get("destinationSign"),
                    }
                    for index, entry in enumerate(sorted_entries)
                ],
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError(
            f"No stop timetables were derived from trips artifact: {trips_path}"
        )
    output_path = built_dir / "stop_timetables.parquet"
    frame.to_parquet(output_path, index=False)
    return output_path


def build_gtfs_reconciliation_artifact(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    *,
    feed_path: str | Path | None = None,
    strict: bool = False,
) -> Path:
    built_dir.mkdir(parents=True, exist_ok=True)

    included_depots, included_routes = _dataset_scope(seed_root, dataset_id)
    route_rows = _load_route_to_depot_rows(seed_root)
    scoped_rows = [
        row
        for row in route_rows
        if (not included_depots or row["depot_id"] in included_depots)
        and (included_routes is None or row["route_code"] in included_routes)
    ]
    scoped_route_codes = sorted({row["route_code"] for row in scoped_rows})
    depots_by_route_code: dict[str, list[str]] = defaultdict(list)
    for row in scoped_rows:
        if row["depot_id"] not in depots_by_route_code[row["route_code"]]:
            depots_by_route_code[row["route_code"]].append(row["depot_id"])

    feed_root = _resolved_feed_path(feed_path)
    bundle = _load_gtfs_core_bundle(str(feed_root))
    gtfs_routes = list(bundle.get("routes") or [])
    gtfs_timetable_rows = list(bundle.get("timetable_rows") or [])

    gtfs_route_ids_by_code: dict[str, list[str]] = defaultdict(list)
    route_code_by_gtfs_route_id: dict[str, str] = {}
    for route in gtfs_routes:
        route_code = _route_code_from_route(route)
        route_id = str(route.get("id") or "")
        if not route_code or not route_id:
            continue
        route_code_by_gtfs_route_id[route_id] = route_code
        if route_id not in gtfs_route_ids_by_code[route_code]:
            gtfs_route_ids_by_code[route_code].append(route_id)

    trip_count_by_route_code: Counter[str] = Counter()
    for row in gtfs_timetable_rows:
        route_code = route_code_by_gtfs_route_id.get(str(row.get("route_id") or ""), "")
        if route_code:
            trip_count_by_route_code[route_code] += 1

    master_route_codes_all = sorted({row["route_code"] for row in route_rows})
    gtfs_route_codes_all = sorted(gtfs_route_ids_by_code)
    matched_route_codes = sorted(code for code in scoped_route_codes if code in gtfs_route_ids_by_code)
    missing_master_route_codes = sorted(code for code in scoped_route_codes if code not in gtfs_route_ids_by_code)
    extra_gtfs_route_codes = sorted(code for code in gtfs_route_codes_all if code not in master_route_codes_all)

    route_details = [
        {
            "route_code": route_code,
            "depot_ids": depots_by_route_code.get(route_code, []),
            "master_route_row_count": sum(1 for row in scoped_rows if row["route_code"] == route_code),
            "gtfs_present": route_code in gtfs_route_ids_by_code,
            "gtfs_route_ids": gtfs_route_ids_by_code.get(route_code, []),
            "gtfs_trip_count": int(trip_count_by_route_code.get(route_code, 0)),
        }
        for route_code in scoped_route_codes
    ]

    report = {
        "dataset_id": dataset_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feed_path": str(feed_root),
        "scope": {
            "included_depots": sorted(included_depots),
            "included_routes": "ALL" if included_routes is None else sorted(included_routes),
            "master_route_rows": len(scoped_rows),
            "master_unique_route_codes": len(scoped_route_codes),
        },
        "global": {
            "master_unique_route_codes": len(master_route_codes_all),
            "gtfs_unique_route_codes": len(gtfs_route_codes_all),
            "master_only_route_codes": sorted(code for code in master_route_codes_all if code not in gtfs_route_ids_by_code),
            "gtfs_only_route_codes": extra_gtfs_route_codes,
        },
        "scoped": {
            "matched_route_codes": matched_route_codes,
            "missing_master_route_codes_in_gtfs": missing_master_route_codes,
            "matched_route_code_count": len(matched_route_codes),
            "missing_route_code_count": len(missing_master_route_codes),
            "matched_trip_count": int(sum(trip_count_by_route_code.get(code, 0) for code in matched_route_codes)),
        },
        "route_details": route_details,
    }

    report_path = built_dir / "gtfs_reconciliation.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if missing_master_route_codes:
        _log.warning(
            "GTFS reconciliation for '%s' is missing dataset route codes: %s",
            dataset_id,
            ", ".join(missing_master_route_codes),
        )
    if strict and missing_master_route_codes:
        raise RuntimeError(
            f"GTFS reconciliation failed for dataset '{dataset_id}'. "
            f"Missing route codes: {', '.join(missing_master_route_codes)}. "
            f"See {report_path}."
        )
    return report_path
