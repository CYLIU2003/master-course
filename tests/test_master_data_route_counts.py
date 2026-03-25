from __future__ import annotations

from bff.routers import master_data


def test_list_routes_defaults_to_dispatch_scope_service_counts(monkeypatch) -> None:
    monkeypatch.setattr(master_data, "_check_scenario", lambda scenario_id: None)
    monkeypatch.setattr(
        master_data.store,
        "list_routes",
        lambda scenario_id, depot_id=None, operator=None: [
            {
                "id": "route-a",
                "name": "黒01",
                "routeCode": "黒０１",
                "routeLabel": "黒０１ (目黒駅前 -> 大岡山小学校前)",
            }
        ],
    )
    monkeypatch.setattr(master_data, "reclassify_routes_for_runtime", lambda items: items)
    monkeypatch.setattr(
        master_data.store,
        "summarize_route_service_trip_counts",
        lambda scenario_id: [
            {"route_id": "route-a", "service_id": "WEEKDAY", "trip_count": 191},
            {"route_id": "route-a", "service_id": "SAT", "trip_count": 152},
            {"route_id": "route-a", "service_id": "SUN_HOL", "trip_count": 152},
        ],
    )
    monkeypatch.setattr(
        master_data.store,
        "get_dispatch_scope",
        lambda scenario_id: {"serviceId": "SAT"},
    )
    monkeypatch.setattr(master_data.store, "get_route_import_meta", lambda scenario_id: {})

    payload = master_data.list_routes("scenario-1")

    item = payload["items"][0]
    assert item["tripCount"] == 152
    assert item["tripCountSelectedDay"] == 152
    assert item["tripCountTotal"] == 495
    assert item["tripCountsByDayType"] == {"WEEKDAY": 191, "SAT": 152, "SUN_HOL": 152}
    assert item["selectedServiceId"] == "SAT"


def test_list_routes_explicit_service_id_overrides_dispatch_scope(monkeypatch) -> None:
    monkeypatch.setattr(master_data, "_check_scenario", lambda scenario_id: None)
    monkeypatch.setattr(
        master_data.store,
        "list_routes",
        lambda scenario_id, depot_id=None, operator=None: [
            {
                "id": "route-a",
                "name": "黒01",
                "routeCode": "黒０１",
                "routeLabel": "黒０１ (目黒駅前 -> 大岡山小学校前)",
            }
        ],
    )
    monkeypatch.setattr(master_data, "reclassify_routes_for_runtime", lambda items: items)
    monkeypatch.setattr(
        master_data.store,
        "summarize_route_service_trip_counts",
        lambda scenario_id: [
            {"route_id": "route-a", "service_id": "WEEKDAY", "trip_count": 191},
            {"route_id": "route-a", "service_id": "SAT", "trip_count": 152},
            {"route_id": "route-a", "service_id": "SUN_HOL", "trip_count": 152},
        ],
    )
    monkeypatch.setattr(
        master_data.store,
        "get_dispatch_scope",
        lambda scenario_id: {"serviceId": "SAT"},
    )
    monkeypatch.setattr(master_data.store, "get_route_import_meta", lambda scenario_id: {})

    payload = master_data.list_routes("scenario-1", service_id="WEEKDAY")

    item = payload["items"][0]
    assert item["tripCount"] == 191
    assert item["tripCountSelectedDay"] == 191
    assert item["selectedServiceId"] == "WEEKDAY"
