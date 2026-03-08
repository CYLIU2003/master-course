"""Tests for bff.services.odpt_fetch and bff.services.odpt_normalize."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

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
