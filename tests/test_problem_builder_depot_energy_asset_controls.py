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
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0]["depot_id"] = "depot_default"
    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["depot_default"]

    assert asset.allow_grid_to_bess is True
    assert asset.grid_to_bess_price_threshold_yen_per_kwh == 15.0
    assert tuple(asset.grid_to_bess_allowed_slot_indices) == (0,)
    assert asset.bess_terminal_soc_min_kwh == 20.0
