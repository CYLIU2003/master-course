from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario


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
