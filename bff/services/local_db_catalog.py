"""Local SQLite-backed Tokyu catalog service.

This service reads a prebuilt SQLite catalog and exposes lightweight lookup
functions for catalog APIs and MILP-oriented trip extraction. It never fetches
remote data at runtime.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.dispatch.models import Trip


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_CANDIDATES = (
    _REPO_ROOT / "data" / "tokyu_subset.sqlite",
    _REPO_ROOT / "data" / "tokyu_full.sqlite",
)
_DEFAULT_DB_PATH = next((path for path in _DEFAULT_DB_CANDIDATES if path.exists()), _DEFAULT_DB_CANDIDATES[0])
DB_PATH = Path(os.environ.get("TOKYU_DB_PATH", str(_DEFAULT_DB_PATH)))
DEFAULT_ALLOWED_VEHICLE_TYPES = ("BEV", "ICE")
DEFAULT_DISTANCE_KM = 0.0


def resolve_db_path() -> Path:
    raw = os.environ.get("TOKYU_DB_PATH")
    path = Path(raw) if raw else DB_PATH
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path


def get_conn() -> sqlite3.Connection:
    db_path = resolve_db_path()
    if not db_path.exists():
        raise FileNotFoundError(
            f"Tokyu catalog SQLite DB not found: {db_path}\n"
            "Build it first with either:\n"
            "  python scripts/build_tokyu_subset_db.py --api-key YOUR_KEY --skip-stop-timetables\n"
            "  python scripts/build_tokyu_full_db.py --api-key YOUR_KEY --skip-stop-timetables"
        )
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _normalize_depot_id(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("tokyu:depot:"):
        return text
    if ":" in text and not text.startswith("depot:"):
        return text
    return f"tokyu:depot:{text}"


def _normalize_depot_ids(
    depot_id: str | None = None,
    depot_ids: Sequence[str] | None = None,
) -> list[str]:
    values: list[str] = []
    for candidate in depot_ids or []:
        normalized = _normalize_depot_id(candidate)
        if normalized and normalized not in values:
            values.append(normalized)
    normalized_single = _normalize_depot_id(depot_id)
    if normalized_single and normalized_single not in values:
        values.append(normalized_single)
    return values


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _minutes_to_hhmm(value: int | None, fallback: str = "00:00", wrap: bool = False) -> str:
    if value is None:
        return fallback
    minutes = int(value)
    if wrap:
        minutes %= 1440
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _query_dicts(conn: sqlite3.Connection, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    return _rows_to_dicts(conn.execute(sql, params or []))


def _attach_depot_scope(
    records: list[dict[str, Any]],
    key_field: str,
    depot_map: dict[str, list[str]],
    selected_depots: Sequence[str] | None,
) -> list[dict[str, Any]]:
    selected = list(selected_depots or [])
    selected_set = set(selected)
    scoped: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get(key_field) or "")
        mapped = list(depot_map.get(key) or [])
        matching = [depot for depot in mapped if depot in selected_set] if selected else list(mapped)
        if selected and not matching:
            continue
        chosen = matching[0] if matching else (mapped[0] if mapped else _normalize_depot_id(record.get("depot_id")))
        scoped.append(
            {
                **record,
                "depot_id": chosen or "",
                "depot_ids": mapped,
                "matched_depot_ids": matching or mapped,
            }
        )
    return scoped


def _load_pattern_depot_map(
    conn: sqlite3.Connection,
    pattern_ids: Sequence[str] | None = None,
) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    params: list[Any] = []
    if _table_exists(conn, "route_pattern_depots"):
        sql = "SELECT pattern_id, depot_id FROM route_pattern_depots"
        if pattern_ids:
            placeholders = ",".join("?" for _ in pattern_ids)
            sql += f" WHERE pattern_id IN ({placeholders})"
            params.extend(pattern_ids)
        sql += " ORDER BY pattern_id, depot_id"
        rows = conn.execute(sql, params).fetchall()
    else:
        sql = "SELECT pattern_id, depot_id FROM route_patterns"
        if pattern_ids:
            placeholders = ",".join("?" for _ in pattern_ids)
            sql += f" WHERE pattern_id IN ({placeholders})"
            params.extend(pattern_ids)
        sql += " ORDER BY pattern_id, depot_id"
        rows = conn.execute(sql, params).fetchall()

    for row in rows:
        pattern_id = str(row[0] or "")
        depot_id = _normalize_depot_id(row[1])
        if pattern_id and depot_id and depot_id not in mapping[pattern_id]:
            mapping[pattern_id].append(depot_id)
    return mapping


def _load_route_family_depot_map(
    conn: sqlite3.Connection,
    route_families: Sequence[str] | None = None,
) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    params: list[Any] = []
    if _table_exists(conn, "route_family_depots"):
        sql = "SELECT route_family, depot_id FROM route_family_depots"
        if route_families:
            placeholders = ",".join("?" for _ in route_families)
            sql += f" WHERE route_family IN ({placeholders})"
            params.extend(route_families)
        sql += " ORDER BY route_family, depot_id"
        rows = conn.execute(sql, params).fetchall()
    else:
        sql = "SELECT route_family, depot_id FROM route_families"
        if route_families:
            placeholders = ",".join("?" for _ in route_families)
            sql += f" WHERE route_family IN ({placeholders})"
            params.extend(route_families)
        sql += " ORDER BY route_family, depot_id"
        rows = conn.execute(sql, params).fetchall()

    for row in rows:
        route_family = str(row[0] or "")
        depot_id = _normalize_depot_id(row[1])
        if route_family and depot_id and depot_id not in mapping[route_family]:
            mapping[route_family].append(depot_id)
    return mapping


def health_check() -> dict[str, Any]:
    db_path = resolve_db_path()
    if not db_path.exists():
        return {
            "status": "db_not_found",
            "db_path": str(db_path),
            "message": "Tokyu catalog SQLite DB not found",
        }
    try:
        with get_conn() as conn:
            meta_rows = conn.execute("SELECT key, value FROM pipeline_meta").fetchall()
            meta = {str(row[0]): row[1] for row in meta_rows}
            counts = {
                "operators": conn.execute("SELECT COUNT(*) FROM operators").fetchone()[0],
                "depots": conn.execute("SELECT COUNT(*) FROM depots").fetchone()[0],
                "route_families": conn.execute("SELECT COUNT(*) FROM route_families").fetchone()[0],
                "route_patterns": conn.execute("SELECT COUNT(*) FROM route_patterns").fetchone()[0],
                "stops": conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0],
                "timetable_trips": conn.execute("SELECT COUNT(*) FROM timetable_trips").fetchone()[0],
                "trip_stops": conn.execute("SELECT COUNT(*) FROM trip_stops").fetchone()[0],
                "stop_timetables": conn.execute("SELECT COUNT(*) FROM stop_timetables").fetchone()[0],
            }
        return {"status": "ok", "db_path": str(db_path), **counts, **meta}
    except Exception as exc:
        return {"status": "error", "db_path": str(db_path), "message": str(exc)}


def list_operators() -> list[dict[str, Any]]:
    with get_conn() as conn:
        return _query_dicts(conn, "SELECT * FROM operators ORDER BY operator_id")


def list_depots(operator_id: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM depots"
    params: list[Any] = []
    if operator_id:
        sql += " WHERE operator_id=?"
        params.append(operator_id)
    sql += " ORDER BY depot_id"
    with get_conn() as conn:
        return _query_dicts(conn, sql, params)


def get_depot(depot_id: str) -> dict[str, Any] | None:
    normalized = _normalize_depot_id(depot_id)
    if normalized is None:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM depots WHERE depot_id=?", (normalized,)).fetchone()
    return dict(row) if row else None


def list_route_families(
    operator_id: str | None = None,
    depot_id: str | None = None,
    depot_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM route_families"
    params: list[Any] = []
    if operator_id:
        sql += " WHERE operator_id=?"
        params.append(operator_id)
    sql += " ORDER BY route_family"
    selected_depots = _normalize_depot_ids(depot_id, depot_ids)
    with get_conn() as conn:
        records = _query_dicts(conn, sql, params)
        depot_map = _load_route_family_depot_map(conn, [str(item.get("route_family") or "") for item in records])
    scoped = _attach_depot_scope(records, "route_family", depot_map, selected_depots)
    scoped.sort(key=lambda item: (str(item.get("route_family") or ""), str(item.get("depot_id") or "")))
    return scoped


def get_route_family_detail(operator_id: str, route_family: str) -> dict[str, Any] | None:
    families = list_route_families(operator_id=operator_id)
    family = next((item for item in families if str(item.get("route_family") or "") == route_family), None)
    patterns = list_route_patterns(operator_id=operator_id, route_family=route_family)
    if family is None and not patterns:
        return None
    return {
        "operator_id": operator_id,
        "route_family": route_family,
        "pattern_count": len(patterns),
        "depot_id": str((family or {}).get("depot_id") or ""),
        "depot_ids": list((family or {}).get("depot_ids") or []),
        "patterns": patterns,
    }


def list_route_patterns(
    operator_id: str | None = None,
    route_family: str | None = None,
    depot_id: str | None = None,
    depot_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM route_patterns WHERE 1=1"
    params: list[Any] = []
    if operator_id:
        sql += " AND operator_id=?"
        params.append(operator_id)
    if route_family:
        sql += " AND route_family=?"
        params.append(route_family)
    sql += " ORDER BY route_family, direction, pattern_id"
    selected_depots = _normalize_depot_ids(depot_id, depot_ids)
    with get_conn() as conn:
        records = _query_dicts(conn, sql, params)
        depot_map = _load_pattern_depot_map(conn, [str(item.get("pattern_id") or "") for item in records])
    scoped = _attach_depot_scope(records, "pattern_id", depot_map, selected_depots)
    scoped.sort(key=lambda item: (str(item.get("route_family") or ""), str(item.get("direction") or ""), str(item.get("pattern_id") or "")))
    return scoped


def get_pattern_stops(pattern_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return _query_dicts(
            conn,
            """
            SELECT ps.seq, ps.stop_id, s.title_ja, s.lat, s.lon
            FROM pattern_stops ps
            LEFT JOIN stops s ON ps.stop_id=s.stop_id
            WHERE ps.pattern_id=?
            ORDER BY ps.seq
            """,
            (pattern_id,),
        )


def list_stops(operator_id: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM stops"
    params: list[Any] = []
    if operator_id:
        sql += " WHERE operator_id=?"
        params.append(operator_id)
    sql += " ORDER BY stop_id"
    with get_conn() as conn:
        return _query_dicts(conn, sql, params)


def get_stop(stop_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stops WHERE stop_id=?", (stop_id,)).fetchone()
    return dict(row) if row else None


def get_timetable_trips(
    route_family: str | None = None,
    pattern_id: str | None = None,
    calendar_type: str = "平日",
    direction: str | None = None,
    depot_id: str | None = None,
    depot_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            t.*,
            rp.route_code,
            rp.depot_id AS primary_depot_id
        FROM timetable_trips t
        LEFT JOIN route_patterns rp ON t.pattern_id=rp.pattern_id
        WHERE t.calendar_type=?
    """
    params: list[Any] = [calendar_type]
    if route_family:
        sql += " AND t.route_family=?"
        params.append(route_family)
    if pattern_id:
        sql += " AND t.pattern_id=?"
        params.append(pattern_id)
    if direction:
        sql += " AND t.direction=?"
        params.append(direction)
    sql += " ORDER BY t.dep_min, t.route_family, t.pattern_id, t.trip_id"

    selected_depots = _normalize_depot_ids(depot_id, depot_ids)
    with get_conn() as conn:
        records = _query_dicts(conn, sql, params)
        depot_map = _load_pattern_depot_map(conn, [str(item.get("pattern_id") or "") for item in records])
    scoped = _attach_depot_scope(records, "pattern_id", depot_map, selected_depots)
    result: list[dict[str, Any]] = []
    for item in scoped:
        dep_min = item.get("dep_min")
        arr_min = item.get("arr_min")
        dep_min_int = _safe_int(dep_min, 0) if dep_min is not None else None
        arr_min_int = _safe_int(arr_min, dep_min_int or 0) if arr_min is not None else None
        if dep_min_int is not None and arr_min_int is not None and arr_min_int <= dep_min_int:
            arr_min_int += 1440
        departure_time = str(item.get("departure_hhmm") or _minutes_to_hhmm(dep_min_int))
        arrival_time = str(item.get("arrival_hhmm") or _minutes_to_hhmm(arr_min_int))
        if dep_min_int is not None:
            departure_time = _minutes_to_hhmm(dep_min_int, fallback=departure_time)
        if arr_min_int is not None:
            arrival_time = _minutes_to_hhmm(arr_min_int, fallback=arrival_time)
        result.append(
            {
                **item,
                "dep_min": dep_min_int,
                "arr_min": arr_min_int,
                "departure_time": departure_time,
                "arrival_time": arrival_time,
                "origin": str(item.get("origin_stop_id") or ""),
                "destination": str(item.get("dest_stop_id") or ""),
            }
        )
    result.sort(
        key=lambda item: (
            _safe_int(item.get("dep_min"), 0),
            str(item.get("route_family") or ""),
            str(item.get("pattern_id") or ""),
            str(item.get("trip_id") or ""),
        )
    )
    return result


