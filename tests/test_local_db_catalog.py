from __future__ import annotations

from pathlib import Path

import pytest

from bff.services import local_db_catalog
from tests._local_catalog_fixture import create_local_catalog_db


def test_get_timetable_trips_supports_multiple_depots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = create_local_catalog_db(tmp_path / "tokyu_subset.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)

    rows = local_db_catalog.get_timetable_trips(
        calendar_type="平日",
        depot_ids=["meguro", "seta"],
    )

    assert len(rows) == 3
    assert {row["depot_id"] for row in rows} == {"tokyu:depot:meguro", "tokyu:depot:seta"}


def test_build_milp_trips_unions_multiple_depots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = create_local_catalog_db(tmp_path / "tokyu_subset.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)

    trips = local_db_catalog.build_milp_trips(
        depot_ids=["meguro", "seta"],
        calendar_type="平日",
    )

    assert len(trips) == 3
    assert {trip["route_family"] for trip in trips} == {"黒01", "園01"}


def test_arrival_is_adjusted_when_service_crosses_midnight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = create_local_catalog_db(tmp_path / "tokyu_subset.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)

    trips = local_db_catalog.build_milp_trips(
        depot_id="seta",
        calendar_type="平日",
    )
    late_trip = next(item for item in trips if item["trip_id"] == "trip:garden:late")

    assert late_trip["dep_min"] == 1430
    assert late_trip["arr_min"] == 1450
    assert late_trip["arrival_time"] == "24:10"
    assert late_trip["duration_min"] == 20


def test_health_check_returns_db_not_found_for_missing_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    missing_path = tmp_path / "missing.sqlite"
    monkeypatch.setattr(local_db_catalog, "DB_PATH", missing_path)

    health = local_db_catalog.health_check()

    assert health["status"] == "db_not_found"


def test_build_dispatch_trip_adapter_returns_dispatch_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = create_local_catalog_db(tmp_path / "tokyu_subset.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)

    trips = local_db_catalog.build_dispatch_trips(
        depot_id="meguro",
        calendar_type="平日",
    )

    assert len(trips) == 1
    assert trips[0].trip_id == "trip:black:001"
    assert trips[0].route_id.startswith("tokyu:")
    assert trips[0].departure_time == "06:00"
    assert trips[0].arrival_time == "06:30"
    assert trips[0].distance_km > 0.0


def test_build_milp_trips_uses_straight_line_distance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = create_local_catalog_db(tmp_path / "tokyu_full.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)

    trips = local_db_catalog.build_milp_trips(
        depot_id="tokyu:depot:meguro",
        calendar_type="平日",
    )

    assert len(trips) == 1
    assert trips[0]["distance_km"] > 0.0
    assert trips[0]["origin_lat"] is not None
    assert trips[0]["destination_lon"] is not None


def test_trip_stops_include_coordinates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_path = create_local_catalog_db(tmp_path / "tokyu_full.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)

    stops = local_db_catalog.get_trip_stops("trip:black:001")

    assert len(stops) == 2
    assert stops[0]["lat"] is not None
    assert stops[0]["lon"] is not None
