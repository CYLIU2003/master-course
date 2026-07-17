from __future__ import annotations

import pytest

from src.optimization.common.builder import ProblemBuilder
from src.preprocess.emission_factor_loader import lookup_ice_emission_factor


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
    assert asset.bess_terminal_soc_target_kwh == 0.0
    assert asset.bess_terminal_soc_policy == "minimum_only"
    assert asset.bess_terminal_soc_deviation_penalty_yen_per_kwh == 20.0


def test_problem_builder_prefers_overlay_depot_energy_asset_dict() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0]["bess_initial_soc_kwh"] = 20.0
    scenario["scenario_overlay"]["depot_energy_assets"] = {
        "dep-1": {
            "bess_enabled": True,
            "bess_energy_kwh": 100.0,
            "bess_power_kw": 50.0,
            "bess_initial_soc_kwh": 70.0,
            "bess_soc_min_kwh": 15.0,
            "bess_soc_max_kwh": 95.0,
            "bess_terminal_soc_min_kwh": 65.0,
            "bess_terminal_soc_target_kwh": 80.0,
            "bess_terminal_soc_deviation_penalty_yen_per_kwh": 12.5,
        }
    }

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.bess_initial_soc_kwh == 70.0
    assert asset.bess_soc_min_kwh == 15.0
    assert asset.bess_soc_max_kwh == 95.0
    assert asset.bess_terminal_soc_min_kwh == 65.0
    assert asset.bess_terminal_soc_target_kwh == 80.0
    assert asset.bess_terminal_soc_policy == "fixed_target"
    assert asset.bess_terminal_soc_deviation_penalty_yen_per_kwh == 12.5


def test_problem_builder_defaults_bess_soc_max_to_configured_capacity() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0]["bess_soc_max_kwh"] = 0.0
    scenario["simulation_config"]["depot_energy_assets"][0]["bess_initial_soc_kwh"] = 120.0
    scenario["simulation_config"]["depot_energy_assets"][0]["bess_cycle_cost_yen_per_kwh"] = 8.5

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.bess_soc_max_kwh == 100.0
    assert asset.bess_initial_soc_kwh == 100.0
    assert asset.bess_cycle_cost_yen_per_kwh == 8.5


def test_problem_builder_normalizes_bess_ratio_controls_into_kwh() -> None:
    scenario = _scenario()
    asset_cfg = scenario["simulation_config"]["depot_energy_assets"][0]
    asset_cfg.pop("bess_initial_soc_kwh")
    asset_cfg.pop("bess_soc_min_kwh")
    asset_cfg.pop("bess_soc_max_kwh")
    asset_cfg.pop("bess_terminal_soc_min_kwh")
    asset_cfg["bess_initial_soc_ratio"] = 0.6
    asset_cfg["bess_soc_min_ratio"] = 0.2
    asset_cfg["bess_soc_max_ratio"] = 0.9
    asset_cfg["bess_terminal_soc_min_ratio"] = 0.2
    asset_cfg["bess_terminal_soc_target_ratio"] = 0.7
    asset_cfg["allow_pv_to_bess"] = False
    asset_cfg["allow_bess_to_bus"] = False

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.bess_initial_soc_kwh == 60.0
    assert asset.bess_soc_min_kwh == 20.0
    assert asset.bess_soc_max_kwh == 90.0
    assert asset.bess_terminal_soc_min_kwh == 20.0
    assert asset.bess_terminal_soc_target_kwh == 70.0
    assert asset.bess_terminal_soc_policy == "fixed_target"
    assert asset.allow_pv_to_bess is False
    assert asset.allow_bess_to_bus is False


def test_problem_builder_propagates_pv_curtail_penalty_metadata() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["pv_curtail_penalty_yen_per_kwh"] = 7.5

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")

    assert problem.metadata["pv_curtail_penalty_yen_per_kwh"] == 7.5


def test_problem_builder_respects_explicit_pv_disabled_flag() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0]["pv_enabled"] = False

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.pv_enabled is False
    assert asset.pv_capacity_kw == 0.0
    assert all(value == 0.0 for value in asset.pv_generation_kwh_by_slot)


def test_problem_builder_rejects_missing_positive_trip_distance() -> None:
    scenario = _scenario()
    row = scenario["timetable_rows"][0]
    row.pop("distance_km")

    with pytest.raises(ValueError, match="Trip distance is required"):
        ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")


def test_problem_builder_uses_zero_pv_when_no_profile_without_synthetic_fallback() -> None:
    scenario = _scenario()
    scenario.pop("pv_profiles")
    scenario["simulation_config"]["depot_energy_assets"][0].pop("pv_generation_kwh_by_slot")
    scenario["simulation_config"]["depot_energy_assets"][0].pop("depot_area_m2")

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")

    assert all(slot.pv_available_kw == 0.0 for slot in problem.pv_slots)
    assert problem.metadata["synthetic_pv_fallback_applied"] is False


