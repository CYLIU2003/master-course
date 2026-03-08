from bff.routers.scenarios import (
    _build_stop_timetable_summary,
    _build_timetable_summary,
)


def test_build_timetable_summary_aggregates_by_route_and_service():
    rows = [
        {
            "trip_id": "T1",
            "route_id": "R1",
            "service_id": "WEEKDAY",
            "origin": "A",
            "destination": "B",
            "departure": "06:10",
            "arrival": "06:40",
        },
        {
            "trip_id": "T2",
            "route_id": "R1",
            "service_id": "WEEKDAY",
            "origin": "B",
            "destination": "C",
            "departure": "07:10",
            "arrival": "07:50",
        },
        {
            "trip_id": "T3",
            "route_id": "R2",
            "service_id": "SAT",
            "origin": "A",
            "destination": "D",
            "departure": "08:00",
            "arrival": "08:30",
        },
    ]

    summary = _build_timetable_summary(
        rows,
        {"odpt": {"generatedAt": "2026-03-08T01:00:00Z"}},
    )

    assert summary["totalRows"] == 3
    assert summary["serviceCount"] == 2
    assert summary["routeCount"] == 2
    assert summary["routeServiceCounts"]["WEEKDAY"]["R1"] == 2
    assert summary["routeServiceCounts"]["SAT"]["R2"] == 1
    assert summary["previewTripIds"] == ["T1", "T2", "T3"]
    assert summary["byService"][0]["serviceId"] == "SAT"
    assert summary["byService"][1]["serviceId"] == "WEEKDAY"
    assert summary["byRoute"][0]["routeId"] == "R1"
    assert summary["byRoute"][0]["sampleTripIds"] == ["T1", "T2"]


def test_build_stop_timetable_summary_counts_entries_and_stops():
    items = [
        {
            "id": "ST1",
            "stopId": "STOP_A",
            "stopName": "Stop A",
            "service_id": "WEEKDAY",
            "items": [{"departure": "06:10"}, {"departure": "06:40"}],
        },
        {
            "id": "ST2",
            "stopId": "STOP_A",
            "stopName": "Stop A",
            "service_id": "SAT",
            "items": [{"departure": "07:10"}],
        },
    ]

    summary = _build_stop_timetable_summary(
        items,
        {"gtfs": {"generatedAt": "2026-03-08T02:00:00Z"}},
    )

    assert summary["totalTimetables"] == 2
    assert summary["totalEntries"] == 3
    assert summary["serviceCount"] == 2
    assert summary["stopCount"] == 1
    assert summary["byService"][0]["serviceId"] == "SAT"
    assert summary["byStop"][0]["stopId"] == "STOP_A"
    assert summary["byStop"][0]["entryCount"] == 3
