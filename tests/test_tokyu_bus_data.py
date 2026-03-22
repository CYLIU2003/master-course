from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.tokyu_bus_data import (
    build_timetable_summary_for_scope,
    load_stop_time_rows_for_scope,
    load_stop_timetable_rows_for_scope,
    load_trip_rows_for_scope,
    route_trip_counts_by_day_type,
    tokyu_bus_data_ready,
)


_BUILD_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_tokyu_bus_data.py"
_BUILD_SCRIPT_SPEC = importlib.util.spec_from_file_location("build_tokyu_bus_data", _BUILD_SCRIPT_PATH)
assert _BUILD_SCRIPT_SPEC is not None
assert _BUILD_SCRIPT_SPEC.loader is not None
build_script = importlib.util.module_from_spec(_BUILD_SCRIPT_SPEC)
sys.modules[_BUILD_SCRIPT_SPEC.name] = build_script
_BUILD_SCRIPT_SPEC.loader.exec_module(build_script)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            rows.append(json.loads(text))
    return rows


def test_build_tokyu_bus_data_generates_route_scoped_files_without_duplication(
    tmp_path: Path,
    monkeypatch,
) -> None:
    normalized_root = tmp_path / "catalog-fast" / "normalized"
    canonical_root = tmp_path / "tokyubus" / "canonical" / "snapshot-1"
    raw_root = tmp_path / "tokyubus" / "raw"
    output_root = tmp_path / "catalog-fast" / "tokyu_bus_data"

    _write_jsonl(
        normalized_root / "routes.jsonl",
        [
            {
                "id": "route-1",
                "name": "A1 outbound",
                "routeCode": "A1",
                "routeLabel": "A1 (Stop A -> Stop B)",
                "routeFamilyCode": "A1",
                "routeFamilyLabel": "A1",
                "depotId": "dep-1",
                "odptPatternId": "pattern-1",
                "odptBusrouteId": "busroute-1",
                "routeVariantType": "main_outbound",
                "canonicalDirection": "outbound",
            },
            {
                "id": "route-2",
                "name": "A1 inbound",
                "routeCode": "A1",
                "routeLabel": "A1 (Stop B -> Stop A)",
                "routeFamilyCode": "A1",
                "routeFamilyLabel": "A1",
                "depotId": "dep-1",
                "odptPatternId": "pattern-2",
                "odptBusrouteId": "busroute-2",
                "routeVariantType": "main_inbound",
                "canonicalDirection": "inbound",
            },
        ],
    )
    _write_jsonl(
        normalized_root / "stops.jsonl",
        [
            {"id": "stop-a", "name": "Stop A", "lat": 35.0, "lon": 139.0},
            {"id": "stop-b", "name": "Stop B", "lat": 35.1, "lon": 139.1},
        ],
    )
    _write_json(
        canonical_root / "canonical_summary.json",
        {
            "snapshot_id": "snapshot-1",
            "entity_counts": {
                "trips": 3,
                "stop_timetables": 2,
            },
        },
    )
    _write_jsonl(
        canonical_root / "trips.jsonl",
        [
            {
                "trip_id": "trip-1",
                "odpt_pattern_id": "pattern-1",
                "service_id": "weekday",
                "direction": "outbound",
                "trip_index": 1,
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b",
                "origin_name": "Stop A",
                "destination_name": "Stop B",
                "departure_time": "06:10:00",
                "arrival_time": "06:30:00",
                "distance_km": 10.5,
                "runtime_min": 20,
                "odpt_timetable_id": "odpt-trip-1",
            },
            {
                "trip_id": "trip-2",
                "odpt_pattern_id": "pattern-1",
                "service_id": "sat",
                "direction": "outbound",
                "trip_index": 2,
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b",
                "origin_name": "Stop A",
                "destination_name": "Stop B",
                "departure_time": "07:10:00",
                "arrival_time": "07:30:00",
                "distance_km": 10.5,
                "runtime_min": 20,
                "odpt_timetable_id": "odpt-trip-2",
            },
            {
                "trip_id": "trip-3",
                "odpt_pattern_id": "pattern-2",
                "service_id": "holiday",
                "direction": "inbound",
                "trip_index": 1,
                "origin_stop_id": "stop-b",
                "destination_stop_id": "stop-a",
                "origin_name": "Stop B",
                "destination_name": "Stop A",
                "departure_time": "08:10:00",
                "arrival_time": "08:30:00",
                "distance_km": 10.5,
                "runtime_min": 20,
                "odpt_timetable_id": "odpt-trip-3",
            },
        ],
    )
    _write_jsonl(
        canonical_root / "stop_times.jsonl",
        [
            {
                "trip_id": "trip-1",
                "stop_id": "stop-a",
                "stop_name": "Stop A",
                "stop_sequence": 1,
                "arrival_time": "06:10:00",
                "departure_time": "06:10:00",
            },
            {
                "trip_id": "trip-1",
                "stop_id": "stop-b",
                "stop_name": "Stop B",
                "stop_sequence": 2,
                "arrival_time": "06:30:00",
                "departure_time": "06:30:00",
            },
            {
                "trip_id": "trip-2",
                "stop_id": "stop-a",
                "stop_name": "Stop A",
                "stop_sequence": 1,
                "arrival_time": "07:10:00",
                "departure_time": "07:10:00",
            },
            {
                "trip_id": "trip-2",
                "stop_id": "stop-b",
                "stop_name": "Stop B",
                "stop_sequence": 2,
                "arrival_time": "07:30:00",
                "departure_time": "07:30:00",
            },
            {
                "trip_id": "trip-3",
                "stop_id": "stop-b",
                "stop_name": "Stop B",
                "stop_sequence": 1,
                "arrival_time": "08:10:00",
                "departure_time": "08:10:00",
            },
            {
                "trip_id": "trip-3",
                "stop_id": "stop-a",
                "stop_name": "Stop A",
                "stop_sequence": 2,
                "arrival_time": "08:30:00",
                "departure_time": "08:30:00",
            },
        ],
    )
    _write_jsonl(
        canonical_root / "stop_timetables.jsonl",
        [
            {
                "timetable_id": "pole-a",
                "service_id": "weekday",
                "calendar": "weekday",
                "stop_id": "stop-a",
                "stop_name": "Stop A",
                "items": [
                    {
                        "departure": "06:10:00",
                        "destination": "stop-b",
                        "busroutePattern": "pattern-1",
                        "busroute": "busroute-1",
                    }
                ],
            },
            {
                "timetable_id": "pole-b",
                "service_id": "holiday",
                "calendar": "holiday",
                "stop_id": "stop-b",
                "stop_name": "Stop B",
                "items": [
                    {
                        "departure": "08:10:00",
                        "destination": "stop-a",
                        "busroutePattern": "pattern-2",
                        "busroute": "busroute-2",
                    }
                ],
            },
        ],
    )

    monkeypatch.setattr(build_script, "CATALOG_FAST_NORMALIZED_ROOT", normalized_root)
    monkeypatch.setattr(build_script, "TOKYUBUS_RAW_ROOT", raw_root)
    monkeypatch.setattr(build_script, "BUILT_DIR", tmp_path / "built")

    result = build_script.build_tokyu_bus_data(
        canonical_snapshot_dir=canonical_root,
        output_root=output_root,
        rebuild_built=False,
    )

    assert result["counts"]["trips"] == 3
    assert result["counts"]["routesWithTrips"] == 2
    assert len(_read_jsonl(output_root / "route_trips" / "route-1.jsonl")) == 2
    assert len(_read_jsonl(output_root / "route_trips" / "route-2.jsonl")) == 1

    result = build_script.build_tokyu_bus_data(
        canonical_snapshot_dir=canonical_root,
        output_root=output_root,
        rebuild_built=False,
    )

    assert result["counts"]["trips"] == 3
    assert len(_read_jsonl(output_root / "route_trips" / "route-1.jsonl")) == 2
    assert len(_read_jsonl(output_root / "route_trips" / "route-2.jsonl")) == 1


