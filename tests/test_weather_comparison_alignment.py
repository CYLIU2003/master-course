from __future__ import annotations

import copy

import pytest

from bff.services.weather_comparison import (
    align_scenario_overlay,
    align_simulation_config,
    comparison_mismatches,
    validate_weather_case_alignment,
)


def _asset(date: str, pv_value: float, terminal_soc_kwh: float) -> dict:
    return {
        "depot_id": "tsurumaki",
        "pv_enabled": True,
        "pv_generation_kwh_by_slot": [pv_value] * 24,
        "pv_case_id": f"tsurumaki_{date}",
        "pv_profile_dates": [date],
        "pv_generation_kwh_by_date": [
            {"date": date, "pv_generation_kwh_by_slot": [pv_value] * 24}
        ],
        "pv_capacity_factor_by_date": [
            {"date": date, "capacity_factor_by_slot": [pv_value] * 24}
        ],
        "bess_energy_kwh": 600.0,
        "bess_terminal_soc_target_kwh": terminal_soc_kwh,
        "bess_terminal_soc_target_ratio": terminal_soc_kwh / 600.0,
        "bess_terminal_soc_target_percent": terminal_soc_kwh / 6.0,
    }


def _simulation_config(date: str, pv_value: float, terminal_soc_kwh: float, usage_cost: bool) -> dict:
    return {
        "service_date": date,
        "service_dates": [date],
        "pv_profile_id": f"tsurumaki_{date}",
        "weather_proxy_forecast_path": f"weather/{date}.json",
        "weather_proxy_station_id": "44132",
        "weather_proxy_station_name": "Tokyo",
        "weather_reference_date": date,
        "solcast_proxy_issue_date": "2025-08-09",
        "timestep_min": 60,
        "time_step_min": 60,
        "start_time": "05:00",
        "end_time": "23:00",
        "planning_horizon_hours": 20,
        "planning_days": 1,
        "cost_component_flags": {"vehicle_usage_cost": usage_cost},
        "vehicle_usage_cost_jpy_per_used_bus": 20000.0,
        "depot_energy_assets": [_asset(date, pv_value, terminal_soc_kwh)],
    }


def _overlay(date: str, pv_value: float, terminal_soc_kwh: float) -> dict:
    return {
        "scenario_id": f"scenario-{date}",
        "dataset_id": "tokyu",
        "dataset_version": "v1",
        "depot_ids": ["tsurumaki"],
        "route_ids": ["route-1"],
        "cost_coefficients": {
            "pv_profile_id": f"tsurumaki_{date}",
            "weather_mode": "actual_date_profile",
            "weather_factor_scalar": 1.0,
            "vehicle_usage_cost_jpy_per_used_bus": 20000.0,
        },
        "solver_config": {"time_limit_seconds": 1500},
        "depot_energy_assets": {"tsurumaki": _asset(date, pv_value, terminal_soc_kwh)},
    }


def test_alignment_copies_controls_but_preserves_target_weather_inputs() -> None:
    reference = _simulation_config("2025-08-05", 80.0, 300.0, True)
    target = _simulation_config("2025-08-10", 10.0, 0.0, False)
    original_target = copy.deepcopy(target)

    aligned = align_simulation_config(reference, target)

    assert aligned["service_date"] == "2025-08-10"
    assert aligned["pv_profile_id"] == "tsurumaki_2025-08-10"
    assert aligned["weather_proxy_station_id"] == "44132"
    assert aligned["weather_reference_date"] == "2025-08-10"
    assert aligned["cost_component_flags"]["vehicle_usage_cost"] is True
    assert aligned["depot_energy_assets"][0]["pv_generation_kwh_by_slot"] == [10.0] * 24
    assert aligned["depot_energy_assets"][0]["bess_terminal_soc_target_kwh"] == 300.0
    assert target == original_target
    assert comparison_mismatches(reference, aligned, config_label="simulation_config") == []
    validate_weather_case_alignment(
        reference,
        target,
        aligned,
        config_label="simulation_config",
    )


def test_overlay_alignment_preserves_target_identity_and_weather_inputs() -> None:
    reference = _overlay("2025-08-05", 80.0, 300.0)
    target = _overlay("2025-08-10", 10.0, 0.0)

    aligned = align_scenario_overlay(reference, target)

    assert aligned["scenario_id"] == "scenario-2025-08-10"
    assert aligned["cost_coefficients"]["pv_profile_id"] == "tsurumaki_2025-08-10"
    assert aligned["depot_energy_assets"]["tsurumaki"]["pv_generation_kwh_by_slot"] == [10.0] * 24
    assert aligned["depot_energy_assets"]["tsurumaki"]["bess_terminal_soc_target_percent"] == 50.0
    assert comparison_mismatches(reference, aligned, config_label="scenario_overlay") == []
    validate_weather_case_alignment(
        reference,
        target,
        aligned,
        config_label="scenario_overlay",
    )


def test_alignment_rejects_different_depot_sets() -> None:
    reference = _simulation_config("2025-08-05", 80.0, 300.0, True)
    target = _simulation_config("2025-08-10", 10.0, 0.0, False)
    target["depot_energy_assets"][0]["depot_id"] = "other"

    with pytest.raises(ValueError, match="same depots"):
        align_simulation_config(reference, target)


def test_alignment_rejects_a_time_axis_or_pv_slot_count_mismatch() -> None:
    reference = _simulation_config("2025-08-05", 80.0, 300.0, True)
    target = _simulation_config("2025-08-10", 10.0, 0.0, False)
    target["timestep_min"] = 30
    target["time_step_min"] = 30

    with pytest.raises(ValueError, match="time-axis controls"):
        align_simulation_config(reference, target)

    target["timestep_min"] = 60
    target["time_step_min"] = 60
    target["depot_energy_assets"][0]["pv_generation_kwh_by_slot"] = [10.0] * 23

    with pytest.raises(ValueError, match="must contain 24 slot values"):
        align_simulation_config(reference, target)
