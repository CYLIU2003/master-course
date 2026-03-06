from bff.services.odpt_timetable import (
    build_timetable_rows_from_operational,
    summarize_timetable_import,
)


def test_build_timetable_rows_from_operational_uses_stop_names_and_route_ids():
    dataset = {
        "meta": {"warnings": []},
        "stops": {
            "S1": {"name": "Start"},
            "S2": {"name": "End"},
            "S3": {"name": "Depot"},
        },
        "routePatterns": {
            "odpt.BusroutePattern:TokyuBus.A24.out": {
                "busroute": "odpt.Busroute:TokyuBus.A24",
                "stop_sequence": ["S1", "S2"],
                "total_distance_km": 4.2,
            },
            "odpt.BusroutePattern:TokyuBus.A24.in": {
                "busroute": "odpt.Busroute:TokyuBus.A24",
                "stop_sequence": ["S2", "S1"],
                "total_distance_km": 4.2,
            },
        },
        "trips": {
            "trip-1": {
                "pattern_id": "odpt.BusroutePattern:TokyuBus.A24.out",
                "service_id": "weekday",
                "estimated_distance_km": 4.2,
                "stop_times": [
                    {"stop_id": "S1", "departure": "08:00"},
                    {"stop_id": "S2", "arrival": "08:15"},
                ],
            },
            "trip-2": {
                "pattern_id": "odpt.BusroutePattern:TokyuBus.A24.in",
                "service_id": "saturday",
                "estimated_distance_km": 4.2,
                "stop_times": [
                    {"stop_id": "S2", "departure": "09:00"},
                    {"stop_id": "S1", "arrival": "09:18"},
                ],
            },
            "trip-bad": {
                "pattern_id": "odpt.BusroutePattern:TokyuBus.A24.out",
                "service_id": "weekday",
                "stop_times": [{"stop_id": "S3"}],
            },
        },
        "stopTimetables": {"st-1": {}, "st-2": {}},
    }

    rows = build_timetable_rows_from_operational(dataset)

    assert len(rows) == 2
    by_service = {row["service_id"]: row for row in rows}
    assert by_service["WEEKDAY"]["origin"] == "Start"
    assert by_service["WEEKDAY"]["destination"] == "End"
    assert by_service["WEEKDAY"]["direction"] == "outbound"
    assert by_service["SAT"]["origin"] == "End"
    assert by_service["SAT"]["destination"] == "Start"
    assert by_service["SAT"]["direction"] == "outbound"
    assert by_service["WEEKDAY"]["route_id"].startswith("odpt-route-")


def test_summarize_timetable_import_reports_stop_timetable_count():
    rows = [
        {"route_id": "r1", "service_id": "WEEKDAY"},
        {"route_id": "r1", "service_id": "WEEKDAY"},
        {"route_id": "r2", "service_id": "SAT"},
    ]
    dataset = {
        "meta": {"warnings": ["warn-1"]},
        "stopTimetables": {"st-1": {}, "st-2": {}, "st-3": {}},
    }

    summary = summarize_timetable_import(rows, dataset)

    assert summary == {
        "rowCount": 3,
        "routeCount": 2,
        "serviceCounts": {"SAT": 1, "WEEKDAY": 2},
        "stopTimetableCount": 3,
        "warningCount": 1,
    }
