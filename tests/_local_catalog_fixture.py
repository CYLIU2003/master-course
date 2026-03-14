from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE operators (operator_id TEXT PRIMARY KEY, title_ja TEXT, title_en TEXT);
CREATE TABLE depots (
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
CREATE TABLE route_families (
    route_family TEXT,
    operator_id TEXT,
    route_code TEXT,
    title_ja TEXT,
    pattern_count INTEGER,
    depot_id TEXT,
    PRIMARY KEY(route_family, operator_id)
);
CREATE TABLE route_family_depots (
    route_family TEXT,
    operator_id TEXT,
    depot_id TEXT,
    source TEXT,
    PRIMARY KEY(route_family, operator_id, depot_id)
);
CREATE TABLE route_patterns (
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
CREATE TABLE route_pattern_depots (
    pattern_id TEXT,
    depot_id TEXT,
    source TEXT,
    PRIMARY KEY(pattern_id, depot_id)
);
CREATE TABLE pattern_stops (pattern_id TEXT, seq INTEGER, stop_id TEXT, UNIQUE(pattern_id, seq));
CREATE TABLE route_code_depots (route_code TEXT, depot_id TEXT, source TEXT, PRIMARY KEY(route_code, depot_id, source));
CREATE TABLE stops (stop_id TEXT PRIMARY KEY, operator_id TEXT, title_ja TEXT, title_kana TEXT, lat REAL, lon REAL, platform_num TEXT, raw_json TEXT);
CREATE TABLE timetable_trips (trip_id TEXT PRIMARY KEY, timetable_id TEXT, pattern_id TEXT, route_family TEXT, calendar_type TEXT, direction TEXT, origin_stop_id TEXT, dest_stop_id TEXT, departure_hhmm TEXT, arrival_hhmm TEXT, dep_min INTEGER, arr_min INTEGER, duration_min INTEGER, stop_count INTEGER, is_nonstop INTEGER);
CREATE TABLE trip_stops (id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT, seq INTEGER, stop_id TEXT, departure_hhmm TEXT, arrival_hhmm TEXT, dep_min INTEGER, arr_min INTEGER);
CREATE TABLE stop_timetables (id INTEGER PRIMARY KEY AUTOINCREMENT, stop_id TEXT, pattern_id TEXT, calendar_type TEXT, direction TEXT, departure_hhmm TEXT, dep_min INTEGER, note TEXT);
CREATE TABLE pipeline_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def create_local_catalog_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO operators VALUES (?, ?, ?)",
        [("odpt.Operator:TokyuBus", "東急バス", "Tokyu Bus")],
    )
    conn.executemany(
        """
        INSERT INTO depots
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("tokyu:depot:meguro", "odpt.Operator:TokyuBus", "meguro", "目黒営業所", "Meguro", "", "", "東京", "", "", 35.628292, 139.694458, "{}"),
            ("tokyu:depot:seta", "odpt.Operator:TokyuBus", "seta", "瀬田営業所", "Seta", "", "", "東京", "", "", 35.617458, 139.635818, "{}"),
            ("tokyu:depot:tsurumaki", "odpt.Operator:TokyuBus", "tsurumaki", "弦巻営業所", "Tsurumaki", "", "", "東京", "", "", 35.638203, 139.643631, "{}"),
            ("tokyu:depot:awashima", "odpt.Operator:TokyuBus", "awashima", "淡島営業所", "Awashima", "", "", "東京", "", "", 35.653526, 139.672928, "{}"),
        ],
    )
    conn.executemany(
        "INSERT INTO route_families VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("黒01", "odpt.Operator:TokyuBus", "黒01", "黒01", 1, "tokyu:depot:meguro"),
            ("園01", "odpt.Operator:TokyuBus", "園01", "園01", 1, "tokyu:depot:seta"),
            ("等01", "odpt.Operator:TokyuBus", "等01", "等01", 1, "tokyu:depot:seta"),
            ("渋11", "odpt.Operator:TokyuBus", "渋11", "渋11", 1, "tokyu:depot:awashima"),
        ],
    )
    conn.executemany(
        "INSERT INTO route_family_depots VALUES (?, ?, ?, ?)",
        [
            ("黒01", "odpt.Operator:TokyuBus", "tokyu:depot:meguro", "authority_csv"),
            ("園01", "odpt.Operator:TokyuBus", "tokyu:depot:seta", "authority_csv"),
            ("等01", "odpt.Operator:TokyuBus", "tokyu:depot:seta", "authority_csv"),
            ("等01", "odpt.Operator:TokyuBus", "tokyu:depot:tsurumaki", "authority_csv"),
            ("渋11", "odpt.Operator:TokyuBus", "tokyu:depot:awashima", "authority_csv"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO route_patterns
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("pattern:black", "odpt.Operator:TokyuBus", "黒01", "黒01", "黒01 outbound", "", "outbound", "", "tokyu:depot:meguro", "stop:A", "stop:B", 2, "{}"),
            ("pattern:garden", "odpt.Operator:TokyuBus", "園01", "園01", "園01 outbound", "", "outbound", "", "tokyu:depot:seta", "stop:C", "stop:D", 2, "{}"),
            ("pattern:shared", "odpt.Operator:TokyuBus", "等01", "等01", "等01 outbound", "", "outbound", "", "tokyu:depot:seta", "stop:E", "stop:F", 2, "{}"),
            ("pattern:awashima", "odpt.Operator:TokyuBus", "渋11", "渋11", "渋11 outbound", "", "outbound", "", "tokyu:depot:awashima", "stop:G", "stop:H", 2, "{}"),
        ],
    )
    conn.executemany(
        "INSERT INTO route_pattern_depots VALUES (?, ?, ?)",
        [
            ("pattern:black", "tokyu:depot:meguro", "authority_csv"),
            ("pattern:garden", "tokyu:depot:seta", "authority_csv"),
            ("pattern:shared", "tokyu:depot:seta", "authority_csv"),
            ("pattern:shared", "tokyu:depot:tsurumaki", "authority_csv"),
            ("pattern:awashima", "tokyu:depot:awashima", "authority_csv"),
        ],
    )
    conn.executemany(
        "INSERT INTO route_code_depots VALUES (?, ?, ?)",
        [
            ("黒01", "tokyu:depot:meguro", "authority_csv"),
            ("園01", "tokyu:depot:seta", "authority_csv"),
            ("等01", "tokyu:depot:seta", "authority_csv"),
            ("等01", "tokyu:depot:tsurumaki", "authority_csv"),
            ("渋11", "tokyu:depot:awashima", "authority_csv"),
        ],
    )
    conn.executemany(
        "INSERT INTO pattern_stops VALUES (?, ?, ?)",
        [
            ("pattern:black", 1, "stop:A"),
            ("pattern:black", 2, "stop:B"),
            ("pattern:garden", 1, "stop:C"),
            ("pattern:garden", 2, "stop:D"),
            ("pattern:shared", 1, "stop:E"),
            ("pattern:shared", 2, "stop:F"),
            ("pattern:awashima", 1, "stop:G"),
            ("pattern:awashima", 2, "stop:H"),
        ],
    )
    conn.executemany(
        "INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("stop:A", "odpt.Operator:TokyuBus", "A", "A", 35.628292, 139.694458, "1", "{}"),
            ("stop:B", "odpt.Operator:TokyuBus", "B", "B", 35.629292, 139.704458, "2", "{}"),
            ("stop:C", "odpt.Operator:TokyuBus", "C", "C", 35.617458, 139.635818, "1", "{}"),
            ("stop:D", "odpt.Operator:TokyuBus", "D", "D", 35.627458, 139.645818, "2", "{}"),
            ("stop:E", "odpt.Operator:TokyuBus", "E", "E", 35.638203, 139.643631, "1", "{}"),
            ("stop:F", "odpt.Operator:TokyuBus", "F", "F", 35.648203, 139.653631, "2", "{}"),
            ("stop:G", "odpt.Operator:TokyuBus", "G", "G", 35.653526, 139.672928, "1", "{}"),
            ("stop:H", "odpt.Operator:TokyuBus", "H", "H", 35.663526, 139.682928, "2", "{}"),
        ],
    )
    conn.executemany(
        "INSERT INTO timetable_trips VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("trip:black:001", "tt:black", "pattern:black", "黒01", "平日", "outbound", "stop:A", "stop:B", "06:00", "06:30", 360, 390, 30, 2, 0),
            ("trip:garden:001", "tt:garden", "pattern:garden", "園01", "平日", "outbound", "stop:C", "stop:D", "07:00", "07:45", 420, 465, 45, 2, 0),
            ("trip:garden:late", "tt:garden", "pattern:garden", "園01", "平日", "outbound", "stop:C", "stop:D", "23:50", "00:10", 1430, 10, 20, 2, 0),
            ("trip:shared:001", "tt:shared", "pattern:shared", "等01", "土曜", "outbound", "stop:E", "stop:F", "08:30", "09:00", 510, 540, 30, 2, 0),
            ("trip:awashima:001", "tt:awashima", "pattern:awashima", "渋11", "平日", "outbound", "stop:G", "stop:H", "10:00", "10:30", 600, 630, 30, 2, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO trip_stops (trip_id, seq, stop_id, departure_hhmm, arrival_hhmm, dep_min, arr_min) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("trip:black:001", 1, "stop:A", "06:00", "06:00", 360, 360),
            ("trip:black:001", 2, "stop:B", "06:30", "06:30", 390, 390),
            ("trip:garden:001", 1, "stop:C", "07:00", "07:00", 420, 420),
            ("trip:garden:001", 2, "stop:D", "07:45", "07:45", 465, 465),
            ("trip:shared:001", 1, "stop:E", "08:30", "08:30", 510, 510),
            ("trip:shared:001", 2, "stop:F", "09:00", "09:00", 540, 540),
        ],
    )
    conn.executemany(
        "INSERT INTO stop_timetables (stop_id, pattern_id, calendar_type, direction, departure_hhmm, dep_min, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("stop:A", "pattern:black", "平日", "outbound", "06:00", 360, ""),
            ("stop:C", "pattern:garden", "平日", "outbound", "07:00", 420, ""),
        ],
    )
    conn.executemany(
        "INSERT INTO pipeline_meta VALUES (?, ?)",
        [
            ("built_at", "2026-03-14T00:00:00Z"),
            ("source", "fixture"),
            ("build_mode", "subset"),
            ("selected_depots", "[\"meguro\",\"seta\",\"awashima\",\"tsurumaki\"]"),
        ],
    )
    conn.commit()
    conn.close()
    return path