def test_tokyu_bus_data_loader_reads_route_scoped_outputs(tmp_path: Path) -> None:
    root = tmp_path / "tokyu_bus_data"
    _write_json(
        root / "summary.json",
        {
            "generatedAt": "2026-03-22T00:00:00+00:00",
            "counts": {"stops": 2},
        },
    )
    _write_json(
        root / "route_index.json",
        {
            "items": [
                {
                    "routeId": "route-1",
                    "depotId": "dep-1",
                    "tripCountsByDayType": {"WEEKDAY": 2, "SAT": 1, "SUN_HOL": 0},
                    "firstDepartureByDayType": {"WEEKDAY": "06:10", "SAT": "07:10"},
                    "lastArrivalByDayType": {"WEEKDAY": "08:30", "SAT": "07:30"},
                    "sampleTripIds": ["trip-1", "trip-2"],
                    "tripFile": "route_trips/route-1.jsonl",
                    "stopTimeFile": "route_stop_times/route-1.jsonl",
                    "stopTimetableFile": "route_stop_timetables/route-1.jsonl",
                }
            ]
        },
    )
    _write_json(root / "family_index.json", {"items": []})
    _write_jsonl(root / "routes.jsonl", [{"id": "route-1", "tripCount": 3}])
    _write_jsonl(
        root / "route_trips" / "route-1.jsonl",
        [
            {"trip_id": "trip-1", "route_id": "route-1", "service_id": "WEEKDAY", "departure": "06:10"},
            {"trip_id": "trip-2", "route_id": "route-1", "service_id": "WEEKDAY", "departure": "08:10"},
            {"trip_id": "trip-3", "route_id": "route-1", "service_id": "SAT", "departure": "07:10"},
        ],
    )
    _write_jsonl(
        root / "route_stop_times" / "route-1.jsonl",
        [
            {"trip_id": "trip-1", "route_id": "route-1", "service_id": "WEEKDAY", "sequence": 1},
            {"trip_id": "trip-1", "route_id": "route-1", "service_id": "WEEKDAY", "sequence": 2},
        ],
    )
    _write_jsonl(
        root / "route_stop_timetables" / "route-1.jsonl",
        [
            {"id": "pole-1", "route_id": "route-1", "service_id": "WEEKDAY", "stopId": "stop-a"},
        ],
    )

    assert tokyu_bus_data_ready(root=root)
    assert route_trip_counts_by_day_type(dataset_id="tokyu_full", route_ids=["route-1"], depot_ids=None, root=root) == {
        "route-1": {"WEEKDAY": 2, "SAT": 1, "SUN_HOL": 0}
    }
    assert [row["trip_id"] for row in load_trip_rows_for_scope(dataset_id="tokyu_full", route_ids=["route-1"], depot_ids=None, service_ids=["WEEKDAY"], root=root)] == [
        "trip-1",
        "trip-2",
    ]
    assert len(
        load_stop_time_rows_for_scope(
            dataset_id="tokyu_full",
            route_ids=["route-1"],
            depot_ids=None,
            service_ids=["WEEKDAY"],
            root=root,
        )
    ) == 2
    assert len(
        load_stop_timetable_rows_for_scope(
            dataset_id="tokyu_full",
            route_ids=["route-1"],
            depot_ids=None,
            service_ids=["WEEKDAY"],
            root=root,
        )
    ) == 1

    summary = build_timetable_summary_for_scope(
        dataset_id="tokyu_full",
        route_ids=["route-1"],
        depot_ids=None,
        service_ids=["WEEKDAY"],
        root=root,
    )

    assert summary is not None
    assert summary["totalRows"] == 2
    assert summary["routeCount"] == 1
    assert summary["serviceCount"] == 1
    assert summary["previewTripIds"] == ["trip-1", "trip-2"]
