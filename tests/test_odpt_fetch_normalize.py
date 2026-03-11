"""Tests for bff.services.odpt_fetch and bff.services.odpt_normalize."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest

# ---------------------------------------------------------------------------
# odpt_fetch tests
# ---------------------------------------------------------------------------


def test_build_odpt_url():
    from bff.services.odpt_fetch import build_odpt_url

    url = build_odpt_url("odpt:BusroutePattern", "test-key", "odpt.Operator:TokyuBus")
    assert "odpt%3ABusroutePattern" in url or "odpt:BusroutePattern" in url
    assert "acl%3AconsumerKey=test-key" in url or "acl:consumerKey=test-key" in url
    assert "odpt%3Aoperator=odpt.Operator%3ATokyuBus" in url or "odpt:operator=odpt.Operator:TokyuBus" in url


def test_consumer_key_env():
    from bff.services.odpt_fetch import _consumer_key

    with mock.patch.dict(os.environ, {"ODPT_CONSUMER_KEY": "abc123"}, clear=False):
        assert _consumer_key() == "abc123"


def test_consumer_key_fallback():
    from bff.services.odpt_fetch import _consumer_key

    env = {k: v for k, v in os.environ.items()}
    env.pop("ODPT_CONSUMER_KEY", None)
    env["ODPT_TOKEN"] = "fallback_token"
    with mock.patch.dict(os.environ, env, clear=True):
        assert _consumer_key() == "fallback_token"


def test_consumer_key_missing():
    from bff.services.odpt_fetch import _consumer_key

    env = {k: v for k, v in os.environ.items()}
    env.pop("ODPT_CONSUMER_KEY", None)
    env.pop("ODPT_TOKEN", None)
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="ODPT_CONSUMER_KEY"):
            _consumer_key()


def test_count_json_array_items(tmp_path):
    from bff.services.odpt_fetch import count_json_array_items

    data = [{"a": 1}, {"b": 2}, {"c": 3}]
    p = tmp_path / "test.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert count_json_array_items(p) == 3


def test_count_json_dict_items(tmp_path):
    from bff.services.odpt_fetch import count_json_array_items

    data = {"key1": "val1", "key2": "val2"}
    p = tmp_path / "test.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert count_json_array_items(p) == 2


def test_chunk_query_params_from_snapshot_files(tmp_path):
    from bff.services.odpt_fetch import _chunk_query_params

    (tmp_path / "busroute_pattern.json").write_text(
        json.dumps(
            [
                {"owl:sameAs": "odpt.BusroutePattern:A"},
                {"@id": "odpt.BusroutePattern:B"},
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "busstop_pole.json").write_text(
        json.dumps(
            [
                {"owl:sameAs": "odpt.BusstopPole:S1"},
                {"@id": "odpt.BusstopPole:S2"},
            ]
        ),
        encoding="utf-8",
    )

    assert _chunk_query_params("odpt:BusTimetable", tmp_path) == [
        {"odpt:busroutePattern": "odpt.BusroutePattern:A"},
        {"odpt:busroutePattern": "odpt.BusroutePattern:B"},
    ]
    assert _chunk_query_params("odpt:BusstopPoleTimetable", tmp_path) == [
        {"odpt:busstopPole": "odpt.BusstopPole:S1"},
        {"odpt:busstopPole": "odpt.BusstopPole:S2"},
    ]


def test_fetch_tokyu_odpt_bundle_chunks_timetable_resources(tmp_path):
    from bff.services import odpt_fetch

    def fake_download(url: str, out_path: Path, timeout: float = 300.0):
        if out_path.name == "busroute_pattern.json":
            payload = [
                {"owl:sameAs": "odpt.BusroutePattern:A"},
                {"owl:sameAs": "odpt.BusroutePattern:B"},
            ]
        elif out_path.name == "busstop_pole.json":
            payload = [
                {"owl:sameAs": "odpt.BusstopPole:S1"},
                {"owl:sameAs": "odpt.BusstopPole:S2"},
            ]
        else:
            raise AssertionError(f"unexpected direct download target: {out_path.name}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload), encoding="utf-8")
        return {"path": str(out_path), "size_bytes": out_path.stat().st_size, "sha256": "abc"}

    def fake_fetch_records(url: str, timeout: float = 300.0):
        query = parse_qs(urlparse(url).query)
        if "odpt:busroutePattern" in query:
            pattern_id = query["odpt:busroutePattern"][0]
            if pattern_id.endswith(":A"):
                return [
                    {"owl:sameAs": "trip:A:1"},
                    {"owl:sameAs": "trip:A:2"},
                ]
            if pattern_id.endswith(":B"):
                return [{"owl:sameAs": "trip:B:1"}]
        if "odpt:busstopPole" in query:
            stop_id = query["odpt:busstopPole"][0]
            if stop_id.endswith(":S1"):
                return [{"owl:sameAs": "st:S1:weekday"}]
            if stop_id.endswith(":S2"):
                return [{"owl:sameAs": "st:S2:weekday"}]
        raise AssertionError(f"unexpected chunk query: {url}")

    with mock.patch.object(odpt_fetch, "_consumer_key", return_value="token"), mock.patch.object(
        odpt_fetch, "_cache_base_dir", return_value=tmp_path
    ), mock.patch.object(odpt_fetch, "download_odpt_resource", side_effect=fake_download), mock.patch.object(
        odpt_fetch, "fetch_odpt_records", side_effect=fake_fetch_records
    ):
        manifest = odpt_fetch.fetch_tokyu_odpt_bundle()

    assert manifest["fetched_counts"]["odpt:BusroutePattern"] == 2
    assert manifest["fetched_counts"]["odpt:BusstopPole"] == 2
    assert manifest["fetched_counts"]["odpt:BusTimetable"] == 3
    assert manifest["fetched_counts"]["odpt:BusstopPoleTimetable"] == 2

    snapshot_dir = Path(manifest["snapshot_dir"])
    assert len(json.loads((snapshot_dir / "bus_timetable.json").read_text(encoding="utf-8"))) == 3
    assert len(
        json.loads((snapshot_dir / "busstop_pole_timetable.json").read_text(encoding="utf-8"))
    ) == 2


# ---------------------------------------------------------------------------
# odpt_normalize tests
# ---------------------------------------------------------------------------


def test_normalize_busstop_pole(tmp_path):
    from bff.services.odpt_normalize import normalize_busstop_pole

    raw_data = [
        {
            "owl:sameAs": "odpt.BusstopPole:TokyuBus.Shibuya.1",
            "dc:title": "渋谷駅",
            "geo:lat": 35.658,
            "geo:long": 139.701,
            "odpt:busstopPoleNumber": "1",
        },
        {
            "owl:sameAs": "odpt.BusstopPole:TokyuBus.Daikanyama.2",
            "dc:title": "代官山",
            "geo:lat": 35.650,
            "geo:long": 139.703,
            "odpt:busstopPoleNumber": "2",
        },
    ]

    result = normalize_busstop_pole(raw_data, tmp_path)
    assert result["stop_count"] == 2
    assert (tmp_path / "stops.jsonl").exists()

    # Verify JSONL content
    lines = (tmp_path / "stops.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    stop1 = json.loads(lines[0])
    assert stop1["name"] == "渋谷駅"
    assert stop1["source"] == "odpt"


def test_normalize_busroute_pattern(tmp_path):
    from bff.services.odpt_normalize import normalize_busroute_pattern

    raw_data = [
        {
            "owl:sameAs": "odpt.BusroutePattern:TokyuBus.Shibuya01.1",
            "dc:title": "渋01",
            "odpt:busroute": "odpt.Busroute:TokyuBus.Shibuya01",
            "odpt:busstopPoleOrder": [
                {"odpt:busstopPole": "odpt.BusstopPole:TokyuBus.Shibuya.1", "odpt:distance": 0},
                {"odpt:busstopPole": "odpt.BusstopPole:TokyuBus.Daikanyama.2", "odpt:distance": 1200},
            ],
        },
    ]
    stop_lookup = {
        "odpt.BusstopPole:TokyuBus.Shibuya.1": {"name": "渋谷駅"},
        "odpt.BusstopPole:TokyuBus.Daikanyama.2": {"name": "代官山"},
    }

    result = normalize_busroute_pattern(raw_data, tmp_path, stop_lookup)
    assert result["route_count"] == 1
    assert result["route_stop_count"] == 2
    assert (tmp_path / "routes.jsonl").exists()
    assert (tmp_path / "route_stops.jsonl").exists()

    routes = json.loads((tmp_path / "routes.jsonl").read_text(encoding="utf-8").strip())
    assert "渋01" in routes["name"]
    assert routes["source"] == "odpt"


def test_normalize_busstop_pole_timetable_synthesizes_missing_pattern_coverage(tmp_path):
    from bff.services.odpt_normalize import normalize_busstop_pole_timetable

    stop_lookup = {
        "odpt.BusstopPole:StopA": {"name": "Stop A"},
        "odpt.BusstopPole:StopB": {"name": "Stop B"},
    }
    route_patterns_lookup = {
        "odpt.BusroutePattern:T98.Out": {
            "pattern_id": "odpt.BusroutePattern:T98.Out",
            "busroute_id": "odpt.Busroute:TokyuBus.T98",
        }
    }
    raw_bus_timetable = [
        {
            "owl:sameAs": "odpt.BusTimetable:T98.Weekday.001",
            "odpt:busroutePattern": "odpt.BusroutePattern:T98.Out",
            "odpt:calendar": "odpt.Calendar:Weekday",
            "odpt:busTimetableObject": [
                {
                    "odpt:index": 0,
                    "odpt:busstopPole": "odpt.BusstopPole:StopA",
                    "odpt:departureTime": "06:00",
                },
                {
                    "odpt:index": 1,
                    "odpt:busstopPole": "odpt.BusstopPole:StopB",
                    "odpt:arrivalTime": "06:25",
                },
            ],
        }
    ]

    result = normalize_busstop_pole_timetable(
        [],
        tmp_path,
        stop_lookup,
        route_patterns_lookup,
        raw_bus_timetable,
    )

    assert result["synthetic_group_count"] == 1
    rows = (tmp_path / "busstop_pole_timetables.jsonl").read_text(encoding="utf-8").strip().split("\n")
    synthesized = json.loads(rows[0])
    assert synthesized["source"] == "odpt_synthesized_from_bus_timetable"
    assert synthesized["stopId"] == "odpt.BusstopPole:StopA"
    assert synthesized["service_id"] == "WEEKDAY"
    assert synthesized["items"][0]["busroutePattern"] == "odpt.BusroutePattern:T98.Out"


def test_reconcile_normalized_entities(tmp_path):
    from bff.services.odpt_normalize import reconcile_normalized_entities, _write_jsonl

    # Create minimal test data
    _write_jsonl([
        {"id": "route1"},
    ], tmp_path / "routes.jsonl")
    _write_jsonl([
        {"id": "stop1"},
    ], tmp_path / "stops.jsonl")
    _write_jsonl([
        {"trip_id": "trip1", "route_id": "route1"},
    ], tmp_path / "trips.jsonl")
    _write_jsonl([
        {"pattern_id": "p1", "route_id": "route1", "stop_id": "stop1"},
    ], tmp_path / "route_stops.jsonl")

    result = reconcile_normalized_entities(tmp_path)
    assert result["route_count"] == 1
    assert result["stop_count"] == 1
    assert result["trip_count"] == 1
    assert result["missing_stop_count"] == 0
    assert result["orphan_route_count"] == 0


def test_reconcile_detects_missing_stops(tmp_path):
    from bff.services.odpt_normalize import reconcile_normalized_entities, _write_jsonl

    _write_jsonl([{"id": "route1"}], tmp_path / "routes.jsonl")
    _write_jsonl([{"id": "stop1"}], tmp_path / "stops.jsonl")
    _write_jsonl([{"trip_id": "trip1", "route_id": "route1"}], tmp_path / "trips.jsonl")
    # route_stop references a stop not in stops.jsonl
    _write_jsonl([
        {"pattern_id": "p1", "route_id": "route1", "stop_id": "missing_stop"},
    ], tmp_path / "route_stops.jsonl")

    result = reconcile_normalized_entities(tmp_path)
    assert result["missing_stop_count"] == 1
    assert len(result["warnings"]) > 0


def test_data_hash_deterministic():
    from bff.services.odpt_normalize import _data_hash

    obj = {"a": 1, "b": "hello", "c": [1, 2, 3]}
    h1 = _data_hash(obj)
    h2 = _data_hash(obj)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_normalize_bus_timetable_handles_raw_odpt_trip_shape(tmp_path):
    from bff.services.odpt_normalize import normalize_bus_timetable

    raw_data = [
        {
            "owl:sameAs": "odpt.BusTimetable:TokyuBus.A24.weekday.0800",
            "odpt:calendar": "odpt.Calendar:Weekday",
            "odpt:busroutePattern": "odpt.BusroutePattern:TokyuBus.A24.out",
            "odpt:busTimetableObject": [
                {
                    "odpt:index": 1,
                    "odpt:busstopPole": "S1",
                    "odpt:departureTime": "08:00",
                },
                {
                    "odpt:index": 2,
                    "odpt:busstopPole": "S2",
                    "odpt:arrivalTime": "08:12",
                },
            ],
        }
    ]
    route_patterns_lookup = {
        "odpt.BusroutePattern:TokyuBus.A24.out": {
            "route_id": "route-a24-out",
            "total_distance_km": 4.8,
        }
    }
    stop_lookup = {
        "S1": {"name": "Start"},
        "S2": {"name": "End"},
    }

    result = normalize_bus_timetable(
        raw_data,
        tmp_path,
        route_patterns_lookup=route_patterns_lookup,
        stop_lookup=stop_lookup,
    )

    assert result["trip_count"] == 1
    assert result["stop_time_count"] == 2
    assert result["trip_counts_by_route"] == {"route-a24-out": 1}

    trips = [json.loads(line) for line in (tmp_path / "trips.jsonl").read_text(encoding="utf-8").splitlines()]
    assert trips == [
        {
            "trip_id": "odpt.BusTimetable:TokyuBus.A24.weekday.0800",
            "route_id": "route-a24-out",
            "service_id": "WEEKDAY",
            "direction": "outbound",
            "trip_index": 0,
            "origin": "Start",
            "destination": "End",
            "departure": "08:00",
            "arrival": "08:12",
            "distance_km": 4.8,
            "allowed_vehicle_types": ["BEV", "ICE"],
            "source": "odpt",
            "data_hash": trips[0]["data_hash"],
        }
    ]


def test_normalize_busstop_pole_timetable_preserves_route_pattern_refs(tmp_path):
    from bff.services.odpt_normalize import normalize_busstop_pole_timetable

    raw_data = [
        {
            "owl:sameAs": "tt-1",
            "odpt:busstopPole": "S1",
            "odpt:calendar": "odpt.Calendar:Weekday",
            "odpt:busstopPoleTimetableObject": [
                {
                    "odpt:departureTime": "08:00",
                    "odpt:destinationBusstopPole": "S2",
                    "odpt:busroutePattern": "pattern-1",
                    "odpt:busroute": "route-1",
                    "odpt:isMidnight": False,
                }
            ],
        }
    ]

    result = normalize_busstop_pole_timetable(
        raw_data,
        tmp_path,
        stop_lookup={"S1": {"name": "Start"}},
    )

    assert result["stop_timetable_count"] == 1
    items = [
        json.loads(line)
        for line in (tmp_path / "busstop_pole_timetables.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert items == [
        {
            "id": "tt-1",
            "source": "odpt",
            "stopId": "S1",
            "stopName": "Start",
            "calendar": "odpt.Calendar:Weekday",
            "service_id": "WEEKDAY",
            "items": [
                {
                    "departure": "08:00",
                    "destination": "S2",
                    "busroutePattern": "pattern-1",
                    "busroute": "route-1",
                    "isMidnight": False,
                    "note": "",
                }
            ],
        }
    ]
