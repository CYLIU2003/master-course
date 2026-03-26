"""Local SQLite-backed Tokyu catalog service.

This service reads a prebuilt SQLite catalog and exposes lightweight lookup
functions for catalog APIs and MILP-oriented trip extraction. It never fetches
remote data at runtime.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from bff.services.route_family import derive_route_family_metadata
from src.dispatch.models import Trip
from src.geo import haversine_km


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_CANDIDATES = (
    _REPO_ROOT / "data" / "tokyu_subset.sqlite",
    _REPO_ROOT / "data" / "tokyu_full.sqlite",
)
_DEFAULT_DB_PATH = next((path for path in _DEFAULT_DB_CANDIDATES if path.exists()), _DEFAULT_DB_CANDIDATES[0])
DB_PATH = Path(os.environ.get("TOKYU_DB_PATH", str(_DEFAULT_DB_PATH)))
OPERATOR_ID = "odpt.Operator:TokyuBus"
DEFAULT_ALLOWED_VEHICLE_TYPES = ("BEV", "ICE")
DEFAULT_DISTANCE_KM = 0.0
DEFAULT_KM_PER_STOP_HOP = 0.6
_DEPOT_KEYWORDS = ("営業所", "操車所", "操車場", "車庫")


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
            "  python scripts/build_tokyu_subset_db.py --skip-stop-timetables\n"
            "  python scripts/build_tokyu_full_db.py --skip-stop-timetables\n"
            "If your key is not in .env, add --api-key YOUR_KEY."
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
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


def _normalize_label(value: Any) -> str:
    return str(value or "").strip()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _query_dicts(conn: sqlite3.Connection, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    return _rows_to_dicts(conn.execute(sql, params or []))


def _straight_line_distance_km(record: dict[str, Any]) -> float:
    required = [
        record.get("origin_lat"),
        record.get("origin_lon"),
        record.get("destination_lat"),
        record.get("destination_lon"),
    ]
    if any(value is None for value in required):
        return DEFAULT_DISTANCE_KM
    return round(
        haversine_km(
            _safe_float(record.get("origin_lat")),
            _safe_float(record.get("origin_lon")),
            _safe_float(record.get("destination_lat")),
            _safe_float(record.get("destination_lon")),
        ),
        4,
    )


def _estimate_pattern_distance_km(record: dict[str, Any]) -> float:
    straight_km = _straight_line_distance_km(record)
    if straight_km > 0.0:
        # Apply a modest detour factor so route length is not underestimated.
        return round(straight_km * 1.2, 4)
    stop_count = _safe_int(record.get("stop_count"), 0)
    if stop_count > 1:
        return round((stop_count - 1) * DEFAULT_KM_PER_STOP_HOP, 4)
    return DEFAULT_DISTANCE_KM


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


def _calendar_count_key(calendar_type: str) -> str:
    return {
        "平日": "tripCountWeekday",
        "土曜": "tripCountSaturday",
        "日曜・休日": "tripCountSunday",
    }.get(calendar_type, "tripCountWeekday")


def _load_pattern_stop_names(
    conn: sqlite3.Connection,
    pattern_ids: Sequence[str],
) -> dict[str, list[str]]:
    if not pattern_ids:
        return {}
    placeholders = ",".join("?" for _ in pattern_ids)
    rows = conn.execute(
        f"""
        SELECT ps.pattern_id, ps.seq, COALESCE(s.title_ja, ps.stop_id) AS stop_name
        FROM pattern_stops ps
        LEFT JOIN stops s ON s.stop_id = ps.stop_id
        WHERE ps.pattern_id IN ({placeholders})
        ORDER BY ps.pattern_id, ps.seq
        """,
        list(pattern_ids),
    ).fetchall()
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        grouped[str(row[0])].append(str(row[2] or ""))
    return grouped


def _load_pattern_trip_counts(
    conn: sqlite3.Connection,
    pattern_ids: Sequence[str],
) -> dict[str, dict[str, int]]:
    if not pattern_ids:
        return {}
    placeholders = ",".join("?" for _ in pattern_ids)
    rows = conn.execute(
        f"""
        SELECT pattern_id, calendar_type, COUNT(*) AS trip_count
        FROM timetable_trips
        WHERE pattern_id IN ({placeholders})
        GROUP BY pattern_id, calendar_type
        """,
        list(pattern_ids),
    ).fetchall()
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"平日": 0, "土曜": 0, "日曜・休日": 0}
    )
    for pattern_id, calendar_type, trip_count in rows:
        counts[str(pattern_id)][str(calendar_type or "平日")] = int(trip_count or 0)
    return counts


def _pattern_type_from_variant(
    *,
    route_code: str,
    origin_name: str,
    destination_name: str,
    stop_count: int,
    max_stop_count: int,
    variant_type: str,
) -> tuple[str, bool, str]:
    origin = _normalize_label(origin_name)
    destination = _normalize_label(destination_name)
    terminals = {origin, destination}
    has_depot_keyword = any(
        keyword in origin or keyword in destination for keyword in _DEPOT_KEYWORDS
    )

    if origin and origin == destination:
        return ("loop", False, "origin and destination are identical")

    if route_code == "東98":
        if terminals == {"東京駅南口", "等々力操車所"}:
            return ("mainline", False, "東98 mainline override")
        if "目黒郵便局" in terminals:
            return (
                "depot_move",
                True,
                "東98 Meguro depot-related pattern via 目黒郵便局",
            )
        if "清水" in terminals:
            if "東京駅南口" in terminals:
                return (
                    "short_turn",
                    True,
                    "東98 daytime split pattern; 清水 endpoint remains depot-related for Meguro operations",
                )
            return (
                "depot_move",
                True,
                "東98 Meguro depot-related pattern via 清水",
            )
        if "等々力操車所" in terminals and terminals.intersection({"目黒駅前", "目黒駅東口", "目黒駅"}):
            return ("short_turn", False, "東98 daytime split pattern")

    if variant_type in {"main", "main_outbound", "main_inbound"}:
        return ("mainline", has_depot_keyword, "route-family main variant")
    if variant_type in {"short_turn", "branch"}:
        return ("short_turn", has_depot_keyword, "route-family short-turn/branch variant")
    if variant_type in {"depot_in", "depot_out"}:
        return ("depot_move", True, "route-family depot variant")
    if has_depot_keyword and stop_count < max_stop_count:
        return ("depot_move", True, "terminal contains depot-like keyword and pattern is shorter than mainline")
    if stop_count < max_stop_count:
        return ("short_turn", has_depot_keyword, "pattern is shorter than mainline")
    return ("unknown", has_depot_keyword, "no explicit pattern classification matched")


def _load_route_pattern_records(
    conn: sqlite3.Connection,
    *,
    depot_id: str | None = None,
    route_family: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            rp.pattern_id,
            rp.route_family,
            rp.route_code,
            rp.title_ja,
            rp.direction,
            rp.stop_count,
            origin_stop.lat AS origin_lat,
            origin_stop.lon AS origin_lon,
            dest_stop.lat AS destination_lat,
            dest_stop.lon AS destination_lon,
            COALESCE(origin_stop.title_ja, rp.origin_stop_id) AS origin_name,
            COALESCE(dest_stop.title_ja, rp.dest_stop_id) AS destination_name
        FROM route_patterns rp
        LEFT JOIN stops origin_stop ON origin_stop.stop_id = rp.origin_stop_id
        LEFT JOIN stops dest_stop ON dest_stop.stop_id = rp.dest_stop_id
        WHERE 1=1
    """
    params: list[Any] = []
    if depot_id:
        sql += """
            AND EXISTS (
                SELECT 1
                FROM route_pattern_depots rpd
                WHERE rpd.pattern_id = rp.pattern_id AND rpd.depot_id = ?
            )
        """
        params.append(depot_id)
    if route_family:
        sql += " AND rp.route_family = ?"
        params.append(route_family)
    sql += " ORDER BY rp.route_family, rp.pattern_id"
    rows = _query_dicts(conn, sql, params)
    pattern_ids = [str(row.get("pattern_id") or "") for row in rows if row.get("pattern_id")]
    stop_names = _load_pattern_stop_names(conn, pattern_ids)
    trip_counts = _load_pattern_trip_counts(conn, pattern_ids)
    route_records = [
        {
            "id": str(row.get("pattern_id") or ""),
            "name": str(row.get("title_ja") or row.get("route_code") or ""),
            "routeCode": str(row.get("route_code") or row.get("route_family") or ""),
            "routeLabel": str(row.get("title_ja") or row.get("route_code") or ""),
            "startStop": str(row.get("origin_name") or ""),
            "endStop": str(row.get("destination_name") or ""),
            "stopSequence": stop_names.get(str(row.get("pattern_id") or ""), []),
            "tripCount": sum(trip_counts.get(str(row.get("pattern_id") or ""), {}).values()),
            "distanceKm": _estimate_pattern_distance_km(row),
            "source": "local_sqlite",
        }
        for row in rows
    ]
    metadata = derive_route_family_metadata(route_records)
    max_stop_count_by_family: dict[str, int] = defaultdict(int)
    for row in rows:
        family = str(row.get("route_family") or "")
        max_stop_count_by_family[family] = max(
            max_stop_count_by_family.get(family, 0),
            _safe_int(row.get("stop_count"), 0),
        )

    enriched: list[dict[str, Any]] = []
    for row in rows:
        pattern_id = str(row.get("pattern_id") or "")
        route_code = str(row.get("route_code") or row.get("route_family") or "")
        family = str(row.get("route_family") or "")
        variant_type = metadata.get(pattern_id).route_variant_type if pattern_id in metadata else "unknown"
        pattern_type, is_depot_related, note = _pattern_type_from_variant(
            route_code=route_code,
            origin_name=str(row.get("origin_name") or ""),
            destination_name=str(row.get("destination_name") or ""),
            stop_count=_safe_int(row.get("stop_count"), 0),
            max_stop_count=max_stop_count_by_family.get(family, 0),
            variant_type=variant_type,
        )
        counts = trip_counts.get(pattern_id, {})
        enriched.append(
            {
                "patternId": pattern_id,
                "routeFamilyId": family,
                "routeCode": route_code,
                "titleJa": str(row.get("title_ja") or route_code),
                "direction": str(row.get("direction") or "unknown"),
                "origin": str(row.get("origin_name") or ""),
                "destination": str(row.get("destination_name") or ""),
                "stopCount": _safe_int(row.get("stop_count"), 0),
                "patternType": pattern_type,
                "routeVariantType": variant_type,
                "isDepotRelated": is_depot_related,
                "notes": note,
                "tripCountWeekday": _safe_int(counts.get("平日"), 0),
                "tripCountSaturday": _safe_int(counts.get("土曜"), 0),
                "tripCountSunday": _safe_int(counts.get("日曜・休日"), 0),
            }
        )
    return enriched


