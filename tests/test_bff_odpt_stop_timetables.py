from bff.services.odpt_stop_timetables import (
    build_stop_timetables_from_normalized,
    summarize_stop_timetable_import,
)


def test_build_stop_timetables_from_normalized_uses_stop_names():
    dataset = {
        "stops": {"S1": {"name": "Azamino"}},
        "stopTimetables": {
            "tt-1": {
                "stop_id": "S1",
                "calendar": "odpt.Calendar:Weekday",
                "service_id": "weekday",
                "items": [{"index": 1, "departure": "08:00"}],
            }
        },
    }

    items = build_stop_timetables_from_normalized(dataset)

    assert items == [
        {
            "id": "tt-1",
            "source": "odpt",
            "stopId": "S1",
            "stopName": "Azamino",
            "calendar": "odpt.Calendar:Weekday",
            "service_id": "weekday",
            "items": [{"index": 1, "departure": "08:00"}],
        }
    ]


def test_summarize_stop_timetable_import_counts_entries():
    items = [
        {"id": "tt-1", "service_id": "weekday", "items": [{}, {}]},
        {"id": "tt-2", "service_id": "saturday", "items": [{}]},
    ]
    dataset = {"meta": {"warnings": ["warn-1", "warn-2"]}}

    summary = summarize_stop_timetable_import(items, dataset)

    assert summary == {
        "stopTimetableCount": 2,
        "entryCount": 3,
        "serviceCounts": {"saturday": 1, "weekday": 1},
        "warningCount": 2,
    }
