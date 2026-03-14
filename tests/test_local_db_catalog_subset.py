from __future__ import annotations

from pathlib import Path

import pytest

from bff.services import local_db_catalog
from tests._local_catalog_fixture import create_local_catalog_db


@pytest.fixture
def subset_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = create_local_catalog_db(tmp_path / "tokyu_subset.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)
    return db_path


def test_single_depot_milp_trips_returned(subset_db: Path):
    trips = local_db_catalog.build_milp_trips(depot_id="meguro", calendar_type="平日")

    assert [trip["trip_id"] for trip in trips] == ["trip:black:001"]
    assert {trip["depot_id"] for trip in trips} == {"tokyu:depot:meguro"}


def test_multiple_depots_milp_trips_returned(subset_db: Path):
    trips = local_db_catalog.build_milp_trips(depot_ids=["meguro", "seta"], calendar_type="平日")

    assert len(trips) == 3
    assert {trip["route_family"] for trip in trips} == {"黒01", "園01"}


def test_outside_depot_trips_do_not_leak_into_subset(subset_db: Path):
    trips = local_db_catalog.build_milp_trips(depot_ids=["meguro", "seta"], calendar_type="平日")

    assert "trip:awashima:001" not in {trip["trip_id"] for trip in trips}
    assert all(trip["depot_id"] in {"tokyu:depot:meguro", "tokyu:depot:seta"} for trip in trips)


def test_route_families_filter_is_applied(subset_db: Path):
    trips = local_db_catalog.build_milp_trips(
        depot_ids=["meguro", "seta"],
        route_families=["園01"],
        calendar_type="平日",
    )

    assert len(trips) == 2
    assert {trip["route_family"] for trip in trips} == {"園01"}


def test_departure_window_filter_is_applied(subset_db: Path):
    trips = local_db_catalog.build_milp_trips(
        depot_ids=["meguro", "seta"],
        calendar_type="平日",
        min_dep_min=400,
        max_dep_min=500,
    )

    assert [trip["trip_id"] for trip in trips] == ["trip:garden:001"]
