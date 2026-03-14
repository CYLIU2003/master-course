from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _make_seed_root(root: Path) -> Path:
    seed_root = root / "seed"
    _write_text(
        seed_root / "route_to_depot.csv",
        """
        route_code,depot_id,depot_name,region,route_map_as_of,notes
        黒01,meguro,目黒営業所,東京,2026-03-14,
        """,
    )
    (seed_root / "depots.json").write_text(
        json.dumps(
            {
                "depots": [
                    {
                        "depotId": "meguro",
                        "name": "目黒営業所",
                        "nameEn": "Meguro",
                        "region": "東京",
                        "lat": 35.628292,
                        "lon": 139.694458,
                    }
                ]
            },
            ensure_ascii=False,
        ),
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


def _make_gtfs_feed(root: Path) -> Path:
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


def test_build_tokyu_gtfs_db_creates_local_catalog(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    script = _load_module(
        "build_tokyu_gtfs_db_test",
        repo_root / "scripts" / "build_tokyu_gtfs_db.py",
    )
    seed_root = _make_seed_root(tmp_path)
    feed_root = _make_gtfs_feed(tmp_path)
    db_path = tmp_path / "tokyu_gtfs.sqlite"

    script.build_tokyu_gtfs_db(
        db_path,
        dataset_id="tokyu_core",
        feed_path=feed_root,
        seed_root=seed_root,
    )

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM route_families").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM route_patterns").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM timetable_trips").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM trip_stops").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM stop_timetables").fetchone()[0] == 2
    assert conn.execute("SELECT depot_id FROM route_families").fetchone()[0] == "tokyu:depot:meguro"
    conn.close()
