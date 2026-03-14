from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

from tests._local_catalog_fixture import create_local_catalog_db


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _make_minimal_seed_root(root: Path) -> Path:
    seed_root = root / "seed"
    _write_text(
        seed_root / "route_to_depot.csv",
        """
        route_code,depot_id,depot_name,region,route_map_as_of,notes
        黒01,meguro,目黒営業所,東京,2026-03-14,
        """,
    )
    (seed_root / "version.json").write_text(
        json.dumps({"dataset_version": "2026-03-14"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (seed_root / "datasets").mkdir(parents=True, exist_ok=True)
    (seed_root / "datasets" / "tokyu_core.json").write_text(
        json.dumps(
            {
                "dataset_id": "tokyu_core",
                "included_depots": ["meguro"],
                "included_routes": ["黒01"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return seed_root


def _make_minimal_gtfs_feed(root: Path) -> Path:
    feed_root = root / "TokyuBus-GTFS"
    _write_text(
        feed_root / "agency.txt",
        """
        agency_id,agency_name,agency_url,agency_timezone
        odpt.Operator:TokyuBus,Tokyu Bus,https://www.tokyubus.co.jp,Asia/Tokyo
        """,
    )
    _write_text(
        feed_root / "routes.txt",
        """
        route_id,agency_id,route_short_name,route_long_name,route_type,route_color
        raw-route-01,odpt.Operator:TokyuBus,黒０１,黒０１,3,112233
        """,
    )
    _write_text(
        feed_root / "stops.txt",
        """
        stop_id,stop_name,stop_lat,stop_lon
        stop-a,目黒駅,35.633,139.715
        stop-b,大岡山小学校前,35.610,139.685
        """,
    )
    _write_text(
        feed_root / "trips.txt",
        """
        route_id,service_id,trip_id,direction_id,shape_id,trip_headsign
        raw-route-01,weekday,trip-01,0,shape-01,大岡山小学校前
        """,
    )
    _write_text(
        feed_root / "stop_times.txt",
        """
        trip_id,arrival_time,departure_time,stop_id,stop_sequence
        trip-01,06:00:00,06:00:00,stop-a,1
        trip-01,06:25:00,06:25:00,stop-b,2
        """,
    )
    _write_text(
        feed_root / "calendar.txt",
        """
        service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date
        weekday,1,1,1,1,1,0,0,20260301,20260331
        """,
    )
    (feed_root / "feed_metadata.json").write_text(
        json.dumps(
            {
                "feed_id": "tokyu_odpt_gtfs",
                "snapshot_id": "unit-test",
                "generated_at": "2026-03-14T00:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return feed_root


def test_gtfs_backed_build_pipeline_creates_non_empty_artifacts(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    seed_root = _make_minimal_seed_root(tmp_path)
    feed_root = _make_minimal_gtfs_feed(tmp_path)
    built_dir = tmp_path / "built" / "tokyu_core"

    build_routes = _load_module(
        "build_routes_test_gtfs",
        repo_root / "data-prep" / "pipeline" / "build_routes.py",
    )
    build_trips = _load_module(
        "build_trips_test_gtfs",
        repo_root / "data-prep" / "pipeline" / "build_trips.py",
    )
    build_timetables = _load_module(
        "build_timetables_test_gtfs",
        repo_root / "data-prep" / "pipeline" / "build_timetables.py",
    )
    helper = _load_module(
        "gtfs_built_artifacts_test_helper",
        repo_root / "data-prep" / "pipeline" / "_gtfs_built_artifacts.py",
    )

    build_routes.build_routes("tokyu_core", built_dir, seed_root, feed_path=feed_root)
    build_trips.build_trips("tokyu_core", built_dir, seed_root, feed_path=feed_root)
    build_timetables.build_timetables("tokyu_core", built_dir, seed_root, feed_path=feed_root)
    helper.build_stops_artifact("tokyu_core", built_dir, seed_root, feed_path=feed_root)
    helper.build_stop_timetables_artifact("tokyu_core", built_dir, seed_root, feed_path=feed_root)

    routes = pd.read_parquet(built_dir / "routes.parquet")
    trips = pd.read_parquet(built_dir / "trips.parquet")
    timetables = pd.read_parquet(built_dir / "timetables.parquet")
    stops = pd.read_parquet(built_dir / "stops.parquet")
    stop_timetables = pd.read_parquet(built_dir / "stop_timetables.parquet")

    assert len(routes) == 1
    assert routes.iloc[0]["id"] == "tokyu:meguro:黒01"
    assert routes.iloc[0]["source"] == "gtfs_build"
    assert len(trips) == 1
    assert trips.iloc[0]["route_id"] == "tokyu:meguro:黒01"
    assert len(timetables) == 1
    assert timetables.iloc[0]["trip_id"] == trips.iloc[0]["trip_id"]
    assert len(stops) == 2
    assert set(stops["id"]) == {"stop-a", "stop-b"}
    assert len(stop_timetables) == 2
    stop_tt_items = list(stop_timetables.iloc[0]["items"])
    assert stop_tt_items[0]["busroutePattern"] == "tokyu:meguro:黒01"
    assert stop_tt_items[0]["busTimetable"] == trips.iloc[0]["trip_id"]


def test_export_sqlite_to_built_rejects_empty_catalog(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    script = _load_module(
        "export_tokyu_sqlite_to_built_test",
        repo_root / "scripts" / "export_tokyu_sqlite_to_built.py",
    )
    db_path = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE depots (depot_id TEXT PRIMARY KEY, lat REAL, lon REAL);
        CREATE TABLE route_families (route_family TEXT, operator_id TEXT, title_ja TEXT, pattern_count INTEGER, depot_id TEXT);
        CREATE TABLE route_patterns (pattern_id TEXT PRIMARY KEY, depot_id TEXT);
        CREATE TABLE timetable_trips (
            trip_id TEXT PRIMARY KEY,
            pattern_id TEXT,
            route_family TEXT,
            calendar_type TEXT,
            departure_hhmm TEXT,
            arrival_hhmm TEXT,
            origin_stop_id TEXT,
            dest_stop_id TEXT,
            dep_min INTEGER
        );
        CREATE TABLE stops (stop_id TEXT PRIMARY KEY, title_ja TEXT, lat REAL, lon REAL);
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="No route_families were found"):
        script.export_sqlite_to_built(
            db_path=db_path,
            dataset_id="tokyu_core",
            built_root=tmp_path / "built",
            depot_ids=["tokyu:depot:meguro"],
        )


def test_gtfs_reconciliation_report_exposes_missing_route_codes(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    seed_root = _make_minimal_seed_root(tmp_path)
    feed_root = _make_minimal_gtfs_feed(tmp_path)
    (seed_root / "route_to_depot.csv").write_text(
        (
            "route_code,depot_id,depot_name,region,route_map_as_of,notes\n"
            "黒01,meguro,目黒営業所,東京,2026-03-14,\n"
            "黒02,meguro,目黒営業所,東京,2026-03-14,\n"
        ),
        encoding="utf-8",
    )
    (seed_root / "datasets" / "tokyu_core.json").write_text(
        json.dumps(
            {
                "dataset_id": "tokyu_core",
                "included_depots": ["meguro"],
                "included_routes": "ALL",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    helper = _load_module(
        "gtfs_built_artifacts_test_gtfs",
        repo_root / "data-prep" / "pipeline" / "_gtfs_built_artifacts.py",
    )
    report_path = helper.build_gtfs_reconciliation_artifact(
        dataset_id="tokyu_core",
        built_dir=tmp_path / "built" / "tokyu_core",
        seed_root=seed_root,
        feed_path=feed_root,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["scoped"]["matched_route_codes"] == ["黒01"]
    assert report["scoped"]["missing_master_route_codes_in_gtfs"] == ["黒02"]

    with pytest.raises(RuntimeError, match="Missing route codes: 黒02"):
        helper.build_gtfs_reconciliation_artifact(
            dataset_id="tokyu_core",
            built_dir=tmp_path / "built" / "tokyu_core_strict",
            seed_root=seed_root,
            feed_path=feed_root,
            strict=True,
        )


def test_export_sqlite_to_built_uses_dataset_definition_when_depot_scope_is_omitted(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    script = _load_module(
        "export_tokyu_sqlite_to_built_dataset_scope_test",
        repo_root / "scripts" / "export_tokyu_sqlite_to_built.py",
    )
    seed_root = tmp_path / "seed"
    (seed_root / "datasets").mkdir(parents=True, exist_ok=True)
    (seed_root / "version.json").write_text(
        json.dumps({"dataset_version": "2026-03-14"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (seed_root / "datasets" / "tokyu_full.json").write_text(
        json.dumps(
            {
                "dataset_id": "tokyu_full",
                "included_depots": ["seta"],
                "included_routes": "ALL",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    script.SEED_ROOT = seed_root

    db_path = tmp_path / "catalog.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE depots (depot_id TEXT PRIMARY KEY, lat REAL, lon REAL);
        CREATE TABLE route_families (route_family TEXT, operator_id TEXT, title_ja TEXT, pattern_count INTEGER, depot_id TEXT);
        CREATE TABLE route_patterns (pattern_id TEXT PRIMARY KEY, depot_id TEXT);
        CREATE TABLE timetable_trips (
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
        CREATE TABLE stops (stop_id TEXT PRIMARY KEY, title_ja TEXT, lat REAL, lon REAL);
        """
    )
    conn.executemany(
        "INSERT INTO depots VALUES (?, ?, ?)",
        [
            ("tokyu:depot:meguro", 35.0, 139.0),
            ("tokyu:depot:seta", 35.1, 139.1),
        ],
    )
    conn.executemany(
        "INSERT INTO route_families VALUES (?, ?, ?, ?, ?)",
        [
            ("黒01", "odpt.Operator:TokyuBus", "黒01", 1, "tokyu:depot:meguro"),
            ("園01", "odpt.Operator:TokyuBus", "園01", 1, "tokyu:depot:seta"),
        ],
    )
    conn.executemany(
        "INSERT INTO route_patterns VALUES (?, ?)",
        [
            ("pattern:meguro", "tokyu:depot:meguro"),
            ("pattern:seta", "tokyu:depot:seta"),
        ],
    )
    conn.executemany(
        "INSERT INTO timetable_trips VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("trip:meguro", "tt:meguro", "pattern:meguro", "黒01", "平日", "outbound", "stop:a", "stop:b", "06:00", "06:20", 360, 380, 20, 2, 0),
            ("trip:seta", "tt:seta", "pattern:seta", "園01", "平日", "outbound", "stop:c", "stop:d", "07:00", "07:20", 420, 440, 20, 2, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO stops VALUES (?, ?, ?, ?)",
        [
            ("stop:a", "A", 35.0, 139.0),
            ("stop:b", "B", 35.01, 139.01),
            ("stop:c", "C", 35.1, 139.1),
            ("stop:d", "D", 35.11, 139.11),
        ],
    )
    conn.commit()
    conn.close()

    built_dir = script.export_sqlite_to_built(
        db_path=db_path,
        dataset_id="tokyu_full",
        built_root=tmp_path / "built",
        depot_ids=[],
    )

    routes = pd.read_parquet(built_dir / "routes.parquet")
    trips = pd.read_parquet(built_dir / "trips.parquet")
    assert list(routes["id"]) == ["tokyu:seta:園01"]
    assert list(trips["route_id"]) == ["tokyu:seta:園01"]


def test_export_sqlite_to_built_writes_optional_stop_artifacts(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    script = _load_module(
        "export_tokyu_sqlite_to_built_stop_artifacts_test",
        repo_root / "scripts" / "export_tokyu_sqlite_to_built.py",
    )
    db_path = create_local_catalog_db(tmp_path / "catalog.sqlite")

    built_dir = script.export_sqlite_to_built(
        db_path=db_path,
        dataset_id="tokyu_core",
        built_root=tmp_path / "built",
        depot_ids=["tokyu:depot:meguro"],
    )

    routes = pd.read_parquet(built_dir / "routes.parquet")
    trips = pd.read_parquet(built_dir / "trips.parquet")
    stops = pd.read_parquet(built_dir / "stops.parquet")
    stop_timetables = pd.read_parquet(built_dir / "stop_timetables.parquet")

    assert routes.iloc[0]["startStop"] == "A"
    assert list(routes.iloc[0]["stopSequence"]) == ["stop:A", "stop:B"]
    assert trips.iloc[0]["service_id"] == "WEEKDAY"
    assert set(stops["id"]) == {"stop:A", "stop:B"}
    assert stop_timetables.iloc[0]["service_id"] == "WEEKDAY"
