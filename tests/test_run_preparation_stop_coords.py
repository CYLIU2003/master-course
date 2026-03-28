from __future__ import annotations

import pandas as pd

from bff.services.run_preparation import _load_optional_stops, materialize_scenario_from_prepared_input
from src import tokyu_bus_data


def test_load_optional_stops_uses_catalog_coordinates_for_referenced_trip_stops(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(tokyu_bus_data, "tokyu_bus_data_ready", lambda dataset_id=None, root=None: True)
    monkeypatch.setattr(
        tokyu_bus_data,
        "load_stops",
        lambda dataset_id=None, root=None: [
            {"id": "stop-a", "name": "Depot", "lat": 35.0, "lon": 139.0},
            {"id": "stop-b", "name": "Terminal", "lat": 35.01, "lon": 139.01},
            {"id": "stop-x", "name": "Unused", "lat": 35.5, "lon": 139.5},
        ],
    )

    trips_df = pd.DataFrame(
        [
            {
                "trip_id": "trip-1",
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b",
                "origin": "Depot",
                "destination": "Terminal",
            }
        ]
    )
    timetables_df = pd.DataFrame()

    stops = _load_optional_stops(
        tmp_path,
        {"datasetId": "tokyu_full"},
        trips_df,
        timetables_df,
    )

    assert [item["id"] for item in stops] == ["stop-a", "stop-b"]
    assert stops[0]["lat"] == 35.0
    assert stops[1]["lon"] == 139.01


def test_load_optional_stops_backfills_missing_parquet_coordinates_from_catalog(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(tokyu_bus_data, "tokyu_bus_data_ready", lambda dataset_id=None, root=None: True)
    monkeypatch.setattr(
        tokyu_bus_data,
        "load_stops",
        lambda dataset_id=None, root=None: [
            {"id": "stop-a", "name": "Depot", "lat": 35.0, "lon": 139.0},
            {"id": "stop-b", "name": "Terminal", "lat": 35.01, "lon": 139.01},
        ],
    )
    pd.DataFrame(
        [
            {"id": "stop-a", "name": "Depot"},
            {"id": "stop-b", "name": "Terminal"},
        ]
    ).to_parquet(tmp_path / "stops.parquet")

    trips_df = pd.DataFrame(
        [
            {
                "trip_id": "trip-1",
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b",
                "origin": "Depot",
                "destination": "Terminal",
            }
        ]
    )

    stops = _load_optional_stops(
        tmp_path,
        {"datasetId": "tokyu_full"},
        trips_df,
        pd.DataFrame(),
    )

    assert [item["id"] for item in stops] == ["stop-a", "stop-b"]
    assert stops[0]["lat"] == 35.0
    assert stops[1]["lon"] == 139.01


def test_materialize_scenario_from_prepared_input_backfills_stop_coordinates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(tokyu_bus_data, "tokyu_bus_data_ready", lambda dataset_id=None, root=None: True)
    monkeypatch.setattr(
        tokyu_bus_data,
        "load_stops",
        lambda dataset_id=None, root=None: [
            {"id": "stop-a", "name": "Depot", "lat": 35.0, "lon": 139.0},
            {"id": "stop-b", "name": "Terminal", "lat": 35.01, "lon": 139.01},
        ],
    )

    prepared_input = {
        "dataset_id": "tokyu_full",
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "stops": [
            {"id": "stop-a", "name": "Depot"},
            {"id": "stop-b", "name": "Terminal"},
        ],
        "trips": [
            {
                "trip_id": "trip-1",
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b",
                "origin": "Depot",
                "destination": "Terminal",
            }
        ],
    }

    hydrated = materialize_scenario_from_prepared_input(
        {"id": "scenario-1", "meta": {"id": "scenario-1"}},
        prepared_input,
    )

    stops = {item["id"]: item for item in hydrated["stops"]}
    assert stops["stop-a"]["lat"] == 35.0
    assert stops["stop-b"]["lon"] == 139.01
