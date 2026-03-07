"""Per-operator SQLite master data stores.

This module manages **separate** SQLite databases for each transit operator:

  - ``data/odpt_tokyu.db``   (東急バス – ODPT source)
  - ``data/gtfs_toei.db``    (都営バス – GTFS source)

Tables are *normalised* and dispatch-ready: ``timetable_rows`` maps
directly to ``src.dispatch.models.Trip`` (times in ``"HH:MM"`` format,
stop-ids are consistent, ``allowed_vehicle_types`` as JSON array).

Design principles
-----------------
* Each DB is self-contained – it can be copied to another machine.
* Schema uses ``UNIQUE`` constraints to enforce dedup at insert time.
* The module is a *complement* to the existing ``transit_catalog.py``
  shared catalog; imports populate both stores.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPO_ROOT / "data"

# Operator registry ---------------------------------------------------------
OPERATORS: Dict[str, Dict[str, str]] = {
    "tokyu": {
        "operator_id": "tokyu",
        "name_ja": "東急バス",
        "name_en": "Tokyu Bus",
        "source": "odpt",
        "db_filename": "odpt_tokyu.db",
        "odpt_operator": "odpt.Operator:TokyuBus",
    },
    "toei": {
        "operator_id": "toei",
        "name_ja": "都営バス",
        "name_en": "Toei Bus",
        "source": "gtfs",
        "db_filename": "gtfs_toei.db",
        "gtfs_feed_path": "GTFS/ToeiBus-GTFS",
    },
}

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS routes (
    route_id          TEXT PRIMARY KEY,
    route_code        TEXT,
    route_name        TEXT NOT NULL,
    source            TEXT NOT NULL,
    direction         TEXT,
    origin_stop_id    TEXT,
    destination_stop_id TEXT,
    stop_count        INTEGER DEFAULT 0,
    trip_count        INTEGER DEFAULT 0,
    distance_km       REAL,
    first_departure   TEXT,
    last_arrival      TEXT,
    stop_sequence_json TEXT,
    geometry_json     TEXT,
    extra_json        TEXT
);

CREATE TABLE IF NOT EXISTS stops (
    stop_id     TEXT PRIMARY KEY,
    stop_name   TEXT NOT NULL,
    stop_name_en TEXT,
    lat         REAL,
    lon         REAL,
    kind        TEXT DEFAULT 'real_stop',
    source      TEXT NOT NULL,
    extra_json  TEXT
);

CREATE TABLE IF NOT EXISTS timetable_rows (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id               TEXT NOT NULL,
    route_id              TEXT NOT NULL,
    service_id            TEXT NOT NULL,
    direction             TEXT,
    trip_index            INTEGER,
    origin                TEXT NOT NULL,
    destination           TEXT NOT NULL,
    departure             TEXT NOT NULL,
    arrival               TEXT NOT NULL,
    distance_km           REAL DEFAULT 0.0,
    allowed_vehicle_types TEXT DEFAULT '["BEV","ICE"]',
    source                TEXT NOT NULL,
    UNIQUE(trip_id, service_id)
);

CREATE TABLE IF NOT EXISTS stop_timetables (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    stop_id              TEXT NOT NULL,
    route_id             TEXT,
    service_id           TEXT NOT NULL,
    direction            TEXT,
    time                 TEXT NOT NULL,
    destination_display  TEXT,
    trip_id              TEXT,
    source               TEXT NOT NULL,
    UNIQUE(stop_id, route_id, service_id, direction, time)
);

CREATE TABLE IF NOT EXISTS calendar (
    service_id    TEXT PRIMARY KEY,
    service_name  TEXT NOT NULL,
    monday        INTEGER DEFAULT 0,
    tuesday       INTEGER DEFAULT 0,
    wednesday     INTEGER DEFAULT 0,
    thursday      INTEGER DEFAULT 0,
    friday        INTEGER DEFAULT 0,
    saturday      INTEGER DEFAULT 0,
    sunday        INTEGER DEFAULT 0,
    start_date    TEXT,
    end_date      TEXT
);

CREATE TABLE IF NOT EXISTS calendar_dates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id      TEXT NOT NULL,
    date            TEXT NOT NULL,
    exception_type  INTEGER NOT NULL,
    UNIQUE(service_id, date)
);

-- Indexes for dispatch-critical queries
CREATE INDEX IF NOT EXISTS idx_tt_service   ON timetable_rows(service_id);
CREATE INDEX IF NOT EXISTS idx_tt_route     ON timetable_rows(route_id);
CREATE INDEX IF NOT EXISTS idx_tt_departure ON timetable_rows(departure);
CREATE INDEX IF NOT EXISTS idx_st_stop      ON stop_timetables(stop_id);
CREATE INDEX IF NOT EXISTS idx_st_service   ON stop_timetables(service_id);
"""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _db_path(operator_id: str) -> Path:
    """Return the database file path for the given operator."""
    info = OPERATORS.get(operator_id)
    if info is None:
        raise ValueError(f"Unknown operator_id: {operator_id!r}")
    env_key = f"TRANSIT_DB_{operator_id.upper()}"
    configured = os.environ.get(env_key)
    if configured:
        p = Path(configured)
        return p if p.is_absolute() else (_REPO_ROOT / p).resolve()
    return _DATA_DIR / info["db_filename"]


