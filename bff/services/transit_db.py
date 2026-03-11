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
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bff.services.runtime_paths import resolve_runtime_path
from bff.services.service_ids import canonical_service_id
from src.feed_identity import (
    TOEI_GTFS_FEED_ID,
    TOKYU_ODPT_GTFS_FEED_ID,
    build_dataset_id,
    infer_feed_id,
)

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
    feed_id           TEXT,
    snapshot_id       TEXT,
    dataset_id        TEXT,
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
    feed_id     TEXT,
    snapshot_id TEXT,
    dataset_id  TEXT,
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
    feed_id               TEXT,
    snapshot_id           TEXT,
    dataset_id            TEXT,
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
    extra_json            TEXT,
    UNIQUE(trip_id, service_id)
);

CREATE TABLE IF NOT EXISTS stop_timetables (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    stop_id              TEXT NOT NULL,
    feed_id              TEXT,
    snapshot_id          TEXT,
    dataset_id           TEXT,
    route_id             TEXT,
    service_id           TEXT NOT NULL,
    direction            TEXT,
    time                 TEXT NOT NULL,
    destination_display  TEXT,
    trip_id              TEXT,
    source               TEXT NOT NULL,
    extra_json           TEXT,
    UNIQUE(stop_id, route_id, service_id, direction, time)
);

CREATE TABLE IF NOT EXISTS trip_stop_times (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id     TEXT NOT NULL,
    feed_id     TEXT,
    snapshot_id TEXT,
    dataset_id  TEXT,
    stop_id     TEXT NOT NULL,
    stop_name   TEXT,
    sequence    INTEGER NOT NULL,
    departure   TEXT,
    arrival     TEXT,
    source      TEXT NOT NULL,
    extra_json  TEXT,
    UNIQUE(trip_id, sequence)
);

CREATE TABLE IF NOT EXISTS stop_timetable_entries (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timetable_id         TEXT NOT NULL,
    feed_id              TEXT,
    snapshot_id          TEXT,
    dataset_id           TEXT,
    stop_id              TEXT NOT NULL,
    stop_name            TEXT,
    service_id           TEXT NOT NULL,
    calendar             TEXT,
    entry_index          INTEGER NOT NULL,
    departure            TEXT,
    arrival              TEXT,
    destination_stop_id  TEXT,
    destination_display  TEXT,
    route_id             TEXT,
    trip_id              TEXT,
    note                 TEXT,
    source               TEXT NOT NULL,
    extra_json           TEXT,
    UNIQUE(timetable_id, entry_index)
);

