from pathlib import Path

from bff.services import transit_db


def test_replace_all_persists_feed_identity_columns(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "gtfs_toei.db"
    monkeypatch.setenv("TRANSIT_DB_TOEI", str(db_path))

    transit_db.replace_all(
        "toei",
        routes=[
            {
                "id": "R1",
                "routeCode": "01",
                "name": "Sample Route",
            }
        ],
        stops=[
            {
                "id": "S1",
                "name": "Sample Stop",
                "lat": 35.0,
                "lon": 139.0,
            }
        ],
        timetable_rows=[
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "S1",
                "destination": "S1",
                "departure": "08:00",
                "arrival": "08:10",
                "allowed_vehicle_types": ["BEV"],
            }
        ],
        stop_timetables=[],
        trip_stop_times=[],
        calendar_entries=[
            {
                "service_id": "WEEKDAY",
                "service_name": "Weekday",
                "monday": 1,
            }
        ],
        calendar_date_entries=[
            {
                "service_id": "WEEKDAY",
                "date": "2026-03-09",
                "exception_type": 1,
            }
        ],
        meta={
            "feed_id": "toei_gtfs",
            "snapshot_id": "2026-03-09-official",
            "dataset_id": "toei_gtfs:2026-03-09-official",
        },
    )

    route = transit_db.get_route("toei", "R1")
    stop = transit_db.list_stops("toei")[0]
    trip = transit_db.list_timetable_rows("toei")[0]
    calendar = transit_db.list_calendar("toei")[0]
    calendar_date = transit_db.list_calendar_dates("toei")[0]

    assert route["feed_id"] == "toei_gtfs"
    assert stop["snapshot_id"] == "2026-03-09-official"
    assert trip["dataset_id"] == "toei_gtfs:2026-03-09-official"
    assert calendar["feed_id"] == "toei_gtfs"
    assert calendar_date["dataset_id"] == "toei_gtfs:2026-03-09-official"