def test_problem_builder_synthetic_pv_fallback_requires_explicit_opt_in() -> None:
    scenario = _scenario()
    scenario.pop("pv_profiles")
    scenario["simulation_config"]["allow_synthetic_pv_fallback"] = True
    scenario["simulation_config"]["depot_energy_assets"][0].pop("pv_generation_kwh_by_slot")
    scenario["simulation_config"]["depot_energy_assets"][0].pop("depot_area_m2")

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")

    assert any(slot.pv_available_kw > 0.0 for slot in problem.pv_slots)
    assert problem.metadata["synthetic_pv_fallback_allowed"] is True
    assert problem.metadata["synthetic_pv_fallback_applied"] is True


def test_problem_builder_resamples_hourly_depot_pv_series_to_price_slot_count() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0]["pv_generation_kwh_by_slot"] = [3.0, 6.0]
    scenario["simulation_config"]["depot_energy_assets"][0]["pv_capacity_kw"] = 60.0
    scenario["energy_price_profiles"] = [{"site_id": "dep-1", "values": [10.0, 20.0, 30.0, 40.0]}]

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert len(asset.pv_generation_kwh_by_slot) == len(problem.price_slots)
    assert asset.pv_capacity_kw == 70.0
    assert tuple(asset.pv_generation_kwh_by_slot) == tuple([3.5] * 24 + [7.0] * 24)


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
    assert tuple(asset.capacity_factor_by_slot) == tuple([0.1] * 12 + [0.2] * 12 + [0.3] * 12 + [0.4] * 12)
    assert tuple(asset.pv_generation_kwh_by_slot) == tuple([3.5] * 12 + [7.0] * 12 + [10.5] * 12 + [14.0] * 12)


def test_problem_builder_rotates_full_day_pv_profile_to_horizon_start() -> None:
    scenario = _scenario()
    capacity_factors = [0.0] * 24
    capacity_factors[5] = 0.4
    capacity_factors[18] = 0.2
    scenario["simulation_config"]["start_time"] = "05:00"
    scenario["simulation_config"]["depot_energy_assets"][0] = {
        "depot_id": "dep-1",
        "pv_enabled": True,
        "pv_capacity_kw": 100.0,
        "pv_capacity_kw_manual_override": True,
        "pv_capacity_factor_by_date": [
            {
                "date": "2025-08-01",
                "slot_minutes": 60,
                "capacity_factor_by_slot": capacity_factors,
            }
        ],
    }

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert problem.scenario.horizon_start == "05:00"
    assert asset.pv_generation_kwh_by_slot[0] == 20.0
    assert asset.pv_generation_kwh_by_slot[1] == 20.0
    assert asset.pv_generation_kwh_by_slot[26] == 10.0
    assert asset.pv_generation_kwh_by_slot[10] == 0.0


def test_problem_builder_disables_legacy_pv_when_depot_area_missing() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0].pop("depot_area_m2", None)
    scenario["simulation_config"]["depot_energy_assets"][0]["pv_capacity_kw"] = 50.0

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.depot_area_m2 is None
    assert asset.pv_enabled is False
    assert asset.pv_capacity_kw == 0.0
    assert tuple(asset.pv_generation_kwh_by_slot) == tuple([0.0] * 48)


def test_problem_builder_uses_manual_pv_capacity_override_without_depot_area() -> None:
    scenario = _scenario()
    scenario["simulation_config"]["depot_energy_assets"][0] = {
        "depot_id": "dep-1",
        "pv_enabled": True,
        "pv_capacity_kw": 120.0,
        "pv_capacity_kw_manual_override": True,
        "pv_capacity_factor_by_date": [
            {
                "date": "2025-08-01",
                "slot_minutes": 60,
                "capacity_factor_by_slot": [0.25, 0.5],
            }
        ],
    }
    scenario["energy_price_profiles"] = [{"site_id": "dep-1", "values": [10.0, 20.0]}]

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    asset = problem.depot_energy_assets["dep-1"]

    assert asset.pv_enabled is True
    assert asset.pv_capacity_kw == 120.0
    assert tuple(asset.pv_generation_kwh_by_slot) == tuple([15.0] * 24 + [30.0] * 24)


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
    assert tuple(base.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot) == tuple([0.0] * 24 + [17.5] * 24)
    assert tuple(doubled.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot) == tuple([0.0] * 24 + [35.0] * 24)


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
    assert tuple(day1.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot) == tuple([7.0] * 24 + [14.0] * 24)
    assert tuple(day2.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot) == tuple([3.5] * 24 + [21.0] * 24)


def test_problem_builder_propagates_ice_emission_factor_from_catalog() -> None:
    scenario = _scenario()
    scenario["vehicles"] = [
        {
            "id": "ice-1",
            "depotId": "dep-1",
            "type": "ICE",
            "modelCode": "2KG-LV290N4",
            "fuelConsumptionLPerKm": 0.1869,
            "fuelTankL": 150.0,
        }
    ]
    scenario["timetable_rows"][0]["allowed_vehicle_types"] = ["ICE"]

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")
    vehicle_type = next(item for item in problem.vehicle_types if item.vehicle_type_id == "ICE")
    expected = lookup_ice_emission_factor("2KG-LV290N4")

    assert expected is not None
    assert vehicle_type.co2_emission_kg_per_l == expected["co2EmissionKgPerL"]
