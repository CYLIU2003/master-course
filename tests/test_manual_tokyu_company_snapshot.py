"""A frozen Go capture must be complete before the offline catalog can exist."""

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from scripts.catalog import manual_tokyu_company_snapshot as snapshot


PATTERN = "odpt.BusroutePattern:TokyuBus.Shibu24.test"
ROUTE = "odpt.Busroute:TokyuBus.Shibu24"
STOP_A = "odpt.BusstopPole:TokyuBus.A"
STOP_B = "odpt.BusstopPole:TokyuBus.B"


def _fixture(output: Path) -> None:
    datasets = [
        (snapshot.RESOURCES[0], [{
            "owl:sameAs": PATTERN, "odpt:operator": snapshot.OPERATOR,
            "odpt:busroute": ROUTE, "dc:title": "渋24",
            "odpt:busstopPoleOrder": [
                {"odpt:index": 1, "odpt:busstopPole": STOP_A},
                {"odpt:index": 2, "odpt:busstopPole": STOP_B},
            ],
        }], {}),
        (snapshot.RESOURCES[1], [
            {"owl:sameAs": STOP_A, "odpt:operator": [snapshot.OPERATOR], "dc:title": "A", "geo:lat": 35.0, "geo:long": 139.0,
             "odpt:busstopPoleTimetable": ["odpt.BusstopPoleTimetable:TokyuBus.test"]},
            {"owl:sameAs": STOP_B, "odpt:operator": [snapshot.OPERATOR], "dc:title": "B", "geo:lat": 35.1, "geo:long": 139.1},
        ], {}),
        (snapshot.RESOURCES[2], [{
            "owl:sameAs": "odpt.BusTimetable:TokyuBus.test", "odpt:operator": snapshot.OPERATOR,
            "odpt:busroutePattern": PATTERN, "odpt:calendar": "odpt.Calendar:Weekday",
            "odpt:busTimetableObject": [
                {"odpt:busstopPole": STOP_A, "odpt:departureTime": "10:00"},
                {"odpt:busstopPole": STOP_B, "odpt:arrivalTime": "10:20"},
            ],
        }], {"odpt:busroutePattern": PATTERN}),
        (snapshot.RESOURCES[3], [{
            "owl:sameAs": "odpt.BusstopPoleTimetable:TokyuBus.test", "odpt:operator": snapshot.OPERATOR,
            "odpt:busroute": [ROUTE], "odpt:busstopPole": STOP_A,
            "odpt:busDirection": ["odpt.BusDirection:TokyuBus.A", "odpt.BusDirection:TokyuBus.B"],
            "odpt:calendar": "odpt.Calendar:Weekday",
            "odpt:busstopPoleTimetableObject": [{"odpt:departureTime": "10:00"}],
        }], {"odpt:busstopPole": STOP_A}),
        (snapshot.RESOURCES[3], [], {"odpt:busstopPole": STOP_B}),
    ]
    sources = []
    for index, (resource, rows, partition) in enumerate(datasets):
        path = output / f"resource_{index}.json"
        raw = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        path.write_bytes(raw)
        sources.append({
            "resource": resource, "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(), "record_count": len(rows),
            "request": {"endpoint": f"https://api.odpt.org/api/v4/{resource}",
                        "query": {"odpt:operator": snapshot.OPERATOR, **partition}},
        })
        if index in (2, 3):
            sources.append({
                **sources[-1],
                "request": {"endpoint": f"https://api.odpt.org/api/v4/{resource}",
                            "query": {"odpt:operator": snapshot.OPERATOR}},
            })
    (output / snapshot.MANIFEST).write_text(json.dumps({
        "schema_version": "tokyu_company_odpt_capture_v1", "operator_id": snapshot.OPERATOR,
        "captured_at_utc": "2026-09-24T06:56:33Z",
        "status": "CAPTURED_NOT_BUILT", "sources": sources,
        "pattern_count": 1, "route_count": 1, "stop_partition_count": 2,
        "timetable_object_count": 1, "stop_timetable_object_count": 1,
    }), encoding="utf-8")


def test_offline_build_keeps_exact_odpt_route_and_stop_timetable_source(tmp_path):
    _fixture(tmp_path)
    result = snapshot.build(tmp_path)
    assert result["counts"]["route_patterns"] == 1
    assert result["counts"]["timetable_trips"] == 1
    assert result["counts"]["stop_timetables"] == 1
    assert result["trip_stop_ids_absent_from_stop_master"] == 0
    assert (tmp_path / snapshot.DATABASE).is_file()
    assert (tmp_path / snapshot.BUILD_MANIFEST).is_file()
    with sqlite3.connect(tmp_path / snapshot.DATABASE) as connection:
        legacy_direction, directions_json = connection.execute(
            "SELECT direction, bus_directions_json FROM stop_timetables"
        ).fetchone()
    assert legacy_direction == ""
    assert json.loads(directions_json) == ["odpt.BusDirection:TokyuBus.A", "odpt.BusDirection:TokyuBus.B"]
    with pytest.raises(FileExistsError, match="immutable"):
        snapshot.build(tmp_path)


def test_bad_raw_sha_cannot_build_a_database(tmp_path):
    _fixture(tmp_path)
    (tmp_path / "resource_2.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA mismatch"):
        snapshot.build(tmp_path)
    assert not (tmp_path / snapshot.DATABASE).exists()


def test_export_shibu24_capture_links_only_frozen_relevant_sources(tmp_path):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    _fixture(frozen)
    snapshot.build(frozen)
    result = snapshot.export_shibu24_capture(frozen, tmp_path / "route24")
    manifest = json.loads((tmp_path / "route24/shibu24_capture_manifest.json").read_text(encoding="utf-8"))
    assert result["pattern_count"] == 1
    assert result["timetable_count"] == 1
    assert [source["resource"] for source in manifest["sources"]] == list(snapshot.RESOURCES[:3])
    assert all(Path(source["path"]).is_file() for source in manifest["sources"])
    with pytest.raises(FileExistsError):
        snapshot.export_shibu24_capture(frozen, tmp_path / "route24")


def test_missing_route_partition_cannot_be_called_company_wide(tmp_path):
    _fixture(tmp_path)
    path = tmp_path / snapshot.MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["sources"] = [source for source in manifest["sources"]
                           if source["request"]["query"].get("odpt:busstopPole") != STOP_A]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Incomplete or duplicate ODPT partitions"):
        snapshot.build(tmp_path)
    assert not (tmp_path / snapshot.DATABASE).exists()
