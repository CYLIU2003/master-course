from __future__ import annotations

from scripts.audits.audit_shibu24_source import (
    audit,
    build_candidate,
    normalize_route_code,
    parse_time,
    route_stop_polyline_distance_km,
)
import pytest


def test_normalize_route_code_uses_nfkc_and_removes_whitespace() -> None:
    assert normalize_route_code(" 渋２４ ") == "渋24"


def test_source_audit_does_not_overwrite_existing_snapshot(tmp_path) -> None:
    output = tmp_path / "existing_snapshot"
    output.mkdir()
    (output / "manifest.json").write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError, match="immutable"):
        audit(tmp_path / "unused", tmp_path / "unused.json", tmp_path / "unused.jsonl",
              tmp_path / "unused_old.json", output)
    assert (output / "manifest.json").read_text(encoding="utf-8") == "original"


def test_route_stop_polyline_distance_requires_every_adjacent_segment() -> None:
    distance, segments = route_stop_polyline_distance_km(
        ("a", "b", "c"), {"a": (35.0, 139.0), "b": (35.001, 139.0), "c": (35.001, 139.001)}
    )
    assert distance > 0
    assert segments == 2


def test_build_candidate_preserves_operator_distance_and_browser_gate() -> None:
    pattern_id = "odpt.BusroutePattern:TokyuBus.Shibu24.0004600219"
    stop_a = "odpt.BusstopPole:TokyuBus.A.1"
    stop_b = "odpt.BusstopPole:TokyuBus.B.1"
    pattern = {"owl:sameAs": pattern_id, "odpt:operator": "odpt.Operator:TokyuBus",
               "odpt:busstopPoleOrder": [
        {"odpt:index": 1, "odpt:busstopPole": stop_a},
        {"odpt:index": 2, "odpt:busstopPole": stop_b},
    ]}
    timetable_id = "odpt.BusTimetable:TokyuBus.Shibu24.0004600219.A.Weekday.0600"
    timetable = {"owl:sameAs": timetable_id, "odpt:busroutePattern": pattern_id,
                 "odpt:operator": "odpt.Operator:TokyuBus", "odpt:calendar": "odpt.Calendar:Weekday",
                 "odpt:busTimetableObject": [
                     {"odpt:index": 1, "odpt:busstopPole": stop_a, "odpt:departureTime": "06:00"},
                     {"odpt:index": 2, "odpt:busstopPole": stop_b, "odpt:arrivalTime": "06:04"},
                 ]}
    stops = {stop_a: {"owl:sameAs": stop_a, "dc:title": "A", "geo:lat": 35.0, "geo:long": 139.0},
             stop_b: {"owl:sameAs": stop_b, "dc:title": "B", "geo:lat": 35.001, "geo:long": 139.0}}
    routes = {pattern_id: {"id": "route24-a", "routeCode": "渋２４", "direction": "outbound"}}

    result = build_candidate(patterns=[pattern], timetables=[timetable], stops=stops,
                             routes=routes, provenance={timetable_id: {"sha256": "x"}})

    row = result["timetable_rows"][0]
    assert row["operator_id"] == "tokyu"
    assert row["distance_km"] > 0
    assert row["browser_verification"] == "BROWSER_COMPARISON_PENDING"
    assert result["selected_routes"][0]["distanceKm"] == row["distance_km"]