def list_depot_summaries(calendar_type: str = "平日") -> list[dict[str, Any]]:
    count_key = _calendar_count_key(calendar_type)
    summaries: list[dict[str, Any]] = []
    for depot in list_depots(operator_id=OPERATOR_ID):
        routes = list_depot_route_summaries(
            str(depot.get("depot_id") or ""),
            include_depot_moves=True,
        )
        summaries.append(
            {
                "depot_id": str(depot.get("depot_id") or ""),
                "name": str(depot.get("title_ja") or depot.get("depot_key") or ""),
                "lat": depot.get("lat"),
                "lon": depot.get("lon"),
                "route_count": len(routes),
                "trip_count": sum(_safe_int(route.get(count_key), 0) for route in routes),
            }
        )
    summaries.sort(key=lambda item: item["depot_id"])
    return summaries


def list_depot_route_summaries(
    depot_id: str,
    *,
    include_depot_moves: bool = False,
) -> list[dict[str, Any]]:
    normalized_depot_id = _normalize_depot_id(depot_id)
    if not normalized_depot_id:
        return []
    with get_conn() as conn:
        pattern_records = _load_route_pattern_records(conn, depot_id=normalized_depot_id)
        family_rows = {
            str(row.get("route_family") or ""): row
            for row in _query_dicts(
                conn,
                """
                SELECT route_family, route_code, title_ja
                FROM route_families
                WHERE route_family IN (
                    SELECT DISTINCT rp.route_family
                    FROM route_patterns rp
                    INNER JOIN route_pattern_depots rpd ON rpd.pattern_id = rp.pattern_id
                    WHERE rpd.depot_id = ?
                )
                """,
                (normalized_depot_id,),
            )
        }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in pattern_records:
        grouped[str(record.get("routeFamilyId") or "")].append(record)

    priority = {"mainline": 0, "short_turn": 1, "depot_move": 2, "loop": 3, "unknown": 4}
    summaries: list[dict[str, Any]] = []
    for family_id, patterns in grouped.items():
        type_counter = Counter()
        for item in patterns:
            type_counter[str(item.get("patternType") or "unknown")] += (
                _safe_int(item.get("tripCountWeekday"), 0)
                + _safe_int(item.get("tripCountSaturday"), 0)
                + _safe_int(item.get("tripCountSunday"), 0)
            )
        dominant_pattern_type = sorted(
            type_counter.items(),
            key=lambda pair: (priority.get(pair[0], 99), -pair[1], pair[0]),
        )[0][0] if type_counter else "unknown"
        if not include_depot_moves and dominant_pattern_type == "depot_move":
            continue
        family_row = family_rows.get(family_id, {})
        notes = sorted({str(item.get("notes") or "") for item in patterns if item.get("notes")})
        summaries.append(
            {
                "route_family_id": family_id,
                "route_code": str(family_row.get("route_code") or family_id),
                "display_name": str(family_row.get("title_ja") or family_id),
                "dominant_pattern_type": dominant_pattern_type,
                "pattern_summary": patterns,
                "tripCountWeekday": sum(_safe_int(item.get("tripCountWeekday"), 0) for item in patterns),
                "tripCountSaturday": sum(_safe_int(item.get("tripCountSaturday"), 0) for item in patterns),
                "tripCountSunday": sum(_safe_int(item.get("tripCountSunday"), 0) for item in patterns),
                "confirmed": True,
                "notes": " / ".join(notes),
            }
        )
    summaries.sort(key=lambda item: (item["route_code"], item["route_family_id"]))
    return summaries


