from bff.services.odpt_routes import (
    build_routes_from_operational,
    summarize_routes_import,
)


def test_build_routes_from_operational_prefers_full_trip_duration_and_distance():
    dataset = {
        "meta": {"warnings": []},
        "stops": {
            "S1": {"name": "Start"},
            "S2": {"name": "Middle"},
            "S3": {"name": "End"},
        },
        "routePatterns": {
            "pattern-1": {
                "title": "Line 1",
                "busroute": "route-1",
                "stop_sequence": ["S1", "S2", "S3"],
                "total_distance_km": 12.5,
                "distance_coverage_ratio": 1.0,
            }
        },
        "trips": {
            "trip-1": {
                "distance_source": "pattern_segments",
                "estimated_distance_km": 12.5,
                "stop_times": [
                    {"departure": "08:00"},
                    {"arrival": "08:42"},
                ],
            }
        },
        "indexes": {"tripsByPattern": {"pattern-1": ["trip-1"]}},
    }

    routes = build_routes_from_operational(dataset)

    assert len(routes) == 1
    route = routes[0]
    assert route["name"] == "Line 1 (Start -> End)"
    assert route["startStop"] == "Start"
    assert route["endStop"] == "End"
    assert route["distanceKm"] == 12.5
    assert route["durationMin"] == 42
    assert route["tripCount"] == 1
    assert route["durationSource"] == "pattern_segments_median"
    assert route["distanceSource"] == "pattern_total"


def test_summarize_routes_import_counts_zero_duration_and_warnings():
    routes = [
        {
            "id": "r1",
            "durationMin": 0,
            "distanceKm": 0.0,
            "tripCount": 0,
            "durationSource": "none",
            "distanceSource": "none",
        },
        {
            "id": "r2",
            "durationMin": 15,
            "distanceKm": 3.2,
            "tripCount": 3,
            "durationSource": "trip_median",
            "distanceSource": "trip_estimate_median",
        },
    ]
    dataset = {"meta": {"warnings": ["BusTimetable maybe truncated"]}}

    summary = summarize_routes_import(routes, dataset)

    assert summary["routeCount"] == 2
    assert summary["warningCount"] == 1
    assert summary["zeroDurationCount"] == 1
    assert summary["zeroDistanceCount"] == 1
    assert summary["noTripCount"] == 1
    assert summary["durationSources"] == {"none": 1, "trip_median": 1}
    assert summary["distanceSources"] == {"none": 1, "trip_estimate_median": 1}
