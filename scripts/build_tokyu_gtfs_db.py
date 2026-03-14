from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = REPO_ROOT / "data" / "seed" / "tokyu"
DEFAULT_GTFS_FEED_PATH = REPO_ROOT / "GTFS" / "TokyuBus-GTFS"
DEFAULT_OUT = REPO_ROOT / "data" / "tokyu_gtfs.sqlite"
OPERATOR_ID = "odpt.Operator:TokyuBus"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS operators (
    operator_id TEXT PRIMARY KEY,
    title_ja TEXT,
    title_en TEXT
);
CREATE TABLE IF NOT EXISTS depots (
    depot_id TEXT PRIMARY KEY,
    operator_id TEXT,
    depot_key TEXT,
    title_ja TEXT,
    title_en TEXT,
    address TEXT,
    phone TEXT,
    region TEXT,
    route_map_pdf TEXT,
    route_map_as_of TEXT,
    lat REAL,
    lon REAL,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS route_families (
    route_family TEXT,
    operator_id TEXT,
    route_code TEXT,
    title_ja TEXT,
    pattern_count INTEGER,
    depot_id TEXT,
    PRIMARY KEY(route_family, operator_id)
);
CREATE TABLE IF NOT EXISTS route_family_depots (
    route_family TEXT,
    operator_id TEXT,
    depot_id TEXT,
    source TEXT,
    PRIMARY KEY(route_family, operator_id, depot_id)
);
CREATE TABLE IF NOT EXISTS route_patterns (
    pattern_id TEXT PRIMARY KEY,
    operator_id TEXT,
    route_family TEXT,
    route_code TEXT,
    title_ja TEXT,
    title_kana TEXT,
    direction TEXT,
    via TEXT,
    depot_id TEXT,
    origin_stop_id TEXT,
    dest_stop_id TEXT,
    stop_count INTEGER,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS route_pattern_depots (
    pattern_id TEXT,
    depot_id TEXT,
    source TEXT,
    PRIMARY KEY(pattern_id, depot_id)
);
CREATE TABLE IF NOT EXISTS pattern_stops (
    pattern_id TEXT,
    seq INTEGER,
    stop_id TEXT,
    UNIQUE(pattern_id, seq)
);
CREATE TABLE IF NOT EXISTS route_code_depots (
    route_code TEXT,
    depot_id TEXT,
    source TEXT,
    PRIMARY KEY(route_code, depot_id, source)
);
CREATE TABLE IF NOT EXISTS stops (
    stop_id TEXT PRIMARY KEY,
    operator_id TEXT,
    title_ja TEXT,
    title_kana TEXT,
    lat REAL,
    lon REAL,
    platform_num TEXT,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS timetable_trips (
    trip_id TEXT PRIMARY KEY,
    timetable_id TEXT,
    pattern_id TEXT,
    route_family TEXT,
    calendar_type TEXT,
    direction TEXT,
    origin_stop_id TEXT,
    dest_stop_id TEXT,
    departure_hhmm TEXT,
    arrival_hhmm TEXT,
    dep_min INTEGER,
    arr_min INTEGER,
    duration_min INTEGER,
    stop_count INTEGER,
    is_nonstop INTEGER
);
CREATE TABLE IF NOT EXISTS trip_stops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT,
    seq INTEGER,
    stop_id TEXT,
    departure_hhmm TEXT,
    arrival_hhmm TEXT,
    dep_min INTEGER,
    arr_min INTEGER,
    UNIQUE(trip_id, seq)
);
CREATE TABLE IF NOT EXISTS stop_timetables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stop_id TEXT,
    pattern_id TEXT,
    calendar_type TEXT,
    direction TEXT,
    departure_hhmm TEXT,
    dep_min INTEGER,
    note TEXT
);
CREATE TABLE IF NOT EXISTS pipeline_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_route_patterns_family ON route_patterns(route_family);
CREATE INDEX IF NOT EXISTS idx_timetable_trips_pattern ON timetable_trips(pattern_id);
CREATE INDEX IF NOT EXISTS idx_trip_stops_trip ON trip_stops(trip_id);
CREATE INDEX IF NOT EXISTS idx_stop_timetables_stop ON stop_timetables(stop_id);
"""


def _load_module(module_name: str, relative_path: str) -> Any:
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize_route_code(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return ""
    if "さんま" in text:
        return "さんまバス"
    if "トランセ" in text:
        return "トランセ"
    return text


def _canonical_depot_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if text.startswith("tokyu:depot:") else f"tokyu:depot:{text}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dataset_scope(seed_root: Path, dataset_id: str) -> tuple[set[str], set[str] | None]:
    payload = _read_json(seed_root / "datasets" / f"{dataset_id}.json")
    included_depots = {
        _canonical_depot_id(item)
        for item in payload.get("included_depots") or []
        if _canonical_depot_id(item)
    }
    included_routes_raw = payload.get("included_routes")
    if included_routes_raw == "ALL":
        included_routes = None
    else:
        included_routes = {
            normalize_route_code(item)
            for item in included_routes_raw or []
            if normalize_route_code(item)
        }
    return included_depots, included_routes


def _load_seed_route_map(seed_root: Path) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    with (seed_root / "route_to_depot.csv").open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            route_code = normalize_route_code(row.get("route_code"))
            depot_id = _canonical_depot_id(row.get("depot_id"))
            if not route_code or not depot_id:
                continue
            mapping.setdefault(route_code, [])
            if depot_id not in mapping[route_code]:
                mapping[route_code].append(depot_id)
    return mapping


def _load_seed_depots(seed_root: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(seed_root / "depots.json")
    result: dict[str, dict[str, Any]] = {}
    for item in payload.get("depots") or []:
        depot_id = _canonical_depot_id(item.get("depotId") or item.get("id"))
        if depot_id:
            result[depot_id] = dict(item)
    return result


def _calendar_type_label(service_id: str) -> str:
    normalized = str(service_id or "WEEKDAY").strip().upper()
    if normalized == "SAT":
        return "土曜"
    if normalized in {"SUN_HOL", "SUN_HOLIDAY"}:
        return "日曜・休日"
    if normalized in {"SAT_HOL", "SAT_HOLIDAY"}:
        return "土曜・休日"
    return "平日"


def _hhmm_to_min(value: Any) -> int | None:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def _route_code_from_route(route: dict[str, Any]) -> str:
    return normalize_route_code(
        route.get("routeFamilyCode")
        or route.get("routeCode")
        or route.get("routeLabel")
        or route.get("name")
        or route.get("id")
    )


def build_tokyu_gtfs_db(
    out_path: Path,
    *,
    dataset_id: str = "tokyu_full",
    feed_path: str | Path = DEFAULT_GTFS_FEED_PATH,
    seed_root: Path = SEED_ROOT,
) -> Path:
    gtfs_import = _load_module("tokyu_gtfs_import_for_sqlite", "data-prep/lib/catalog_builder/gtfs_import.py")
    bundle = gtfs_import.load_gtfs_core_bundle(feed_path=feed_path)
    stop_tt_bundle = gtfs_import.build_gtfs_stop_timetables(feed_path=feed_path)

    included_depots, included_routes = _dataset_scope(seed_root, dataset_id)
    route_map = _load_seed_route_map(seed_root)
    seed_depots = _load_seed_depots(seed_root)

    routes = list(bundle.get("routes") or [])
    timetable_rows = list(bundle.get("timetable_rows") or [])
    stop_times_by_trip = dict(bundle.get("stop_times_by_trip") or {})
    stop_index = {
        str(stop.get("id") or ""): dict(stop)
        for stop in list(bundle.get("stops") or [])
        if stop.get("id")
    }

    scoped_routes: list[dict[str, Any]] = []
    primary_depot_by_pattern_id: dict[str, str | None] = {}
    candidate_depots_by_pattern_id: dict[str, list[str]] = {}
    candidate_depots_by_route_code: dict[str, list[str]] = {}
    unmatched_route_codes: set[str] = set()
    skipped_out_of_scope_route_codes: set[str] = set()

    for route in routes:
        route_code = _route_code_from_route(route)
        if not route_code:
            continue
        if included_routes is not None and route_code not in included_routes:
            continue

        mapped_depots = list(route_map.get(route_code) or [])
        candidate_depots = [
            depot_id
            for depot_id in mapped_depots
            if not included_depots or depot_id in included_depots
        ]
        if included_depots and mapped_depots and not candidate_depots:
            skipped_out_of_scope_route_codes.add(route_code)
            continue
        if not mapped_depots:
            unmatched_route_codes.add(route_code)
            if dataset_id != "tokyu_full":
                continue

        pattern_id = str(route.get("id") or "")
        primary_depot_by_pattern_id[pattern_id] = candidate_depots[0] if candidate_depots else None
        candidate_depots_by_pattern_id[pattern_id] = candidate_depots
        candidate_depots_by_route_code.setdefault(route_code, [])
        for depot_id in candidate_depots:
            if depot_id not in candidate_depots_by_route_code[route_code]:
                candidate_depots_by_route_code[route_code].append(depot_id)
        scoped_routes.append(dict(route))

    scoped_pattern_ids = {str(route.get("id") or "") for route in scoped_routes if route.get("id")}
    route_code_counts = Counter(_route_code_from_route(route) for route in scoped_routes)

    scoped_timetable_rows = [
        dict(row)
        for row in timetable_rows
        if str(row.get("route_id") or "") in scoped_pattern_ids
    ]
    scoped_trip_ids = {str(row.get("trip_id") or "") for row in scoped_timetable_rows if row.get("trip_id")}

    used_stop_ids: set[str] = set()
    for route in scoped_routes:
        for stop_id in list(route.get("stopSequence") or []):
            if str(stop_id).strip():
                used_stop_ids.add(str(stop_id))
    for trip_id in scoped_trip_ids:
        for stop_time in list(stop_times_by_trip.get(trip_id) or []):
            stop_id = str(stop_time.get("stop_id") or "").strip()
            if stop_id:
                used_stop_ids.add(stop_id)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    conn = sqlite3.connect(out_path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO operators VALUES (?, ?, ?)",
        (OPERATOR_ID, "東急バス", "Tokyu Bus"),
    )

    depot_rows = []
    for depot_id, depot in seed_depots.items():
        if included_depots and depot_id not in included_depots:
            continue
        depot_rows.append(
            (
                depot_id,
                OPERATOR_ID,
                depot_id.replace("tokyu:depot:", ""),
                depot.get("name") or depot.get("title_ja") or depot_id,
                depot.get("nameEn") or depot.get("title_en") or depot_id,
                depot.get("location") or "",
                "",
                depot.get("region") or "",
                "",
                "",
                depot.get("lat"),
                depot.get("lon"),
                json.dumps(depot, ensure_ascii=False),
            )
        )
    conn.executemany(
        "INSERT INTO depots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        depot_rows,
    )

    route_family_rows = []
    route_family_depot_rows = []
    route_pattern_rows = []
    route_pattern_depot_rows = []
    pattern_stop_rows = []
    route_code_depot_rows = []
    seen_route_families: set[str] = set()

    for route in scoped_routes:
        pattern_id = str(route.get("id") or "")
        route_code = _route_code_from_route(route)
        title = str(route.get("routeLabel") or route.get("name") or route_code)
        candidate_depots = list(candidate_depots_by_pattern_id.get(pattern_id) or [])
        primary_depot = primary_depot_by_pattern_id.get(pattern_id)

        if route_code not in seen_route_families:
            seen_route_families.add(route_code)
            route_family_rows.append(
                (
                    route_code,
                    OPERATOR_ID,
                    route_code,
                    title,
                    int(route_code_counts.get(route_code) or 0),
                    primary_depot,
                )
            )
            for depot_id in candidate_depots_by_route_code.get(route_code) or []:
                route_family_depot_rows.append(
                    (route_code, OPERATOR_ID, depot_id, "authority_csv")
                )
                route_code_depot_rows.append((route_code, depot_id, "authority_csv"))

        stop_sequence = [str(item) for item in list(route.get("stopSequence") or []) if str(item).strip()]
        route_pattern_rows.append(
            (
                pattern_id,
                OPERATOR_ID,
                route_code,
                route_code,
                title,
                "",
                str(route.get("canonicalDirection") or "").strip() or "unknown",
                "",
                primary_depot,
                stop_sequence[0] if stop_sequence else None,
                stop_sequence[-1] if stop_sequence else None,
                len(stop_sequence),
                json.dumps(route, ensure_ascii=False),
            )
        )
        for depot_id in candidate_depots:
            route_pattern_depot_rows.append((pattern_id, depot_id, "authority_csv"))
        for seq, stop_id in enumerate(stop_sequence, start=1):
            pattern_stop_rows.append((pattern_id, seq, stop_id))

    conn.executemany(
        "INSERT INTO route_families VALUES (?, ?, ?, ?, ?, ?)",
        route_family_rows,
    )
    conn.executemany(
        "INSERT INTO route_family_depots VALUES (?, ?, ?, ?)",
        route_family_depot_rows,
    )
    conn.executemany(
        "INSERT INTO route_patterns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        route_pattern_rows,
    )
    conn.executemany(
        "INSERT INTO route_pattern_depots VALUES (?, ?, ?)",
        route_pattern_depot_rows,
    )
    conn.executemany(
        "INSERT INTO pattern_stops VALUES (?, ?, ?)",
        pattern_stop_rows,
    )
    conn.executemany(
        "INSERT INTO route_code_depots VALUES (?, ?, ?)",
        route_code_depot_rows,
    )

    stop_rows = []
    for stop_id in sorted(used_stop_ids):
        stop = dict(stop_index.get(stop_id) or {})
        stop_rows.append(
            (
                stop_id,
                OPERATOR_ID,
                stop.get("name") or stop_id,
                stop.get("kana") or "",
                stop.get("lat"),
                stop.get("lon"),
                stop.get("poleNumber") or stop.get("platformCode") or "",
                json.dumps(stop, ensure_ascii=False),
            )
        )
    conn.executemany(
        "INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        stop_rows,
    )

    timetable_trip_rows = []
    trip_stop_rows = []
    direction_by_pattern_id = {
        str(route.get("id") or ""): str(route.get("canonicalDirection") or "").strip() or "unknown"
        for route in scoped_routes
    }
    route_code_by_pattern_id = {
        str(route.get("id") or ""): _route_code_from_route(route)
        for route in scoped_routes
    }
    for row in scoped_timetable_rows:
        trip_id = str(row.get("trip_id") or "")
        pattern_id = str(row.get("route_id") or "")
        stop_times = list(stop_times_by_trip.get(trip_id) or [])
        origin_stop_id = str(stop_times[0].get("stop_id") or "") if stop_times else ""
        dest_stop_id = str(stop_times[-1].get("stop_id") or "") if stop_times else ""
        departure = str(row.get("departure") or "")
        arrival = str(row.get("arrival") or "")
        dep_min = _hhmm_to_min(departure)
        arr_min = _hhmm_to_min(arrival)
        duration_min = (
            arr_min - dep_min
            if dep_min is not None and arr_min is not None and arr_min >= dep_min
            else None
        )
        timetable_trip_rows.append(
            (
                trip_id,
                f"{pattern_id}:{row.get('service_id')}",
                pattern_id,
                route_code_by_pattern_id.get(pattern_id) or "",
                _calendar_type_label(str(row.get("service_id") or "WEEKDAY")),
                direction_by_pattern_id.get(pattern_id) or str(row.get("direction") or "unknown"),
                origin_stop_id,
                dest_stop_id,
                departure,
                arrival,
                dep_min,
                arr_min,
                duration_min,
                len(stop_times),
                0,
            )
        )
        for seq, stop_time in enumerate(stop_times, start=1):
            departure_hhmm = stop_time.get("departure")
            arrival_hhmm = stop_time.get("arrival")
            trip_stop_rows.append(
                (
                    trip_id,
                    seq,
                    str(stop_time.get("stop_id") or ""),
                    departure_hhmm,
                    arrival_hhmm,
                    _hhmm_to_min(departure_hhmm),
                    _hhmm_to_min(arrival_hhmm),
                )
            )

    conn.executemany(
        "INSERT INTO timetable_trips VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        timetable_trip_rows,
    )
    conn.executemany(
        "INSERT INTO trip_stops (trip_id, seq, stop_id, departure_hhmm, arrival_hhmm, dep_min, arr_min) VALUES (?, ?, ?, ?, ?, ?, ?)",
        trip_stop_rows,
    )

    stop_timetable_rows = []
    for item in list(stop_tt_bundle.get("stop_timetables") or []):
        stop_id = str(item.get("stopId") or "")
        calendar_type = _calendar_type_label(str(item.get("service_id") or item.get("calendar") or "WEEKDAY"))
        for entry in list(item.get("items") or []):
            pattern_id = str(entry.get("busroutePattern") or "")
            trip_id = str(entry.get("busTimetable") or "")
            if pattern_id not in scoped_pattern_ids or trip_id not in scoped_trip_ids:
                continue
            stop_timetable_rows.append(
                (
                    stop_id,
                    pattern_id,
                    calendar_type,
                    direction_by_pattern_id.get(pattern_id) or "unknown",
                    entry.get("departure") or entry.get("arrival") or "",
                    _hhmm_to_min(entry.get("departure") or entry.get("arrival")),
                    str(entry.get("destinationSign") or ""),
                )
            )
    conn.executemany(
        "INSERT INTO stop_timetables (stop_id, pattern_id, calendar_type, direction, departure_hhmm, dep_min, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
        stop_timetable_rows,
    )

    pipeline_meta_rows = [
        ("built_at", datetime.now(timezone.utc).isoformat()),
        ("source", "gtfs"),
        ("dataset_id", dataset_id),
        ("feed_path", str(Path(feed_path).resolve())),
        ("route_family_count", str(len(route_family_rows))),
        ("route_pattern_count", str(len(route_pattern_rows))),
        ("stop_count", str(len(stop_rows))),
        ("timetable_trip_count", str(len(timetable_trip_rows))),
        ("trip_stop_count", str(len(trip_stop_rows))),
        ("stop_timetable_count", str(len(stop_timetable_rows))),
        ("unmatched_route_codes", json.dumps(sorted(unmatched_route_codes), ensure_ascii=False)),
        ("skipped_out_of_scope_route_codes", json.dumps(sorted(skipped_out_of_scope_route_codes), ensure_ascii=False)),
    ]
    conn.executemany(
        "INSERT INTO pipeline_meta VALUES (?, ?)",
        pipeline_meta_rows,
    )
    conn.commit()
    conn.close()
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--dataset-id", default="tokyu_full")
    parser.add_argument("--feed-path", default=str(DEFAULT_GTFS_FEED_PATH))
    args = parser.parse_args()

    output_path = build_tokyu_gtfs_db(
        Path(args.out),
        dataset_id=args.dataset_id,
        feed_path=args.feed_path,
    )
    print(f"db={output_path}")


if __name__ == "__main__":
    main()