def _connect(operator_id: str) -> sqlite3.Connection:
    """Open (and optionally create) the database for *operator_id*."""
    path = _db_path(operator_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def ensure_schema(operator_id: str) -> None:
    """Create tables / indexes if they do not yet exist."""
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def set_metadata(operator_id: str, key: str, value: str) -> None:
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            """INSERT INTO metadata (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, _now_iso()),
        )
        conn.commit()


def get_metadata(operator_id: str, key: str) -> Optional[str]:
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def get_all_metadata(operator_id: str) -> Dict[str, str]:
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        rows = conn.execute("SELECT key, value, updated_at FROM metadata").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------------
# Bulk write (replace-all for an import session)
# ---------------------------------------------------------------------------

def replace_all(
    operator_id: str,
    *,
    routes: Sequence[Dict[str, Any]] = (),
    stops: Sequence[Dict[str, Any]] = (),
    timetable_rows: Sequence[Dict[str, Any]] = (),
    stop_timetables: Sequence[Dict[str, Any]] = (),
    calendar_entries: Sequence[Dict[str, Any]] = (),
    calendar_date_entries: Sequence[Dict[str, Any]] = (),
    meta: Optional[Dict[str, str]] = None,
) -> Dict[str, int]:
    """Drop-and-replace all data for the operator in a single transaction.

    Returns a dict of counts per table.
    """
    info = OPERATORS.get(operator_id)
    if info is None:
        raise ValueError(f"Unknown operator_id: {operator_id!r}")
    source = info["source"]

    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)

        # Clear existing data
        conn.execute("DELETE FROM stop_timetables")
        conn.execute("DELETE FROM timetable_rows")
        conn.execute("DELETE FROM calendar_dates")
        conn.execute("DELETE FROM calendar")
        conn.execute("DELETE FROM routes")
        conn.execute("DELETE FROM stops")

        # Insert stops -------------------------------------------------------
        seen_stop_ids: set[str] = set()
        stop_rows: list[tuple] = []
        for s in stops:
            sid = str(s.get("id") or s.get("stop_id") or "")
            if not sid or sid in seen_stop_ids:
                continue
            seen_stop_ids.add(sid)
            stop_rows.append((
                sid,
                str(s.get("name") or s.get("stop_name") or sid),
                s.get("name_en") or s.get("stop_name_en"),
                s.get("lat") or s.get("latitude"),
                s.get("lon") or s.get("lng") or s.get("longitude"),
                s.get("kind", "real_stop"),
                source,
                _json_dumps({k: v for k, v in s.items()
                             if k not in {"id", "stop_id", "name", "stop_name",
                                          "name_en", "stop_name_en",
                                          "lat", "latitude", "lon", "lng", "longitude",
                                          "kind"}}) if True else None,
            ))
        conn.executemany(
            "INSERT OR IGNORE INTO stops (stop_id, stop_name, stop_name_en, lat, lon, kind, source, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            stop_rows,
        )

        # Insert routes -------------------------------------------------------
        seen_route_ids: set[str] = set()
        route_rows: list[tuple] = []
        for r in routes:
            rid = str(r.get("id") or r.get("route_id") or "")
            if not rid or rid in seen_route_ids:
                continue
            seen_route_ids.add(rid)
            # Extract stop sequence if available
            directions = r.get("directions") or []
            stop_seq = None
            if directions:
                first_dir = directions[0] if isinstance(directions, list) else None
                if first_dir and isinstance(first_dir, dict):
                    stops_list = first_dir.get("stops") or first_dir.get("stop_sequence") or []
                    if stops_list:
                        stop_seq = _json_dumps([
                            s.get("stopId") or s.get("stop_id") or s
                            for s in stops_list
                            if s
                        ])
            route_rows.append((
                rid,
                str(r.get("routeCode") or r.get("route_code") or rid),
                str(r.get("name") or r.get("route_name") or rid),
                source,
                r.get("direction"),
                r.get("origin_stop_id"),
                r.get("destination_stop_id"),
                r.get("stop_count") or r.get("stopCount") or 0,
                r.get("trip_count") or r.get("tripCount") or 0,
                r.get("distance_km") or r.get("distanceKm"),
                r.get("first_departure") or r.get("firstDeparture"),
                r.get("last_arrival") or r.get("lastArrival"),
                stop_seq,
                r.get("geometry_json"),
                _json_dumps({k: v for k, v in r.items()
                             if k not in {"id", "route_id", "routeCode", "route_code",
                                          "name", "route_name", "direction",
                                          "origin_stop_id", "destination_stop_id",
                                          "stop_count", "stopCount",
                                          "trip_count", "tripCount",
                                          "distance_km", "distanceKm",
                                          "first_departure", "firstDeparture",
                                          "last_arrival", "lastArrival",
                                          "stop_sequence_json",
                                          "geometry_json", "directions"}}) if True else None,
            ))
        conn.executemany(
            "INSERT OR IGNORE INTO routes "
            "(route_id, route_code, route_name, source, direction, "
            " origin_stop_id, destination_stop_id, stop_count, trip_count, "
            " distance_km, first_departure, last_arrival, "
            " stop_sequence_json, geometry_json, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            route_rows,
        )

        # Insert timetable rows ------------------------------------------------
        seen_trips: set[str] = set()
        tt_rows: list[tuple] = []
        for idx, t in enumerate(timetable_rows):
            trip_id = str(t.get("trip_id") or f"{t.get('route_id','?')}_{t.get('direction','?')}_{t.get('departure','?')}_{idx}")
            service_id = str(t.get("service_id") or "WEEKDAY")
            dedup_key = f"{trip_id}|{service_id}"
            if dedup_key in seen_trips:
                continue
            seen_trips.add(dedup_key)

            # Normalize allowed_vehicle_types
            avt = t.get("allowed_vehicle_types")
            if avt is None:
                avt_json = '["BEV","ICE"]'
            elif isinstance(avt, str):
                avt_json = avt
            else:
                avt_json = _json_dumps(list(avt))

            tt_rows.append((
                trip_id,
                str(t.get("route_id") or ""),
                service_id,
                t.get("direction"),
                t.get("trip_index") if t.get("trip_index") is not None else idx,
                str(t.get("origin") or t.get("from_stop_id") or ""),
                str(t.get("destination") or t.get("to_stop_id") or ""),
                str(t.get("departure") or ""),
                str(t.get("arrival") or ""),
                float(t.get("distance_km") or 0.0),
                avt_json,
                source,
            ))
        conn.executemany(
            "INSERT OR IGNORE INTO timetable_rows "
            "(trip_id, route_id, service_id, direction, trip_index, "
            " origin, destination, departure, arrival, distance_km, "
            " allowed_vehicle_types, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            tt_rows,
        )

        # Insert stop timetables -----------------------------------------------
        st_rows: list[tuple] = []
        seen_st: set[str] = set()
        for st in stop_timetables:
            stop_id = str(st.get("stopId") or st.get("stop_id") or "")
            if not stop_id:
                continue
            entries = st.get("entries") or []
            svc_id = str(st.get("service_id") or "WEEKDAY")
            for entry in entries:
                time_val = str(entry.get("time") or "")
                route_id = str(entry.get("routeId") or entry.get("route_id") or "")
                direction = entry.get("direction") or ""
                dedup = f"{stop_id}|{route_id}|{svc_id}|{direction}|{time_val}"
                if dedup in seen_st:
                    continue
                seen_st.add(dedup)
                st_rows.append((
                    stop_id,
                    route_id or None,
                    svc_id,
                    direction or None,
                    time_val,
                    entry.get("destinationDisplay") or entry.get("destination_display"),
                    entry.get("tripId") or entry.get("trip_id"),
                    source,
                ))
        conn.executemany(
            "INSERT OR IGNORE INTO stop_timetables "
            "(stop_id, route_id, service_id, direction, time, "
            " destination_display, trip_id, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            st_rows,
        )

        # Insert calendar -------------------------------------------------------
        for cal in calendar_entries:
            sid = str(cal.get("service_id") or "")
            if not sid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO calendar "
                "(service_id, service_name, monday, tuesday, wednesday, "
                " thursday, friday, saturday, sunday, start_date, end_date) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    str(cal.get("service_name") or cal.get("name") or sid),
                    int(cal.get("monday") or 0),
                    int(cal.get("tuesday") or 0),
                    int(cal.get("wednesday") or 0),
                    int(cal.get("thursday") or 0),
                    int(cal.get("friday") or 0),
                    int(cal.get("saturday") or 0),
                    int(cal.get("sunday") or 0),
                    cal.get("start_date") or cal.get("startDate"),
                    cal.get("end_date") or cal.get("endDate"),
                ),
            )

        # Insert calendar dates --------------------------------------------------
        for cd in calendar_date_entries:
            sid = str(cd.get("service_id") or "")
            dt = str(cd.get("date") or "")
            if not sid or not dt:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO calendar_dates (service_id, date, exception_type) "
                "VALUES (?,?,?)",
                (sid, dt, int(cd.get("exception_type") or 1)),
            )

        # Write metadata ---------------------------------------------------------
        now = _now_iso()
        meta_entries = {
            "operator_id": operator_id,
            "operator_name": info["name_ja"],
            "source": source,
            "last_import_at": now,
            "route_count": str(len(route_rows)),
            "stop_count": str(len(stop_rows)),
            "timetable_row_count": str(len(tt_rows)),
            "stop_timetable_entry_count": str(len(st_rows)),
            "calendar_count": str(len(calendar_entries)),
            "calendar_date_count": str(len(calendar_date_entries)),
        }
        if meta:
            meta_entries.update(meta)
        for k, v in meta_entries.items():
            conn.execute(
                "INSERT INTO metadata (key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (k, str(v), now),
            )

        conn.commit()

    counts = {
        "routes": len(route_rows),
        "stops": len(stop_rows),
        "timetable_rows": len(tt_rows),
        "stop_timetable_entries": len(st_rows),
        "calendar": len(calendar_entries),
        "calendar_dates": len(calendar_date_entries),
    }
    logger.info(
        "transit_db replace_all [%s]: routes=%d stops=%d tt_rows=%d st_entries=%d",
        operator_id, counts["routes"], counts["stops"],
        counts["timetable_rows"], counts["stop_timetable_entries"],
    )
    return counts


# ---------------------------------------------------------------------------
# Query helpers (dispatch-oriented)
# ---------------------------------------------------------------------------

def get_db_info(operator_id: str) -> Dict[str, Any]:
    """Return summary information about the operator database."""
    info = OPERATORS.get(operator_id)
    if info is None:
        raise ValueError(f"Unknown operator_id: {operator_id!r}")
    path = _db_path(operator_id)
    if not path.exists():
        return {
            "operator_id": operator_id,
            "operator_name": info["name_ja"],
            "source": info["source"],
            "db_path": str(path),
            "exists": False,
            "tables": {},
        }
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        tables: Dict[str, int] = {}
        for tbl in ("routes", "stops", "timetable_rows", "stop_timetables", "calendar", "calendar_dates"):
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {tbl}").fetchone()
            tables[tbl] = int(row["n"])
        meta = {}
        for row in conn.execute("SELECT key, value FROM metadata").fetchall():
            meta[row["key"]] = row["value"]
    return {
        "operator_id": operator_id,
        "operator_name": info["name_ja"],
        "source": info["source"],
        "db_path": str(path.relative_to(_REPO_ROOT)),
        "exists": True,
        "tables": tables,
        "metadata": meta,
    }


def list_routes(operator_id: str) -> List[Dict[str, Any]]:
    """Return all routes for an operator (lightweight summary)."""
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        rows = conn.execute(
            "SELECT route_id, route_code, route_name, direction, "
            "       stop_count, trip_count, distance_km, "
            "       first_departure, last_arrival, source "
            "FROM routes ORDER BY route_code ASC, route_name ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_stops(operator_id: str) -> List[Dict[str, Any]]:
    """Return all stops for an operator."""
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        rows = conn.execute(
            "SELECT stop_id, stop_name, stop_name_en, lat, lon, kind, source "
            "FROM stops ORDER BY stop_name ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_timetable_rows(
    operator_id: str,
    *,
    service_id: Optional[str] = None,
    route_id: Optional[str] = None,
    limit: int = 5000,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return timetable rows (dispatch-ready Trip candidates).

    Each row is directly convertible to ``src.dispatch.models.Trip``:
      - ``departure`` / ``arrival`` in ``"HH:MM"`` format
      - ``origin`` / ``destination`` as stop_id strings
      - ``allowed_vehicle_types`` as a JSON array string
    """
    clauses: list[str] = []
    params: list[Any] = []
    if service_id:
        clauses.append("service_id = ?")
        params.append(service_id)
    if route_id:
        clauses.append("route_id = ?")
        params.append(route_id)
    where = " AND ".join(clauses) if clauses else "1=1"
    params.extend([limit, offset])

    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        rows = conn.execute(
            f"SELECT trip_id, route_id, service_id, direction, trip_index, "
            f"       origin, destination, departure, arrival, distance_km, "
            f"       allowed_vehicle_types, source "
            f"FROM timetable_rows "
            f"WHERE {where} "
            f"ORDER BY departure ASC, route_id ASC, trip_index ASC "
            f"LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # Parse allowed_vehicle_types from JSON string
        avt = d.get("allowed_vehicle_types")
        if isinstance(avt, str):
            try:
                d["allowed_vehicle_types"] = json.loads(avt)
            except (json.JSONDecodeError, TypeError):
                d["allowed_vehicle_types"] = ["BEV", "ICE"]
        result.append(d)
    return result


def count_timetable_rows(
    operator_id: str,
    *,
    service_id: Optional[str] = None,
    route_id: Optional[str] = None,
) -> int:
    """Count timetable rows with optional filters."""
    clauses: list[str] = []
    params: list[Any] = []
    if service_id:
        clauses.append("service_id = ?")
        params.append(service_id)
    if route_id:
        clauses.append("route_id = ?")
        params.append(route_id)
    where = " AND ".join(clauses) if clauses else "1=1"
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM timetable_rows WHERE {where}", params
        ).fetchone()
    return int(row["n"])


def timetable_summary(operator_id: str) -> Dict[str, Any]:
    """Return aggregated timetable statistics per service_id."""
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        rows = conn.execute(
            "SELECT service_id, COUNT(*) AS trip_count, "
            "       COUNT(DISTINCT route_id) AS route_count, "
            "       MIN(departure) AS earliest_departure, "
            "       MAX(arrival) AS latest_arrival "
            "FROM timetable_rows "
            "GROUP BY service_id "
            "ORDER BY service_id ASC"
        ).fetchall()
    return {
        "by_service": [dict(r) for r in rows],
        "total": sum(r["trip_count"] for r in rows),
    }


def list_stop_timetables(
    operator_id: str,
    stop_id: str,
    *,
    service_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return stop timetable entries for a given stop."""
    clauses = ["stop_id = ?"]
    params: list[Any] = [stop_id]
    if service_id:
        clauses.append("service_id = ?")
        params.append(service_id)
    where = " AND ".join(clauses)
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        rows = conn.execute(
            f"SELECT stop_id, route_id, service_id, direction, time, "
            f"       destination_display, trip_id, source "
            f"FROM stop_timetables WHERE {where} "
            f"ORDER BY time ASC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def list_calendar(operator_id: str) -> List[Dict[str, Any]]:
    """Return calendar definitions."""
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        rows = conn.execute(
            "SELECT service_id, service_name, monday, tuesday, wednesday, "
            "       thursday, friday, saturday, sunday, start_date, end_date "
            "FROM calendar ORDER BY service_id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_calendar_dates(operator_id: str) -> List[Dict[str, Any]]:
    """Return calendar date exceptions."""
    with _connect(operator_id) as conn:
        conn.executescript(_SCHEMA_SQL)
        rows = conn.execute(
            "SELECT service_id, date, exception_type "
            "FROM calendar_dates ORDER BY date ASC, service_id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Dispatch-ready extraction
# ---------------------------------------------------------------------------

def extract_dispatch_trips(
    operator_id: str,
    service_id: str,
) -> List[Dict[str, Any]]:
    """Extract trips for one service-day, ready for ``DispatchContext``.

    Returns dicts with the exact keys expected by
    ``src.dispatch.models.Trip``:
      trip_id, route_id, origin, destination,
      departure_time ("HH:MM"), arrival_time ("HH:MM"),
      distance_km, allowed_vehicle_types (tuple of str).
    """
    rows = list_timetable_rows(operator_id, service_id=service_id, limit=100_000)
    trips: list[Dict[str, Any]] = []
    for r in rows:
        avt = r.get("allowed_vehicle_types")
        if isinstance(avt, list):
            avt_tuple = tuple(avt)
        elif isinstance(avt, str):
            try:
                avt_tuple = tuple(json.loads(avt))
            except Exception:
                avt_tuple = ("BEV", "ICE")
        else:
            avt_tuple = ("BEV", "ICE")

        trips.append({
            "trip_id": r["trip_id"],
            "route_id": r["route_id"],
            "origin": r["origin"],
            "destination": r["destination"],
            "departure_time": r["departure"],
            "arrival_time": r["arrival"],
            "distance_km": float(r.get("distance_km") or 0.0),
            "allowed_vehicle_types": avt_tuple,
        })
    return trips


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def list_operator_ids() -> List[str]:
    """Return all registered operator IDs."""
    return list(OPERATORS.keys())


def list_operators() -> List[Dict[str, Any]]:
    """Return all operators with DB status."""
    results = []
    for op_id in OPERATORS:
        try:
            info = get_db_info(op_id)
        except Exception:
            info = {"operator_id": op_id, "exists": False, "error": True}
        results.append(info)
    return results


def db_exists(operator_id: str) -> bool:
    """Check if the operator database file exists."""
    return _db_path(operator_id).exists()


def table_schema(operator_id: str) -> List[Dict[str, Any]]:
    """Return the schema of all tables in the operator database."""
    if not db_exists(operator_id):
        return []
    with _connect(operator_id) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        result = []
        for t in tables:
            tname = t["name"]
            cols = conn.execute(f"PRAGMA table_info({tname})").fetchall()
            result.append({
                "table": tname,
                "columns": [
                    {"name": c["name"], "type": c["type"], "notnull": bool(c["notnull"]), "pk": bool(c["pk"])}
                    for c in cols
                ],
            })
    return result
