from pathlib import Path
from textwrap import dedent

from bff.services.gtfs_import import (
    build_gtfs_stop_timetables,
    load_gtfs_core_bundle,
    summarize_gtfs_routes_import,
    summarize_gtfs_stop_import,
    summarize_gtfs_stop_timetable_import,
    summarize_gtfs_timetable_import,
)


def _write_feed_file(feed_dir: Path, name: str, content: str) -> None:
    (feed_dir / name).write_text(dedent(content).strip() + "\n", encoding="utf-8")


def _create_feed(tmp_path: Path) -> Path:
    feed_dir = tmp_path / "mini-gtfs"
    feed_dir.mkdir()

    _write_feed_file(
        feed_dir,
        "agency.txt",
        """
        agency_id,agency_name,agency_url,agency_timezone,agency_lang
        A1,Sample Bus,https://example.com,Asia/Tokyo,ja
        """,
    )
    _write_feed_file(
        feed_dir,
        "routes.txt",
        """
        route_id,agency_id,route_short_name,route_long_name,route_desc,route_type,route_url,route_color,route_text_color,jp_parent_route_id
        R1,A1,Sample,Central Corridor,,3,https://example.com/routes/R1,112233,FFFFFF,
        """,
    )
    _write_feed_file(
        feed_dir,
        "stops.txt",
        """
        stop_id,stop_code,stop_name,stop_desc,stop_lat,stop_lon,zone_id,stop_url,location_type,parent_station,stop_timezone,wheelchair_boarding,platform_code,stop_access
        S1,100,Start,,35.0000,139.0000,,,0,,,,,
        S2,200,End,,35.0100,139.0100,,,0,,,,,
        S3,300,Mid,,35.0050,139.0050,,,0,,,,,
        """,
    )
    _write_feed_file(
        feed_dir,
        "calendar.txt",
        """
        service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date
        WD,1,1,1,1,1,0,0,20260101,20261231
        SA,0,0,0,0,0,1,0,20260101,20261231
        """,
    )
    _write_feed_file(
        feed_dir,
        "trips.txt",
        """
        route_id,service_id,trip_id,trip_headsign,trip_short_name,direction_id,block_id,shape_id,wheelchair_accessible,bikes_allowed,jp_trip_desc,jp_trip_desc_symbol,jp_office_id
        R1,WD,T1,End,,0,,shape-out,1,0,,,
        R1,WD,T2,Start,,1,,shape-in,1,0,,,
        R1,SA,T3,End,,0,,shape-out,1,0,,,
        """,
    )
    _write_feed_file(
        feed_dir,
        "stop_times.txt",
        """
        trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign,pickup_type,drop_off_type,shape_dist_traveled,timepoint
        T1,08:00:00,08:00:00,S1,1,End,,,,1
        T1,08:05:00,08:05:00,S3,2,End,,,,1
        T1,08:10:00,08:10:00,S2,3,End,,,,1
        T2,09:00:00,09:00:00,S2,1,Start,,,,1
        T2,09:06:00,09:06:00,S3,2,Start,,,,1
        T2,09:12:00,09:12:00,S1,3,Start,,,,1
        T3,10:00:00,10:00:00,S1,1,End,,,,1
        T3,10:05:00,10:05:00,S3,2,End,,,,1
        T3,10:10:00,10:10:00,S2,3,End,,,,1
        """,
    )

    return feed_dir


def test_load_gtfs_core_bundle_builds_routes_stops_and_timetable_rows(tmp_path: Path):
    feed_dir = _create_feed(tmp_path)

    bundle = load_gtfs_core_bundle(feed_dir)

    assert bundle["meta"]["source"] == "gtfs"
    assert bundle["meta"]["agencyName"] == "Sample Bus"
    assert bundle["meta"]["warnings"] == []
    assert len(bundle["stops"]) == 3
    assert len(bundle["routes"]) == 2
    assert len(bundle["timetable_rows"]) == 3
    assert bundle["stop_timetable_count"] == 6

    outbound_route = next(route for route in bundle["routes"] if route["startStop"] == "Start")
    inbound_route = next(route for route in bundle["routes"] if route["startStop"] == "End")

    assert outbound_route["source"] == "gtfs"
    assert outbound_route["tripCount"] == 2
    assert outbound_route["distanceKm"] > 0
    assert inbound_route["tripCount"] == 1

    weekday_rows = [row for row in bundle["timetable_rows"] if row["service_id"] == "WEEKDAY"]
    saturday_rows = [row for row in bundle["timetable_rows"] if row["service_id"] == "SAT"]
    assert len(weekday_rows) == 2
    assert len(saturday_rows) == 1
    assert {row["route_id"] for row in saturday_rows} == {outbound_route["id"]}


def test_build_gtfs_stop_timetables_groups_entries_by_stop_and_service(tmp_path: Path):
    feed_dir = _create_feed(tmp_path)

    stop_bundle = build_gtfs_stop_timetables(feed_dir)

    items = stop_bundle["stop_timetables"]
    assert len(items) == 6

    weekday_start = next(
        item
        for item in items
        if item["stopId"] == "S1" and item["service_id"] == "WEEKDAY"
    )
    saturday_end = next(
        item
        for item in items
        if item["stopId"] == "S2" and item["service_id"] == "SAT"
    )

    assert weekday_start["source"] == "gtfs"
    assert weekday_start["stopName"] == "Start"
    assert len(weekday_start["items"]) == 2
    assert weekday_start["items"][0]["busroutePattern"].startswith("gtfs-route-")
    assert saturday_end["items"][0]["destinationSign"] == "End"


def test_gtfs_import_summaries_report_expected_counts(tmp_path: Path):
    feed_dir = _create_feed(tmp_path)
    core_bundle = load_gtfs_core_bundle(feed_dir)
    stop_bundle = build_gtfs_stop_timetables(feed_dir)

    assert summarize_gtfs_routes_import(core_bundle["routes"], core_bundle) == {
        "routeCount": 2,
        "warningCount": 0,
        "zeroDurationCount": 0,
        "zeroDistanceCount": 0,
        "noTripCount": 0,
        "durationSources": {"stop_times_median": 2},
        "distanceSources": {"stop_geometry_median": 2},
    }
    assert summarize_gtfs_stop_import(core_bundle["stops"], core_bundle) == {
        "stopCount": 3,
        "namedCount": 3,
        "geoCount": 3,
        "poleNumberCount": 3,
        "warningCount": 0,
    }
    assert summarize_gtfs_timetable_import(
        core_bundle["timetable_rows"], core_bundle
    ) == {
        "rowCount": 3,
        "routeCount": 2,
        "serviceCounts": {"SAT": 1, "WEEKDAY": 2},
        "stopTimetableCount": 6,
        "warningCount": 0,
    }
    assert summarize_gtfs_stop_timetable_import(
        stop_bundle["stop_timetables"], stop_bundle
    ) == {
        "stopTimetableCount": 6,
        "entryCount": 9,
        "serviceCounts": {"SAT": 3, "WEEKDAY": 3},
        "warningCount": 0,
    }
