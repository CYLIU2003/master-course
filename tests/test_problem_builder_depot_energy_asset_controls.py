from __future__ import annotations

from src.optimization.common.builder import ProblemBuilder


def _scenario() -> dict:
    return {
        "meta": {"id": "s-1", "updatedAt": "2026-03-24T00:00:00Z"},
        "simulation_config": {
            "default_turnaround_min": 10,
            "depot_energy_assets": [
                {
                    "depot_id": "dep-1",
                    "depot_area_m2": 1000.0,
                    "pv_enabled": True,
                    "pv_generation_kwh_by_slot": [1.0, 2.0],
                    "bess_enabled": True,
                    "bess_energy_kwh": 100.0,
                    "bess_power_kw": 50.0,
                    "bess_initial_soc_kwh": 60.0,
                    "bess_soc_min_kwh": 10.0,
                    "bess_soc_max_kwh": 100.0,
                    "allow_grid_to_bess": True,
                    "grid_to_bess_price_threshold_yen_per_kwh": 15.0,
                    "grid_to_bess_allowed_slot_indices": [0],
                    "bess_terminal_soc_min_kwh": 20.0,
                }
            ],
        },
        "scenario_overlay": {
            "solver_config": {},
            "cost_coefficients": {},
            "charging_constraints": {},
        },
        "depots": [{"id": "dep-1", "name": "Depot 1"}],
        "routes": [{"id": "r1", "route_id": "r1"}],
        "vehicles": [
            {
                "id": "bev-1",
                "depotId": "dep-1",
                "type": "BEV",
                "batteryKwh": 300.0,
                "energyConsumption": 1.2,
                "chargePowerKw": 60.0,
            }
        ],
        "timetable_rows": [
            {
                "trip_id": "t1",
                "route_id": "r1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 10.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["BEV"],
            }
        ],
        "energy_price_profiles": [{"site_id": "dep-1", "values": [10.0, 20.0]}],
        "pv_profiles": [{"site_id": "dep-1", "values": [2.0, 4.0]}],
        "deadhead_rules": [],
        "turnaround_rules": [],
    }


def test_problem_builder_maps_grid_to_bess_controls_into_assets() -> None:
    problem = ProblemBuilder().build_from_scenario(_scenario(), depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.allow_grid_to_bess is True
    assert asset.grid_to_bess_price_threshold_yen_per_kwh == 15.0
    assert tuple(asset.grid_to_bess_allowed_slot_indices) == (0,)
    assert asset.bess_terminal_soc_min_kwh == 20.0


def test_problem_builder_resamples_hourly_depot_pv_series_to_price_slot_count() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0]["pv_generation_kwh_by_slot"] = [3.0, 6.0]
    scenario["simulation_config"]["depot_energy_assets"][0]["pv_capacity_kw"] = 60.0
    scenario["energy_price_profiles"] = [{"site_id": "dep-1", "values": [10.0, 20.0, 30.0, 40.0]}]

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert len(asset.pv_generation_kwh_by_slot) == len(problem.price_slots)
    assert asset.pv_capacity_kw == 70.0
    assert tuple(asset.pv_generation_kwh_by_slot) == (3.5, 3.5, 7.0, 7.0)


def test_problem_builder_prefers_daily_capacity_factor_metadata_for_pv_series() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0] = {
        "depot_id": "dep-1",
        "depot_area_m2": 1000.0,
        "pv_enabled": True,
        "pv_capacity_kw": 50.0,
        "pv_capacity_factor_by_date": [
            {
                "date": "2025-08-01",
                "slot_minutes": 60,
                "capacity_factor_by_slot": [0.1, 0.2],
            },
            {
                "date": "2025-08-02",
                "slot_minutes": 60,
                "capacity_factor_by_slot": [0.3, 0.4],
            },
        ],
    }
    scenario["energy_price_profiles"] = [{"site_id": "dep-1", "values": [10.0, 20.0, 30.0, 40.0]}]

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.pv_capacity_kw == 70.0
    assert tuple(asset.capacity_factor_by_slot) == (0.1, 0.2, 0.3, 0.4)
    assert tuple(asset.pv_generation_kwh_by_slot) == (7.0, 14.0, 21.0, 28.0)


def test_problem_builder_disables_legacy_pv_when_depot_area_missing() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0].pop("depot_area_m2", None)
    scenario["simulation_config"]["depot_energy_assets"][0]["pv_capacity_kw"] = 50.0

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.depot_area_m2 is None
    assert asset.pv_enabled is False
    assert asset.pv_capacity_kw == 0.0
    assert tuple(asset.pv_generation_kwh_by_slot) == (0.0, 0.0)


def test_problem_builder_area_scaling_doubles_capacity_and_generation() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0] = {
        "depot_id": "dep-1",
        "depot_area_m2": 1000.0,
        "pv_capacity_factor_by_date": [
            {
                "date": "2025-08-01",
                "slot_minutes": 60,
                "capacity_factor_by_slot": [0.0, 0.5],
            }
        ],
    }
    base = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")

    scenario["simulation_config"]["depot_energy_assets"][0]["depot_area_m2"] = 2000.0
    doubled = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")

    assert base.depot_energy_assets["dep-1"].pv_capacity_kw == 70.0
    assert doubled.depot_energy_assets["dep-1"].pv_capacity_kw == 140.0
    assert tuple(base.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot) == (0.0, 35.0)
    assert tuple(doubled.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot) == (0.0, 70.0)


def test_problem_builder_same_area_keeps_capacity_when_profile_shape_changes() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0] = {
        "depot_id": "dep-1",
        "depot_area_m2": 1000.0,
        "pv_capacity_factor_by_date": [
            {
                "date": "2025-08-01",
                "slot_minutes": 60,
                "capacity_factor_by_slot": [0.2, 0.4],
            }
        ],
    }
    day1 = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")

    scenario["simulation_config"]["depot_energy_assets"][0]["pv_capacity_factor_by_date"] = [
        {
            "date": "2025-08-02",
            "slot_minutes": 60,
            "capacity_factor_by_slot": [0.1, 0.6],
        }
    ]
    day2 = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")

    assert day1.depot_energy_assets["dep-1"].pv_capacity_kw == 70.0
    assert day2.depot_energy_assets["dep-1"].pv_capacity_kw == 70.0
    assert tuple(day1.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot) == (14.0, 28.0)
    assert tuple(day2.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot) == (7.0, 42.0)
