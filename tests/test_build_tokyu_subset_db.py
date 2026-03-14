from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


def _load_builder_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "build_tokyu_subset_db.py"
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("build_tokyu_subset_db_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_subset_builder_writes_selected_depots_and_timetable_trips(tmp_path, monkeypatch):
    module = _load_builder_module()
    assert module.ODPT_BASE.endswith("/api/v4")

    master_path = tmp_path / "tokyu_bus_depots_master.json"
    master_path.write_text(
        """
        {
          "depots": [
            {
              "depot_id": "meguro",
              "name": "目黒営業所",
              "address": "",
              "phone": "",
              "region": "東京",
              "route_map_pdf": "",
              "route_map_as_of": "2025-12-01",
              "route_codes": ["黒01"]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    csv_path = tmp_path / "tokyu_bus_route_to_depot.csv"
    csv_path.write_text(
        "route_code,depot_id,depot_name,region,route_map_as_of,notes\n黒01,meguro,目黒営業所,東京,2025-12-01,\n",
        encoding="utf-8",
    )

    patterns = [
        {
            "owl:sameAs": "pattern:black",
            "dc:title": "黒０１",
            "odpt:direction": "outbound",
            "odpt:busstopPoleOrder": [
                {"odpt:index": 1, "odpt:busstopPole": "stop:A"},
                {"odpt:index": 2, "odpt:busstopPole": "stop:B"},
            ],
        }
    ]
    timetables = [
        {
            "owl:sameAs": "tt:black",
            "odpt:busroutePattern": "pattern:black",
            "odpt:calendar": "平日",
            "odpt:direction": "outbound",
            "odpt:busTimetableObject": [
                {"odpt:busstopPole": "stop:A", "odpt:departureTime": "06:00", "odpt:arrivalTime": "06:00"},
                {"odpt:busstopPole": "stop:B", "odpt:departureTime": "06:30", "odpt:arrivalTime": "06:30"},
            ],
        }
    ]
    stops = [
        {"owl:sameAs": "stop:A", "dc:title": "A", "odpt:kana": "A", "geo:lat": 0.0, "geo:long": 0.0},
        {"owl:sameAs": "stop:B", "dc:title": "B", "odpt:kana": "B", "geo:lat": 0.0, "geo:long": 0.0},
    ]

    def fake_fetch(resource, params, api_key, use_cache=True):
        del api_key, use_cache
        if resource == "odpt:BusroutePattern":
            return patterns
        if resource == "odpt:BusTimetable":
            assert params["odpt:busroutePattern"] == "pattern:black"
            return timetables
        if resource == "odpt:BusstopPole":
            return stops
        if resource == "odpt:BusstopPoleTimetable":
            return []
        raise AssertionError(f"unexpected resource: {resource}")

    monkeypatch.setattr(module, "DEPOT_MASTER_CANDIDATES", (master_path,))
    monkeypatch.setattr(module, "ROUTE_TO_DEPOT_CANDIDATES", (csv_path,))
    monkeypatch.setattr(module, "odpt_fetch", fake_fetch)

    out_path = tmp_path / "tokyu_subset.sqlite"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_tokyu_subset_db.py",
            "--api-key",
            "dummy",
            "--depots",
            "meguro",
            "--skip-stop-timetables",
            "--out",
            str(out_path),
        ],
    )

    module.main()

    conn = sqlite3.connect(out_path)
    assert conn.execute("SELECT COUNT(*) FROM depots").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM route_patterns").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM timetable_trips").fetchone()[0] == 1
    meta = dict(conn.execute("SELECT key, value FROM pipeline_meta").fetchall())
    assert meta["build_mode"] == "subset"
    assert "meguro" in meta["selected_depots"]
    conn.close()


def test_subset_builder_accepts_env_backed_key_when_flag_is_omitted(tmp_path, monkeypatch):
    module = _load_builder_module()

    master_path = tmp_path / "tokyu_bus_depots_master.json"
    master_path.write_text(
        """
        {
          "depots": [
            {
              "depot_id": "meguro",
              "name": "目黒営業所",
              "address": "",
              "phone": "",
              "region": "東京",
              "route_map_pdf": "",
              "route_map_as_of": "2025-12-01",
              "route_codes": ["黒01"]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    csv_path = tmp_path / "tokyu_bus_route_to_depot.csv"
    csv_path.write_text(
        "route_code,depot_id,depot_name,region,route_map_as_of,notes\n黒01,meguro,目黒営業所,東京,2025-12-01,\n",
        encoding="utf-8",
    )

    patterns = [
        {
            "owl:sameAs": "pattern:black",
            "dc:title": "黒０１",
            "odpt:direction": "outbound",
            "odpt:busstopPoleOrder": [
                {"odpt:index": 1, "odpt:busstopPole": "stop:A"},
                {"odpt:index": 2, "odpt:busstopPole": "stop:B"},
            ],
        }
    ]

    def fake_fetch(resource, params, api_key, use_cache=True):
        del params, use_cache
        assert api_key == "env-key"
        if resource == "odpt:BusroutePattern":
            return patterns
        if resource == "odpt:BusTimetable":
            return []
        if resource == "odpt:BusstopPole":
            return []
        if resource == "odpt:BusstopPoleTimetable":
            return []
        raise AssertionError(f"unexpected resource: {resource}")

    monkeypatch.setattr(module, "DEPOT_MASTER_CANDIDATES", (master_path,))
    monkeypatch.setattr(module, "ROUTE_TO_DEPOT_CANDIDATES", (csv_path,))
    monkeypatch.setattr(module, "odpt_fetch", fake_fetch)
    monkeypatch.setattr(module, "resolve_odpt_api_key", lambda explicit_key: "env-key")

    out_path = tmp_path / "tokyu_subset.sqlite"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_tokyu_subset_db.py",
            "--depots",
            "meguro",
            "--skip-stop-timetables",
            "--out",
            str(out_path),
        ],
    )

    module.main()

    conn = sqlite3.connect(out_path)
    assert conn.execute("SELECT COUNT(*) FROM route_patterns").fetchone()[0] == 1
    conn.close()


def test_subset_builder_synthesizes_stop_timetables_when_odpt_is_empty(tmp_path, monkeypatch):
    module = _load_builder_module()

    master_path = tmp_path / "tokyu_bus_depots_master.json"
    master_path.write_text(
        """
        {
          "depots": [
            {
              "depot_id": "meguro",
              "name": "目黒営業所",
              "address": "",
              "phone": "",
              "region": "東京",
              "route_map_pdf": "",
              "route_map_as_of": "2025-12-01",
              "route_codes": ["黒01"]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    csv_path = tmp_path / "tokyu_bus_route_to_depot.csv"
    csv_path.write_text(
        "route_code,depot_id,depot_name,region,route_map_as_of,notes\n黒01,meguro,目黒営業所,東京,2025-12-01,\n",
        encoding="utf-8",
    )

    patterns = [
        {
            "owl:sameAs": "pattern:black",
            "dc:title": "黒０１",
            "odpt:direction": "outbound",
            "odpt:busstopPoleOrder": [
                {"odpt:index": 1, "odpt:busstopPole": "stop:A"},
                {"odpt:index": 2, "odpt:busstopPole": "stop:B"},
            ],
        }
    ]
    timetables = [
        {
            "owl:sameAs": "tt:black",
            "odpt:busroutePattern": "pattern:black",
            "odpt:calendar": "平日",
            "odpt:direction": "outbound",
            "odpt:busTimetableObject": [
                {"odpt:busstopPole": "stop:A", "odpt:departureTime": "06:00", "odpt:arrivalTime": "06:00"},
                {"odpt:busstopPole": "stop:B", "odpt:departureTime": "06:30", "odpt:arrivalTime": "06:30"},
            ],
        }
    ]
    stops = [
        {"owl:sameAs": "stop:A", "dc:title": "A", "odpt:kana": "A", "geo:lat": 0.0, "geo:long": 0.0},
        {"owl:sameAs": "stop:B", "dc:title": "B", "odpt:kana": "B", "geo:lat": 0.0, "geo:long": 0.0},
    ]

    def fake_fetch(resource, params, api_key, use_cache=True):
        del api_key, use_cache
        if resource == "odpt:BusroutePattern":
            return patterns
        if resource == "odpt:BusTimetable":
            assert params["odpt:busroutePattern"] == "pattern:black"
            return timetables
        if resource == "odpt:BusstopPole":
            return stops
        if resource == "odpt:BusstopPoleTimetable":
            return []
        raise AssertionError(f"unexpected resource: {resource}")

    monkeypatch.setattr(module, "DEPOT_MASTER_CANDIDATES", (master_path,))
    monkeypatch.setattr(module, "ROUTE_TO_DEPOT_CANDIDATES", (csv_path,))
    monkeypatch.setattr(module, "odpt_fetch", fake_fetch)

    out_path = tmp_path / "tokyu_subset.sqlite"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_tokyu_subset_db.py",
            "--api-key",
            "dummy",
            "--depots",
            "meguro",
            "--out",
            str(out_path),
        ],
    )

    module.main()

    conn = sqlite3.connect(out_path)
    assert conn.execute("SELECT COUNT(*) FROM stop_timetables").fetchone()[0] == 2
    meta = dict(conn.execute("SELECT key, value FROM pipeline_meta").fetchall())
    assert meta["synthetic_stop_timetable_entries"] == "2"
    assert meta["synthetic_stop_timetable_patterns"] == "1"
    conn.close()
