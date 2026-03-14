from pathlib import Path
from unittest.mock import patch

from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.store import scenario_store


def test_build_problem_data_from_scenario_uses_scope_rules_and_profiles():
    scenario = {
        "meta": {"id": "scenario-1", "updatedAt": "2026-03-08T00:00:00+00:00"},
        "depots": [{"id": "D1"}],
        "vehicles": [
            {
                "id": "V_BEV",
                "depotId": "D1",
                "type": "BEV",
                "batteryKwh": 300.0,
                "energyConsumption": 1.5,
                "minSoc": 0.2,
                "maxSoc": 0.9,
                "targetEndSoc": 0.6,
                "chargePowerKw": 150.0,
            },
            {
                "id": "V_ICE",
                "depotId": "D1",
                "type": "ICE",
                "energyConsumption": 0.5,
                "fuelTankL": 180.0,
            },
        ],
        "depot_route_permissions": [{"depotId": "D1", "routeId": "R1", "allowed": True}],
        "vehicle_route_permissions": [{"vehicleId": "V_BEV", "routeId": "R1", "allowed": False}],
        "timetable_rows": [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV", "ICE"],
            },
            {
                "trip_id": "T2",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "C",
                "destination": "D",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 8.0,
                "allowed_vehicle_types": ["ICE"],
            },
        ],
        "deadhead_rules": [{"from_stop": "B", "to_stop": "C", "travel_time_min": 15}],
        "turnaround_rules": [{"stop_id": "B", "min_turnaround_min": 5}],
        "charger_sites": [{"id": "D1", "site_type": "depot"}],
        "chargers": [{"id": "C1", "siteId": "D1", "powerKw": 150.0}],
        "pv_profiles": [{"site_id": "D1", "values": [0.0, 10.0, 5.0]}],
        "energy_price_profiles": [{"site_id": "D1", "values": [20.0, 25.0, 30.0]}],
        "duties": [
            {
                "duty_id": "duty_1",
                "vehicle_type": "ICE",
                "legs": [
                    {
                        "trip": {
                            "trip_id": "T1",
                            "origin": "A",
                            "destination": "B",
                            "departure": "07:00",
                            "arrival": "07:30",
                            "distance_km": 10.0,
                        }
                    }
                ],
            }
        ],
        "simulation_config": {
            "start_time": "05:00",
            "time_step_min": 15,
            "planning_horizon_hours": 16,
        },
    }

    data, report = build_problem_data_from_scenario(
        scenario,
        depot_id="D1",
        service_id="WEEKDAY",
        mode="mode_duty_constrained",
        use_existing_duties=True,
    )

    assert report.trip_count == 2
    assert report.task_count == 2
    assert report.vehicle_count == 2
    assert report.travel_connection_count == 2
    assert len(data.chargers) == 1
    assert len(data.pv_profiles) == 3
    assert len(data.electricity_prices) == 3

    by_task = {task.task_id: task for task in data.tasks}
    assert by_task["T1"].required_vehicle_type == "ICE"
    assert by_task["T1"].energy_required_kwh_bev == 15.0
    assert by_task["T1"].fuel_required_liter_ice == 5.0

    assert data.duty_assignment_enabled is True
    assert data.duty_trip_mapping == {"duty_1": ["T1"]}

    by_pair = {(tc.from_task_id, tc.to_task_id): tc for tc in data.travel_connections}
    assert by_pair[("T1", "T2")].can_follow is True
    assert by_pair[("T1", "T2")].deadhead_time_slot == 1


