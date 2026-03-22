from __future__ import annotations

from pathlib import Path

from bff.store import trip_store


def test_trip_store_excludes_gtfs_reconciliation_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "artifacts.sqlite"
    trip_store.save_timetable_rows(
        db_path,
        [
            {"trip_id": "trip-1", "route_id": "route-a", "service_id": "WEEKDAY"},
            {"trip_id": "trip-1__v1", "route_id": "route-a", "service_id": "WEEKDAY"},
            {"trip_id": "trip-2", "route_id": "route-a", "service_id": "SAT"},
        ],
    )

    assert [row["trip_id"] for row in trip_store.page_timetable_rows(db_path)] == ["trip-1", "trip-2"]
    assert trip_store.count_timetable_rows(db_path) == 2
    assert trip_store.count_timetable_rows(db_path, service_id="WEEKDAY") == 1
    assert trip_store.summarize_timetable_routes(db_path) == [
        {"route_id": "route-a", "service_id": "SAT", "trip_count": 1},
        {"route_id": "route-a", "service_id": "WEEKDAY", "trip_count": 1},
    ]


def test_trip_store_row_artifact_summary_excludes_gtfs_reconciliation_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "artifacts.sqlite"
    trip_store.save_rows(
        db_path,
        "timetable_rows",
        [
            {"trip_id": "trip-1", "route_id": "route-a", "service_id": "WEEKDAY"},
            {"trip_id": "trip-1__v2", "route_id": "route-a", "service_id": "WEEKDAY"},
            {"trip_id": "trip-2", "route_id": "route-b", "service_id": "WEEKDAY"},
        ],
    )

    assert trip_store.summarize_timetable_routes_from_row_artifacts(db_path) == [
        {"route_id": "route-a", "service_id": "WEEKDAY", "trip_count": 1},
        {"route_id": "route-b", "service_id": "WEEKDAY", "trip_count": 1},
    ]