CREATE TABLE IF NOT EXISTS calendar (
    service_id    TEXT PRIMARY KEY,
    feed_id       TEXT,
    snapshot_id   TEXT,
    dataset_id    TEXT,
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
    feed_id         TEXT,
    snapshot_id     TEXT,
    dataset_id      TEXT,
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
CREATE INDEX IF NOT EXISTS idx_trip_stop_times_trip_seq ON trip_stop_times(trip_id, sequence);
CREATE INDEX IF NOT EXISTS idx_stop_tt_entries_stop_service_time
    ON stop_timetable_entries(stop_id, service_id, departure);
CREATE INDEX IF NOT EXISTS idx_stop_tt_entries_trip ON stop_timetable_entries(trip_id);
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
    return resolve_runtime_path(f"transit_db_{operator_id}", _DATA_DIR / info["db_filename"])


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
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_exception_type(value: Any) -> int:
    if value is None:
        return 1
    if isinstance(value, int):
        if value in (1, 2):
            return value
        raise ValueError(f"Unsupported exception_type int: {value!r}")

    normalized = str(value).strip().upper()
    if normalized in {"1", "ADD", "ADDED", "SERVICE_ADDED"}:
        return 1
    if normalized in {"2", "REMOVE", "REMOVED", "SERVICE_REMOVED"}:
        return 2
    raise ValueError(f"Unsupported calendar_dates.exception_type: {value!r}")


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_migrations(conn: sqlite3.Connection) -> None:
    if "extra_json" not in _column_names(conn, "timetable_rows"):
        conn.execute("ALTER TABLE timetable_rows ADD COLUMN extra_json TEXT")
    if "extra_json" not in _column_names(conn, "stop_timetables"):
        conn.execute("ALTER TABLE stop_timetables ADD COLUMN extra_json TEXT")
    for table_name in (
        "routes",
        "stops",
        "timetable_rows",
        "stop_timetables",
        "trip_stop_times",
        "stop_timetable_entries",
        "calendar",
        "calendar_dates",
    ):
        columns = _column_names(conn, table_name)
        if "feed_id" not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN feed_id TEXT")
        if "snapshot_id" not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN snapshot_id TEXT")
        if "dataset_id" not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN dataset_id TEXT")


def _ensure_ready(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    _ensure_migrations(conn)


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def set_metadata(operator_id: str, key: str, value: str) -> None:
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        conn.execute(
            """INSERT INTO metadata (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, _now_iso()),
        )
        conn.commit()


def get_metadata(operator_id: str, key: str) -> Optional[str]:
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def get_all_metadata(operator_id: str) -> Dict[str, str]:
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
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
    trip_stop_times: Sequence[Dict[str, Any]] = (),
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
    meta = dict(meta or {})
    default_feed_id = (
        TOKYU_ODPT_GTFS_FEED_ID if operator_id == "tokyu" else TOEI_GTFS_FEED_ID
    )
    feed_id = str(
        meta.get("feed_id")
        or infer_feed_id(meta.get("feed_path") or meta.get("gtfs_feed_path") or "")
        or default_feed_id
    )
    snapshot_id = str(meta.get("snapshot_id") or "").strip() or None
    dataset_id = str(meta.get("dataset_id") or "").strip() or build_dataset_id(
        feed_id, snapshot_id
    )

    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)

        # Clear existing data
        conn.execute("DELETE FROM stop_timetable_entries")
        conn.execute("DELETE FROM trip_stop_times")
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
                feed_id,
                snapshot_id,
                dataset_id,
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
            "INSERT OR IGNORE INTO stops (stop_id, feed_id, snapshot_id, dataset_id, stop_name, stop_name_en, lat, lon, kind, source, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
            if r.get("stopSequence"):
                stop_seq = _json_dumps(list(r.get("stopSequence") or []))
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
                feed_id,
                snapshot_id,
                dataset_id,
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
            "(route_id, feed_id, snapshot_id, dataset_id, route_code, route_name, source, direction, "
            " origin_stop_id, destination_stop_id, stop_count, trip_count, "
            " distance_km, first_departure, last_arrival, "
            " stop_sequence_json, geometry_json, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            route_rows,
        )

        # Insert timetable rows ------------------------------------------------
        seen_trips: set[str] = set()
        tt_rows: list[tuple] = []
        for idx, t in enumerate(timetable_rows):
            trip_id = str(t.get("trip_id") or f"{t.get('route_id','?')}_{t.get('direction','?')}_{t.get('departure','?')}_{idx}")
            service_id = canonical_service_id(t.get("service_id"))
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
                feed_id,
                snapshot_id,
                dataset_id,
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
                _json_dumps({k: v for k, v in t.items() if k not in {
                    "trip_id", "route_id", "service_id", "direction", "trip_index",
                    "origin", "destination", "departure", "arrival", "distance_km",
                    "allowed_vehicle_types", "source",
                }}),
            ))
        conn.executemany(
            "INSERT OR IGNORE INTO timetable_rows "
            "(trip_id, feed_id, snapshot_id, dataset_id, route_id, service_id, direction, trip_index, "
            " origin, destination, departure, arrival, distance_km, "
            " allowed_vehicle_types, source, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tt_rows,
        )

        # Insert trip stop times -----------------------------------------------
        trip_stop_rows: list[tuple] = []
        seen_trip_stops: set[str] = set()
        for stop_time in trip_stop_times:
            trip_id = str(stop_time.get("trip_id") or "")
            sequence = int(stop_time.get("sequence") or stop_time.get("index") or 0)
            stop_id = str(stop_time.get("stop_id") or stop_time.get("stopId") or "")
            if not trip_id or not stop_id:
                continue
            dedup_key = f"{trip_id}|{sequence}"
            if dedup_key in seen_trip_stops:
                continue
            seen_trip_stops.add(dedup_key)
            trip_stop_rows.append(
                (
                    trip_id,
                    feed_id,
                    snapshot_id,
                    dataset_id,
                    stop_id,
                    str(stop_time.get("stop_name") or stop_time.get("stopName") or ""),
                    sequence,
                    stop_time.get("departure"),
                    stop_time.get("arrival"),
                    str(stop_time.get("source") or source),
                    _json_dumps(
                        {
                            k: v
                            for k, v in stop_time.items()
                            if k
                            not in {
                                "trip_id",
                                "stop_id",
                                "stopId",
                                "stop_name",
                                "stopName",
                                "sequence",
                                "index",
                                "departure",
                                "arrival",
                                "source",
                            }
                        }
                    ),
                )
            )
        conn.executemany(
            "INSERT OR IGNORE INTO trip_stop_times "
            "(trip_id, feed_id, snapshot_id, dataset_id, stop_id, stop_name, sequence, departure, arrival, source, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            trip_stop_rows,
        )

        # Insert stop timetables -----------------------------------------------
        st_rows: list[tuple] = []
        st_entry_rows: list[tuple] = []
        seen_st: set[str] = set()
        seen_st_entries: set[str] = set()
        for st in stop_timetables:
            timetable_id = str(st.get("id") or "")
            stop_id = str(st.get("stopId") or st.get("stop_id") or "")
            if not stop_id:
                continue
            entries = st.get("items") or st.get("entries") or []
            svc_id = canonical_service_id(st.get("service_id"))
            stop_name = str(st.get("stopName") or "")
            calendar = st.get("calendar")
            for entry_index, entry in enumerate(entries):
                departure = entry.get("departure") or entry.get("time")
                arrival = entry.get("arrival")
                time_val = str(departure or arrival or "")
                route_id = str(
                    entry.get("routeId")
                    or entry.get("route_id")
                    or entry.get("busroute")
                    or ""
                )
                direction = entry.get("direction") or ""
                dedup = f"{stop_id}|{route_id}|{svc_id}|{direction}|{time_val}"
                if dedup in seen_st:
                    continue
                seen_st.add(dedup)
                st_rows.append((
                    stop_id,
                    feed_id,
                    snapshot_id,
                    dataset_id,
                    route_id or None,
                    svc_id,
                    direction or None,
                    time_val,
                    entry.get("destinationDisplay")
                    or entry.get("destination_display")
                    or entry.get("destination"),
                    entry.get("tripId") or entry.get("trip_id") or entry.get("busTimetable"),
                    source,
                    _json_dumps(entry),
                ))
                entry_dedup = f"{timetable_id}|{entry_index}"
                if timetable_id and entry_dedup not in seen_st_entries:
                    seen_st_entries.add(entry_dedup)
                    st_entry_rows.append(
                        (
                            timetable_id,
                            feed_id,
                            snapshot_id,
                            dataset_id,
                            stop_id,
                            stop_name,
                            svc_id,
                            calendar,
                            entry_index,
                            departure,
                            arrival,
                            entry.get("destination_stop_id") or entry.get("destination"),
                            entry.get("destinationDisplay")
                            or entry.get("destination_display")
                            or entry.get("destination"),
                            route_id or None,
                            entry.get("tripId")
                            or entry.get("trip_id")
                            or entry.get("busTimetable"),
                            entry.get("note"),
                            source,
                            _json_dumps(entry),
                        )
                    )
        conn.executemany(
            "INSERT OR IGNORE INTO stop_timetables "
            "(stop_id, feed_id, snapshot_id, dataset_id, route_id, service_id, direction, time, "
            " destination_display, trip_id, source, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            st_rows,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO stop_timetable_entries "
            "(timetable_id, feed_id, snapshot_id, dataset_id, stop_id, stop_name, service_id, calendar, entry_index, "
            " departure, arrival, destination_stop_id, destination_display, route_id, "
            " trip_id, note, source, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            st_entry_rows,
        )

        # Insert calendar -------------------------------------------------------
        for cal in calendar_entries:
            sid = str(cal.get("service_id") or "")
            if not sid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO calendar "
                "(service_id, feed_id, snapshot_id, dataset_id, service_name, monday, tuesday, wednesday, "
                " thursday, friday, saturday, sunday, start_date, end_date) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    feed_id,
                    snapshot_id,
                    dataset_id,
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
                "INSERT OR IGNORE INTO calendar_dates (service_id, feed_id, snapshot_id, dataset_id, date, exception_type) "
                "VALUES (?,?,?,?,?,?)",
                (
                    sid,
                    feed_id,
                    snapshot_id,
                    dataset_id,
                    dt,
                    _normalize_exception_type(cd.get("exception_type")),
                ),
            )

        # Write metadata ---------------------------------------------------------
        now = _now_iso()
        meta_entries = {
            "operator_id": operator_id,
            "operator_name": info["name_ja"],
            "source": source,
            "feed_id": feed_id,
            "snapshot_id": snapshot_id or "",
            "dataset_id": dataset_id,
            "last_import_at": now,
            "route_count": str(len(route_rows)),
            "stop_count": str(len(stop_rows)),
            "timetable_row_count": str(len(tt_rows)),
            "stop_timetable_entry_count": str(len(st_rows)),
            "trip_stop_time_count": str(len(trip_stop_rows)),
            "stop_timetable_detail_count": str(len(st_entry_rows)),
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
        "trip_stop_times": len(trip_stop_rows),
        "stop_timetable_details": len(st_entry_rows),
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
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        tables: Dict[str, int] = {}
        for tbl in (
            "routes",
            "stops",
            "timetable_rows",
            "trip_stop_times",
            "stop_timetables",
            "stop_timetable_entries",
            "calendar",
            "calendar_dates",
        ):
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


def list_routes(
    operator_id: str,
    *,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return paginated route summaries for an operator."""
    clauses = ["1=1"]
    params: list[Any] = []
    if q:
        like = f"%{q.strip()}%"
        clauses.append("(route_id LIKE ? OR route_code LIKE ? OR route_name LIKE ?)")
        params.extend([like, like, like])
    params.extend([limit, offset])
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        rows = conn.execute(
            "SELECT route_id, feed_id, snapshot_id, dataset_id, route_code, route_name, direction, "
            "       stop_count, trip_count, distance_km, "
            "       first_departure, last_arrival, source "
            f"FROM routes WHERE {' AND '.join(clauses)} "
            "ORDER BY route_code ASC, route_name ASC "
            "LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def count_routes(operator_id: str, *, q: Optional[str] = None) -> int:
    clauses = ["1=1"]
    params: list[Any] = []
    if q:
        like = f"%{q.strip()}%"
        clauses.append("(route_id LIKE ? OR route_code LIKE ? OR route_name LIKE ?)")
        params.extend([like, like, like])
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM routes WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
    return int(row["n"])


def get_route(operator_id: str, route_id: str) -> Optional[Dict[str, Any]]:
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        row = conn.execute(
            "SELECT route_id, feed_id, snapshot_id, dataset_id, route_code, route_name, source, direction, "
            "       origin_stop_id, destination_stop_id, stop_count, trip_count, "
            "       distance_km, first_departure, last_arrival, stop_sequence_json, "
            "       geometry_json, extra_json "
            "FROM routes WHERE route_id = ?",
            (route_id,),
        ).fetchone()
    if row is None:
        return None
    payload = dict(row)
    for key in ("stop_sequence_json", "geometry_json", "extra_json"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            try:
                payload[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return payload


def list_stops(
    operator_id: str,
    *,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return paginated stops for an operator."""
    clauses = ["1=1"]
    params: list[Any] = []
    if q:
        like = f"%{q.strip()}%"
        clauses.append("(stop_id LIKE ? OR stop_name LIKE ? OR stop_name_en LIKE ?)")
        params.extend([like, like, like])
    params.extend([limit, offset])
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        rows = conn.execute(
            "SELECT stop_id, feed_id, snapshot_id, dataset_id, stop_name, stop_name_en, lat, lon, kind, source "
            f"FROM stops WHERE {' AND '.join(clauses)} "
            "ORDER BY stop_name ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def count_stops(operator_id: str, *, q: Optional[str] = None) -> int:
    clauses = ["1=1"]
    params: list[Any] = []
    if q:
        like = f"%{q.strip()}%"
        clauses.append("(stop_id LIKE ? OR stop_name LIKE ? OR stop_name_en LIKE ?)")
        params.extend([like, like, like])
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM stops WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
    return int(row["n"])


def count_depot_candidates(operator_id: str) -> int:
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM stops "
            "WHERE (stop_name LIKE '%営業所%' OR stop_name LIKE '%車庫%' OR stop_name LIKE '%操車所%') "
            "AND lat IS NOT NULL AND lon IS NOT NULL"
        ).fetchone()
    return int(row["n"] or 0)


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

    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        rows = conn.execute(
            f"SELECT trip_id, feed_id, snapshot_id, dataset_id, route_id, service_id, direction, trip_index, "
            f"       origin, destination, departure, arrival, distance_km, "
            f"       allowed_vehicle_types, source, extra_json "
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
        if isinstance(d.get("extra_json"), str) and d["extra_json"]:
            try:
                d["extra_json"] = json.loads(d["extra_json"])
            except json.JSONDecodeError:
                pass
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
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM timetable_rows WHERE {where}", params
        ).fetchone()
    return int(row["n"])


def timetable_summary(
    operator_id: str,
    *,
    route_id: Optional[str] = None,
    service_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return aggregated timetable statistics per service_id."""
    clauses: list[str] = []
    params: list[Any] = []
    if route_id:
        clauses.append("route_id = ?")
        params.append(route_id)
    if service_id:
        clauses.append("service_id = ?")
        params.append(service_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        rows = conn.execute(
            "SELECT service_id, COUNT(*) AS trip_count, "
            "       COUNT(DISTINCT route_id) AS route_count, "
            "       MIN(departure) AS earliest_departure, "
            "       MAX(arrival) AS latest_arrival "
            "FROM timetable_rows "
            f"{where} "
            "GROUP BY service_id "
            "ORDER BY service_id ASC",
            params,
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
    limit: int = 500,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return detailed stop timetable entries for a given stop."""
    clauses = ["stop_id = ?"]
    params: list[Any] = [stop_id]
    if service_id:
        clauses.append("service_id = ?")
        params.append(service_id)
    params.extend([limit, offset])
    where = " AND ".join(clauses)
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        rows = conn.execute(
            f"SELECT timetable_id, feed_id, snapshot_id, dataset_id, stop_id, stop_name, service_id, calendar, entry_index, "
            f"       departure, arrival, destination_stop_id, destination_display, "
            f"       route_id, trip_id, note, source, extra_json "
            f"FROM stop_timetable_entries WHERE {where} "
            f"ORDER BY departure ASC, arrival ASC, entry_index ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if isinstance(item.get("extra_json"), str) and item["extra_json"]:
            try:
                item["extra_json"] = json.loads(item["extra_json"])
            except json.JSONDecodeError:
                pass
        result.append(item)
    return result


def count_stop_timetable_entries(
    operator_id: str,
    stop_id: str,
    *,
    service_id: Optional[str] = None,
) -> int:
    clauses = ["stop_id = ?"]
    params: list[Any] = [stop_id]
    if service_id:
        clauses.append("service_id = ?")
        params.append(service_id)
    where = " AND ".join(clauses)
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM stop_timetable_entries WHERE {where}",
            params,
        ).fetchone()
    return int(row["n"])


def list_trip_stop_times(operator_id: str, trip_id: str) -> List[Dict[str, Any]]:
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        rows = conn.execute(
            "SELECT trip_id, feed_id, snapshot_id, dataset_id, stop_id, stop_name, sequence, departure, arrival, source, extra_json "
            "FROM trip_stop_times WHERE trip_id = ? ORDER BY sequence ASC",
            (trip_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if isinstance(item.get("extra_json"), str) and item["extra_json"]:
            try:
                item["extra_json"] = json.loads(item["extra_json"])
            except json.JSONDecodeError:
                pass
        result.append(item)
    return result


def list_calendar(operator_id: str) -> List[Dict[str, Any]]:
    """Return calendar definitions."""
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        rows = conn.execute(
            "SELECT service_id, feed_id, snapshot_id, dataset_id, service_name, monday, tuesday, wednesday, "
            "       thursday, friday, saturday, sunday, start_date, end_date "
            "FROM calendar ORDER BY service_id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_calendar_dates(operator_id: str) -> List[Dict[str, Any]]:
    """Return calendar date exceptions."""
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
        rows = conn.execute(
            "SELECT service_id, feed_id, snapshot_id, dataset_id, date, exception_type "
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
    with closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)
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