def test_build_problem_data_from_scenario_applies_analysis_scope_filters():
    scenario = {
        "meta": {"id": "scenario-scope", "updatedAt": "2026-03-08T00:00:00+00:00"},
        "depots": [{"id": "D1"}],
        "routes": [
            {"id": "R_MAIN", "routeVariantType": "main"},
            {"id": "R_SHORT", "routeVariantType": "short_turn"},
        ],
        "vehicles": [{"id": "V1", "depotId": "D1", "type": "BEV", "batteryKwh": 300.0}],
        "route_depot_assignments": [
            {"routeId": "R_MAIN", "depotId": "D1", "confidence": 1.0},
            {"routeId": "R_SHORT", "depotId": "D1", "confidence": 1.0},
        ],
        "timetable_rows": [
            {
                "trip_id": "T1",
                "route_id": "R_MAIN",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "T2",
                "route_id": "R_SHORT",
                "service_id": "WEEKDAY",
                "origin": "B",
                "destination": "C",
                "departure": "07:40",
                "arrival": "07:55",
                "distance_km": 3.0,
                "allowed_vehicle_types": ["BEV"],
            },
        ],
        "simulation_config": {"start_time": "05:00", "time_step_min": 15},
    }

    data, report = build_problem_data_from_scenario(
        scenario,
        depot_id="D1",
        service_id="WEEKDAY",
        mode="mode_milp_only",
        analysis_scope={
            "depotSelection": {"depotIds": ["D1"], "primaryDepotId": "D1"},
            "routeSelection": {
                "mode": "refine",
                "includeRouteIds": [],
                "excludeRouteIds": [],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {
                "includeShortTurn": False,
                "includeDepotMoves": True,
                "includeDeadhead": True,
            },
        },
    )

    assert report.trip_count == 1
    assert [task.task_id for task in data.tasks] == ["T1"]


def test_build_problem_data_from_scenario_uses_prebuilt_trips_when_timetable_rows_are_empty():
    scenario = {
        "meta": {"id": "scenario-shards", "updatedAt": "2026-03-14T00:00:00+00:00"},
        "depots": [{"id": "D1"}],
        "vehicles": [{"id": "V1", "depotId": "D1", "type": "BEV", "batteryKwh": 300.0}],
        "routes": [{"id": "R1"}],
        "timetable_rows": [],
        "trips": [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
            }
        ],
        "simulation_config": {"start_time": "05:00", "time_step_min": 15},
    }

    data, report = build_problem_data_from_scenario(
        scenario,
        depot_id="D1",
        service_id="WEEKDAY",
        mode="mode_milp_only",
        analysis_scope={
            "effectiveRouteIds": ["R1"],
            "routeSelection": {"includeRouteIds": ["R1"]},
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        },
    )

    assert report.trip_count == 1
    assert report.task_count == 1
    assert [task.task_id for task in data.tasks] == ["T1"]


def test_split_artifact_scenario_roundtrip_builds_equivalent_problem_data(tmp_path: Path):
    store_dir = tmp_path / "scenarios"
    app_context_path = tmp_path / "app_context.json"

    with patch.object(scenario_store, "_STORE_DIR", store_dir), patch.object(
        scenario_store, "_APP_CONTEXT_PATH", app_context_path
    ):
        meta = scenario_store.create_scenario("roundtrip", "", "thesis_mode")
        scenario_id = meta["id"]
        scenario_store.set_field(scenario_id, "depots", [{"id": "D1"}])
        scenario_store.set_field(
            scenario_id,
            "vehicles",
            [
                {
                    "id": "V1",
                    "depotId": "D1",
                    "type": "BEV",
                    "batteryKwh": 320.0,
                    "energyConsumption": 1.4,
                    "minSoc": 0.2,
                    "maxSoc": 0.9,
                    "targetEndSoc": 0.6,
                    "chargePowerKw": 120.0,
                }
            ],
        )
        scenario_store.set_field(
            scenario_id,
            "timetable_rows",
            [
                {
                    "trip_id": "T1",
                    "route_id": "R1",
                    "service_id": "WEEKDAY",
                    "origin": "A",
                    "destination": "B",
                    "departure": "24:15",
                    "arrival": "24:45",
                    "distance_km": 12.0,
                    "allowed_vehicle_types": ["BEV"],
                }
            ],
        )
        scenario_store.set_field(
            scenario_id,
            "charger_sites",
            [{"id": "D1", "site_type": "depot", "grid_import_limit_kw": 500.0}],
        )
        scenario_store.set_field(
            scenario_id,
            "chargers",
            [{"id": "C1", "siteId": "D1", "powerKw": 120.0}],
        )
        scenario_store.set_field(
            scenario_id,
            "pv_profiles",
            [{"site_id": "D1", "values": [0.0, 10.0, 5.0]}],
        )
        scenario_store.set_field(
            scenario_id,
            "energy_price_profiles",
            [{"site_id": "D1", "values": [20.0, 22.0, 25.0]}],
        )

        scenario = scenario_store._load(scenario_id)
        data, report = build_problem_data_from_scenario(
            scenario,
            depot_id="D1",
            service_id="WEEKDAY",
            mode="mode_milp_only",
        )

    assert report.trip_count == 1
    assert report.vehicle_count == 1
    assert len(data.tasks) == 1
    assert data.tasks[0].task_id == "T1"
    assert data.tasks[0].start_time_idx > 0
    assert len(data.chargers) == 1
    assert len(data.pv_profiles) == 3
    assert len(data.electricity_prices) == 3
    assert data.vehicles[0].battery_capacity == 320.0