def get_route_family_patterns(
    route_family: str,
    *,
    depot_id: str | None = None,
) -> list[dict[str, Any]]:
    normalized_depot_id = _normalize_depot_id(depot_id) if depot_id else None
    with get_conn() as conn:
        return _load_route_pattern_records(
            conn,
            depot_id=normalized_depot_id,
            route_family=route_family,
        )


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
            rp.depot_id AS primary_depot_id,
            origin_stop.title_ja AS origin_name,
            origin_stop.lat AS origin_lat,
            origin_stop.lon AS origin_lon,
            dest_stop.title_ja AS destination_name,
            dest_stop.lat AS destination_lat,
            dest_stop.lon AS destination_lon
        FROM timetable_trips t
        LEFT JOIN route_patterns rp ON t.pattern_id=rp.pattern_id
        LEFT JOIN stops origin_stop ON t.origin_stop_id=origin_stop.stop_id
        LEFT JOIN stops dest_stop ON t.dest_stop_id=dest_stop.stop_id
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
                "origin": str(item.get("origin_name") or item.get("origin_stop_id") or ""),
                "destination": str(item.get("destination_name") or item.get("dest_stop_id") or ""),
                "origin_lat": item.get("origin_lat"),
                "origin_lon": item.get("origin_lon"),
                "destination_lat": item.get("destination_lat"),
                "destination_lon": item.get("destination_lon"),
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
            SELECT ts.seq, ts.stop_id, s.title_ja, s.lat, s.lon,
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
            "origin_lat": item.get("origin_lat"),
            "origin_lon": item.get("origin_lon"),
            "destination_lat": item.get("destination_lat"),
            "destination_lon": item.get("destination_lon"),
            "departure_time": _minutes_to_hhmm(dep_min, fallback=str(item.get("departure_time") or "")),
            "arrival_time": _minutes_to_hhmm(arr_min, fallback=str(item.get("arrival_time") or "")),
            "dep_min": dep_min,
            "arr_min": arr_min,
            "duration_min": arr_min - dep_min,
            "stop_count": _safe_int(item.get("stop_count"), 0),
            "allowed_vehicle_types": list(DEFAULT_ALLOWED_VEHICLE_TYPES),
            "distance_km": _straight_line_distance_km(item),
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