def get_trip_stops(trip_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return _query_dicts(
            conn,
            """
            SELECT ts.seq, ts.stop_id, s.title_ja,
                   ts.departure_hhmm, ts.arrival_hhmm, ts.dep_min, ts.arr_min
            FROM trip_stops ts
            LEFT JOIN stops s ON ts.stop_id=s.stop_id
            WHERE ts.trip_id=?
            ORDER BY ts.seq
            """,
            (trip_id,),
        )


def get_trip_summary(
    calendar_type: str = "平日",
    depot_id: str | None = None,
    depot_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    trips = get_timetable_trips(calendar_type=calendar_type, depot_id=depot_id, depot_ids=depot_ids)
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for trip in trips:
        key = (str(trip.get("route_family") or ""), str(trip.get("direction") or ""))
        current = grouped.get(key)
        dep_time = str(trip.get("departure_time") or "")
        if current is None:
            grouped[key] = {
                "route_family": key[0],
                "direction": key[1],
                "trip_count": 1,
                "first_dep": dep_time,
                "last_dep": str(trip.get("arrival_time") or dep_time),
                "depot_ids": list(trip.get("depot_ids") or []),
            }
            continue
        current["trip_count"] += 1
        current["first_dep"] = min(str(current.get("first_dep") or dep_time), dep_time)
        current["last_dep"] = max(str(current.get("last_dep") or dep_time), str(trip.get("arrival_time") or dep_time))
        current["depot_ids"] = sorted(set(list(current.get("depot_ids") or []) + list(trip.get("depot_ids") or [])))
    routes = list(grouped.values())
    routes.sort(key=lambda item: (str(item.get("route_family") or ""), str(item.get("direction") or "")))
    return {"calendar_type": calendar_type, "routes": routes}


def get_stop_timetable(
    stop_id: str,
    pattern_id: str | None = None,
    calendar_type: str = "平日",
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM stop_timetables WHERE stop_id=? AND calendar_type=?"
    params: list[Any] = [stop_id, calendar_type]
    if pattern_id:
        sql += " AND pattern_id=?"
        params.append(pattern_id)
    sql += " ORDER BY dep_min"
    with get_conn() as conn:
        return _query_dicts(conn, sql, params)


def _stable_route_key(record: dict[str, Any]) -> str:
    family = str(record.get("route_family") or "unknown")
    pattern = str(record.get("pattern_id") or "pattern")
    return f"tokyu:{family}:{pattern}"


def milp_trip_to_dispatch_trip(record: dict[str, Any]) -> Trip:
    dep_min = _safe_int(record.get("dep_min"))
    arr_min = _safe_int(record.get("arr_min"), dep_min)
    if arr_min <= dep_min:
        arr_min += 1440
    return Trip(
        trip_id=str(record.get("trip_id") or ""),
        route_id=str(record.get("route_id") or _stable_route_key(record)),
        origin=str(record.get("origin") or record.get("origin_stop_id") or ""),
        destination=str(record.get("destination") or record.get("dest_stop_id") or ""),
        departure_time=str(record.get("departure_time") or _minutes_to_hhmm(dep_min)),
        arrival_time=str(record.get("arrival_time") or _minutes_to_hhmm(arr_min)),
        distance_km=float(record.get("distance_km") or DEFAULT_DISTANCE_KM),
        allowed_vehicle_types=tuple(record.get("allowed_vehicle_types") or DEFAULT_ALLOWED_VEHICLE_TYPES),
    )


def build_milp_trips(
    route_families: Sequence[str] | None = None,
    depot_id: str | None = None,
    depot_ids: Sequence[str] | None = None,
    calendar_type: str = "平日",
    min_dep_min: int = 0,
    max_dep_min: int = 1440,
) -> list[dict[str, Any]]:
    trips = get_timetable_trips(
        calendar_type=calendar_type,
        depot_id=depot_id,
        depot_ids=depot_ids,
    )
    allowed_families = {str(item) for item in route_families or []}
    result: list[dict[str, Any]] = []
    for item in trips:
        family = str(item.get("route_family") or "")
        if allowed_families and family not in allowed_families:
            continue
        dep = item.get("dep_min")
        if dep is None:
            continue
        dep_min = _safe_int(dep)
        arr_value = item.get("arr_min")
        if arr_value is None:
            arr_value = dep_min + _safe_int(item.get("duration_min"), 0)
        arr_min = _safe_int(arr_value, dep_min)
        if arr_min <= dep_min:
            arr_min += 1440
        if not (min_dep_min <= dep_min <= max_dep_min):
            continue

        record = {
            "trip_id": str(item.get("trip_id") or ""),
            "route_id": _stable_route_key(item),
            "route_family": family,
            "pattern_id": str(item.get("pattern_id") or ""),
            "direction": str(item.get("direction") or ""),
            "depot_id": str(item.get("depot_id") or ""),
            "depot_ids": list(item.get("depot_ids") or []),
            "origin": str(item.get("origin") or item.get("origin_stop_id") or ""),
            "destination": str(item.get("destination") or item.get("dest_stop_id") or ""),
            "origin_stop_id": str(item.get("origin_stop_id") or ""),
            "dest_stop_id": str(item.get("dest_stop_id") or ""),
            "departure_time": _minutes_to_hhmm(dep_min, fallback=str(item.get("departure_time") or "")),
            "arrival_time": _minutes_to_hhmm(arr_min, fallback=str(item.get("arrival_time") or "")),
            "dep_min": dep_min,
            "arr_min": arr_min,
            "duration_min": arr_min - dep_min,
            "stop_count": _safe_int(item.get("stop_count"), 0),
            "allowed_vehicle_types": list(DEFAULT_ALLOWED_VEHICLE_TYPES),
            "distance_km": DEFAULT_DISTANCE_KM,
        }
        dispatch_trip = milp_trip_to_dispatch_trip(record)
        record["dispatch_trip"] = {
            "trip_id": dispatch_trip.trip_id,
            "route_id": dispatch_trip.route_id,
            "origin": dispatch_trip.origin,
            "destination": dispatch_trip.destination,
            "departure_time": dispatch_trip.departure_time,
            "arrival_time": dispatch_trip.arrival_time,
            "distance_km": dispatch_trip.distance_km,
            "allowed_vehicle_types": list(dispatch_trip.allowed_vehicle_types),
        }
        result.append(record)

    result.sort(key=lambda item: (item["dep_min"], item["route_family"], item["trip_id"]))
    return result


def build_optimizer_trips(
    route_families: Sequence[str] | None = None,
    depot_id: str | None = None,
    depot_ids: Sequence[str] | None = None,
    calendar_type: str = "平日",
    min_dep_min: int = 0,
    max_dep_min: int = 1440,
) -> list[dict[str, Any]]:
    return build_milp_trips(
        route_families=route_families,
        depot_id=depot_id,
        depot_ids=depot_ids,
        calendar_type=calendar_type,
        min_dep_min=min_dep_min,
        max_dep_min=max_dep_min,
    )


def build_dispatch_trips(
    route_families: Sequence[str] | None = None,
    depot_id: str | None = None,
    depot_ids: Sequence[str] | None = None,
    calendar_type: str = "平日",
    min_dep_min: int = 0,
    max_dep_min: int = 1440,
) -> list[Trip]:
    return [
        milp_trip_to_dispatch_trip(item)
        for item in build_optimizer_trips(
            route_families=route_families,
            depot_id=depot_id,
            depot_ids=depot_ids,
            calendar_type=calendar_type,
            min_dep_min=min_dep_min,
            max_dep_min=max_dep_min,
        )
    ]
