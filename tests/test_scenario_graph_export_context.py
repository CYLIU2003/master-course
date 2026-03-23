import json

from bff.mappers import scenario_to_problemdata
from src.data_schema import Task


def test_graph_export_context_loads_catalog_fast_stop_times(tmp_path, monkeypatch) -> None:
    route_stop_times_dir = tmp_path / "route_stop_times"
    route_stop_times_dir.mkdir(parents=True)
    normalized_dir = tmp_path / "normalized"
    normalized_dir.mkdir(parents=True)
    (route_stop_times_dir / "route-a.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trip_id": "trip-1",
                        "route_id": "route-a",
                        "service_id": "WEEKDAY",
                        "stop_id": "stop-a",
                        "stop_name": "Stop A",
                        "sequence": 0,
                        "arrival": "08:00",
                        "departure": "08:00",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "trip_id": "trip-1",
                        "route_id": "route-a",
                        "service_id": "WEEKDAY",
                        "stop_id": "stop-b",
                        "stop_name": "Stop B",
                        "sequence": 1,
                        "arrival": "08:10",
                        "departure": "08:10",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "trip_id": "trip-1",
                        "route_id": "route-a",
                        "service_id": "WEEKDAY",
                        "stop_id": "stop-c",
                        "stop_name": "Stop C",
                        "sequence": 2,
                        "arrival": "08:20",
                        "departure": "08:20",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    (normalized_dir / "stops.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "stop-a", "name": "Stop A"}, ensure_ascii=False),
                json.dumps({"id": "stop-b", "name": "Stop B"}, ensure_ascii=False),
                json.dumps({"id": "stop-c", "name": "Stop C"}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        scenario_to_problemdata,
        "_CATALOG_FAST_ROUTE_STOP_TIMES_DIR",
        route_stop_times_dir,
    )
    monkeypatch.setattr(
        scenario_to_problemdata,
        "_CATALOG_FAST_NORMALIZED_STOPS_PATH",
        normalized_dir / "stops.jsonl",
    )

    scenario = {
        "routes": [
            {
                "id": "route-a",
                "routeCode": "渋22",
                "routeFamilyCode": "渋22",
                "routeLabel": "渋22",
                "stopSequence": ["stop-a", "stop-b", "stop-c"],
            }
        ],
        "stops": [],
        "stop_timetables": [],
    }
    trips = [
        {
            "trip_id": "trip-1",
            "route_id": "route-a",
            "routeFamilyCode": "渋22",
            "origin": "Stop A",
            "destination": "Stop C",
            "origin_stop_id": "stop-a",
            "destination_stop_id": "stop-c",
            "service_id": "WEEKDAY",
        }
    ]
    tasks = [
        Task(
            task_id="trip-1",
            start_time_idx=0,
            end_time_idx=4,
            origin="Stop A",
            destination="Stop C",
            route_id="route-a",
            route_family_code="渋22",
            origin_stop_id="stop-a",
            destination_stop_id="stop-c",
            service_id="WEEKDAY",
        )
    ]

    context = scenario_to_problemdata._build_graph_export_context(scenario, trips, tasks)

    assert context["band_stop_sequences"]["渋22"][0] == ["Stop A", "Stop B", "Stop C"]
    assert context["task_stop_sequences"]["trip-1"] == [
        {
            "stop_id": "stop-a",
            "stop_label": "Stop A",
            "stop_sequence": 0,
            "arrival_time": "08:00",
            "departure_time": "08:00",
        },
        {
            "stop_id": "stop-b",
            "stop_label": "Stop B",
            "stop_sequence": 1,
            "arrival_time": "08:10",
            "departure_time": "08:10",
        },
        {
            "stop_id": "stop-c",
            "stop_label": "Stop C",
            "stop_sequence": 2,
            "arrival_time": "08:20",
            "departure_time": "08:20",
        },
    ]
