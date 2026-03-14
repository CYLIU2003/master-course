from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "_stop_timetable_fallback.py"
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import importlib.util

    spec = importlib.util.spec_from_file_location("stop_timetable_fallback_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE timetable_trips (
            trip_id TEXT PRIMARY KEY,
            pattern_id TEXT,
            calendar_type TEXT,
            direction TEXT
        );
        CREATE TABLE trip_stops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT,
            seq INTEGER,
            stop_id TEXT,
            departure_hhmm TEXT,
            arrival_hhmm TEXT,
            dep_min INTEGER,
            arr_min INTEGER
        );
        CREATE TABLE stop_timetables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stop_id TEXT,
            pattern_id TEXT,
            calendar_type TEXT,
            direction TEXT,
            departure_hhmm TEXT,
            dep_min INTEGER,
            note TEXT
        );
        """
    )
    return conn


def test_synthesize_missing_stop_timetables_from_trip_stops():
    module = _load_module()
    conn = _make_conn()
    conn.execute(
        "INSERT INTO timetable_trips VALUES (?, ?, ?, ?)",
        ("trip-01", "pattern-01", "平日", "outbound"),
    )
    conn.executemany(
        "INSERT INTO trip_stops (trip_id, seq, stop_id, departure_hhmm, arrival_hhmm, dep_min, arr_min) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("trip-01", 1, "stop-a", "06:00", "06:00", 360, 360),
            ("trip-01", 2, "stop-b", "06:20", "06:20", 380, 380),
        ],
    )

    summary = module.synthesize_missing_stop_timetables(conn, pattern_ids=["pattern-01"])

    assert summary == {"patterns": 1, "entries": 2}
    rows = conn.execute(
        "SELECT stop_id, note FROM stop_timetables ORDER BY stop_id"
    ).fetchall()
    assert rows == [
        ("stop-a", module.SYNTHETIC_STOP_TIMETABLE_NOTE),
        ("stop-b", module.SYNTHETIC_STOP_TIMETABLE_NOTE),
    ]


def test_synthesize_missing_stop_timetables_skips_patterns_with_actual_rows():
    module = _load_module()
    conn = _make_conn()
    conn.execute(
        "INSERT INTO timetable_trips VALUES (?, ?, ?, ?)",
        ("trip-01", "pattern-01", "平日", "outbound"),
    )
    conn.execute(
        "INSERT INTO stop_timetables (stop_id, pattern_id, calendar_type, direction, departure_hhmm, dep_min, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("stop-a", "pattern-01", "平日", "outbound", "06:00", 360, "actual"),
    )

    summary = module.synthesize_missing_stop_timetables(conn, pattern_ids=["pattern-01"])

    assert summary == {"patterns": 0, "entries": 0}
    assert conn.execute("SELECT COUNT(*) FROM stop_timetables").fetchone()[0] == 1
