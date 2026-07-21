from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.compare_research_phase3_weather import (
    ComparisonContractError,
    build_weather_comparison,
    render_markdown_report,
)


def _summary(
    *,
    case_name: str,
    scenario_id: str,
    service_date: str,
    pv_generation_kwh: float,
    pv_case_id: str,
    pv_hash: str,
    weather_operation_mode: str,
    total_cost: float,
    grid_import_kwh: float,
) -> dict:
    validation_metrics = {
        "all_required_validation_checks_passed": True,
        "bess_terminal_soc_deviation_kwh": 0.0,
        "bess_terminal_soc_tolerance_kwh": 1e-6,
    }
    validation_metrics.update(
        {
            key: 0
            for key in (
                "unassigned_trip_count",
                "duplicate_trip_count",
                "vehicle_time_overlap_count",
                "infeasible_transition_count",
                "ev_soc_lower_violation_count",
                "ev_soc_upper_violation_count",
                "ev_soc_violation_count",
                "bess_soc_lower_violation_count",
                "bess_soc_upper_violation_count",
                "bess_soc_violation_count",
                "contract_power_violation_count",
                "charger_concurrency_violation_count",
            )
        }
    )
    return {
        "case_name": case_name,
        "scenario_id": scenario_id,
        "prepared_input_id": f"prepared-{service_date}",
        "prepared_input_sha256": f"sha-{service_date}",
        "service_date": service_date,
        "experiment_hash": f"experiment-{service_date}",
        "git_sha": "95ade40",
        "git_dirty": False,
        "phase": "phase3_two_stage",
        "time_limit_sec": 1500,
        "mip_gap": 0.1,
        "random_seed": 42,
        "postsolve_repair_enabled": False,
        "vehicle_soc_semantics": "slot_start",
        "weather_operation_policy_enabled": True,
        "weather_configuration": {
            "weather_mode": "actual_date_profile",
            "weather_factor_scalar": 1.0,
            "weather_operation_mode": weather_operation_mode,
            "enable_weather_operation_policy": True,
            "pv_profile_id": f"tsurumaki_{service_date}_60min",
            "weather_proxy_forecast_path": f"weather/{service_date}.json",
            "weather_proxy_station_id": "44132",
            "solcast_typical_weather_class": "auto",
            "random_seed": 42,
        },
        "weather_operation_profile": {
            "operation_mode": weather_operation_mode,
            "final_soc_floor_percent": None,
            "final_soc_target_percent": None,
            "final_soc_target_tolerance_percent": None,
            "initial_soc_mode": "unchanged",
            "initial_soc_min_percent": None,
            "initial_soc_max_percent": None,
            "midday_charge_priority": None,
            "bev_duty_bias": None,
            "ice_backup_bias": None,
            "grid_risk_penalty_multiplier": None,
            "pv_marginal_charge_cost_yen_per_kwh": 0.0,
        },
        "trip_count": 264,
        "fleet": {"BEV": 35, "ICE": 25},
        "timestep_min": 15,
        "price_slot_count": 96,
        "planning_horizon_hours": 24.0,
        "energy_horizon_duration_min": 1440,
        "milp_max_successors_per_trip": 0,
        "successor_pruning_enabled": False,
        "research_discretization": {
            "timestep_min": 15,
            "milp_max_successors_per_trip": 0,
            "successor_pruning_enabled": False,
        },
        "trip_distance_audit": {
            "trip_count": 264,
            "nonpositive_trip_count": 0,
            "prepared_distance_source_kind_counts": {
                "trip.haversine_distance": 264
            },
        },
        "clock_hour_grid_price_yen_per_kwh": {"8": 18.0, "16": 22.0},
        "demand_charge_monthly_yen_per_kw": 1200.0,
        "demand_charge_horizon_yen_per_kw": 40.0,
        "depot_import_limit_kw_by_depot": {"tsurumaki": 1000.0},
        "depot_import_limit_semantics": "nonpositive_means_no_finite_contract_limit",
        "contract_overage_penalty_yen_per_kwh": 0.0,
        "diesel_price_yen_per_l": 150.0,
        "co2_price_yen_per_kg": 1.0,
        "vehicle_usage_cost_jpy_per_used_bus": 20000.0,
        "cost_component_flags": {"vehicle_usage_cost": True},
        "objective_weights": {
            "energy": 1.0,
            "fuel": 1.0,
            "demand": 1.0,
            "vehicle": 1.0,
            "vehicle_usage": 1.0,
            "degradation": 1.0,
        },
        "grid_co2_kg_per_kwh": {"0": 0.4},
        "pv_marginal_charge_cost_yen_per_kwh": 0.0,
        "pv_curtail_penalty_yen_per_kwh": 0.0,
        "initial_soc_policy": "actual_vehicle_inventory",
        "initial_soc_source": "prepared_input",
        "initial_soc_input_hash": "soc-hash",
        "initial_soc_by_vehicle": {"bev-1": 80.0},
        "terminal_soc_policy": {
            "post_return_soc_target_enabled": True,
            "final_soc_floor_percent": 20.0,
        },
        "research_fragment_policy": {
            "policy": "single_continuous_duty",
            "effective": {"daily_fragment_limit": 1},
        },
        "charger_configuration": [{"charger_id": "charger-1", "power_kw": 90.0}],
        "charger_configuration_hash": "charger-hash",
        "depot_energy_assets": {
            "tsurumaki": {
                "pv_enabled": True,
                "pv_case_id": pv_case_id,
                "pv_capacity_kw": 101.5,
                "pv_generation_kwh": pv_generation_kwh,
                "pv_generation_hash": pv_hash,
                "bess_enabled": True,
                "bess_energy_kwh": 600.0,
                "bess_power_kw": 300.0,
                "bess_initial_soc_kwh": 300.0,
                "bess_soc_min_kwh": 120.0,
                "bess_soc_max_kwh": 480.0,
                "allow_pv_to_bess": True,
                "allow_grid_to_bess": False,
                "allow_bess_to_bus": True,
                "bess_terminal_soc_target_kwh": 300.0,
            }
        },
        "vehicle_input_hash": "vehicle-hash",
        "trip_input_hash": "trip-hash",
        "stage1_energy_envelope_constraint_count": 100,
        "stage1_energy_envelope_semantics": "optimistic_vehicle_local",
        "stage1_time_indexed_soc_relaxation_constraint_count": 200,
        "stage1_time_indexed_soc_relaxation_semantics": (
            "location_aware_cumulative_soc_with_single_vehicle_slot_"
            "charge_cap_necessary_condition"
        ),
        "stage1_energy_cost_proxy_configuration": {
            "enabled": True,
            "semantics": (
                "aggregate_home_depot_source_energy_lower_bound_"
                "without_charging_time_or_demand_charge"
            ),
            "charge_efficiency": 0.95,
            "grid_unit_cost_yen_per_kwh": 18.0,
            "pv_unit_cost_yen_per_kwh": 0.0,
        },
        "stage1_energy_cost_proxy_weather_input": {
            "pv_available_kwh_by_depot": {"tsurumaki": pv_generation_kwh}
        },
        "stage1_energy_cost_proxy_result": {
            "external_charge_input_kwh": 600.0,
            "pv_to_bus_kwh": min(pv_generation_kwh, 600.0),
            "grid_to_bus_kwh": max(600.0 - pv_generation_kwh, 0.0),
            "bess_initial_to_bus_kwh": 0.0,
            "objective_jpy": max(600.0 - pv_generation_kwh, 0.0) * 18.0,
        },
        "solver_status": "feasible",
        "feasible": True,
        "trip_count_served": 264,
        "trip_count_unserved": 0,
        "used_vehicle_count": 32,
        "max_fragments_observed": 1,
        "stage1_solver_status": "time_limit",
        "stage2_solver_status": "optimal",
        "stage1_objective": 708727.0,
        "stage2_objective": total_cost - 700000.0,
        "stage1_best_bound": 560000.0,
        "stage1_mip_gap_percent": 20.0,
        "stage1_runtime_seconds": 750.0,
        "stage2_runtime_seconds": 0.1,
        "research_run_accepted": True,
        "research_feasibility_eligible": True,
        "research_cost_kpi_eligible": True,
        "research_accounting_cost_eligible": True,
        "research_cost_optimality_eligible": False,
        "solver_objective_matches_accounting_total": False,
        "accounting_total_cost_jpy": total_cost,
        "cost_comparison_scope": (
            "feasible_schedule_accounting_not_global_total_cost_optimum"
        ),
        "validation_metrics": validation_metrics,
        "flows_kwh_or_kw": {
            "grid_to_bus_kwh": grid_import_kwh,
            "grid_to_bess_kwh": 0.0,
            "pv_to_bus_kwh": pv_generation_kwh * 0.6,
            "pv_to_bess_kwh": pv_generation_kwh * 0.4,
            "bess_to_bus_kwh": pv_generation_kwh * 0.3,
            "pv_generated_kwh": pv_generation_kwh,
            "pv_curtailed_kwh": 0.0,
            "grid_import_kwh": grid_import_kwh,
            "peak_grid_kw": grid_import_kwh / 10.0,
        },
        "costs_jpy": {
            "total_cost": total_cost,
            "electricity_cost": total_cost - 700000.0,
            "grid_purchase_cost": total_cost - 700000.0,
            "pv_to_bus_cost_jpy": 0.0,
            "pv_to_bess_cost_jpy": 0.0,
            "pv_curtail_cost_jpy": 0.0,
            "bess_to_bus_cost_jpy": 0.0,
            "demand_cost": 0.0,
            "fuel_cost": 700000.0,
            "co2_cost": 0.0,
            "vehicle_usage_cost": 0.0,
        },
    }


def _valid_pair() -> tuple[dict, dict]:
    sunny = _summary(
        case_name="sunny",
        scenario_id="sunny-id",
        service_date="2025-08-05",
        pv_generation_kwh=614.7,
        pv_case_id="pv-sunny",
        pv_hash="pv-hash-sunny",
        weather_operation_mode="aggressive",
        total_cost=717249.0,
        grid_import_kwh=22.9,
    )
    rain = _summary(
        case_name="rain",
        scenario_id="rain-id",
        service_date="2025-08-10",
        pv_generation_kwh=101.1,
        pv_case_id="pv-rain",
        pv_hash="pv-hash-rain",
        weather_operation_mode="conservative",
        total_cost=727636.0,
        grid_import_kwh=519.4,
    )
    return sunny, rain


def test_accepts_only_weather_pv_differences_and_reports_effects() -> None:
    sunny, rain = _valid_pair()

    comparison = build_weather_comparison(sunny, rain)

    assert comparison["comparison_accepted"] is True
    assert comparison["effects"]["costs_jpy"]["total_cost"]["rain_minus_sunny"] == 10387.0
    assert comparison["effects"]["flows_kwh_or_kw"]["grid_import_kwh"][
        "rain_minus_sunny"
    ] == pytest.approx(496.5)
    assert comparison["effects"]["stage1_energy_cost_proxy"]["metrics"][
        "grid_to_bus_kwh"
    ]["rain_minus_sunny"] == pytest.approx(498.9)
    assert comparison["allowed_weather_input_differences"]["weather_configuration"][
        "weather_operation_mode"
    ] == {"sunny": "aggressive", "rain": "conservative"}
    report = render_markdown_report(comparison)
    assert "総コストの大域最適性は主張しません" in report
    assert "会計総額へ重ねて加算してはいけません" in report
    assert "Stage 1 集約充電費用代理" in report


def test_rejects_a_different_fixed_tou_price() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["clock_hour_grid_price_yen_per_kwh"]["8"] = 99.0

    with pytest.raises(
        ComparisonContractError,
        match="Fixed control differs at clock_hour_grid_price_yen_per_kwh",
    ):
        build_weather_comparison(sunny, rain)


def test_rejects_a_different_stage1_energy_proxy_policy() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["stage1_energy_cost_proxy_configuration"][
        "grid_unit_cost_yen_per_kwh"
    ] = 19.0

    with pytest.raises(
        ComparisonContractError,
        match="stage1_energy_cost_proxy_configuration",
    ):
        build_weather_comparison(sunny, rain)


def test_rejects_unaccepted_result_before_comparing_costs() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["research_run_accepted"] = False

    with pytest.raises(
        ComparisonContractError,
        match="rain.research_run_accepted must be true",
    ):
        build_weather_comparison(sunny, rain)


def test_rejects_accounting_cost_without_accounting_eligibility() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["research_accounting_cost_eligible"] = False

    with pytest.raises(
        ComparisonContractError,
        match="rain.research_accounting_cost_eligible must be true",
    ):
        build_weather_comparison(sunny, rain)


def test_rejects_two_stage_result_claiming_cost_optimality() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["research_cost_optimality_eligible"] = True

    with pytest.raises(
        ComparisonContractError,
        match="rain.research_cost_optimality_eligible must be false",
    ):
        build_weather_comparison(sunny, rain)


def test_rejects_an_unclassified_weather_configuration_change() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["weather_configuration"]["weather_factor_scalar"] = 0.5

    with pytest.raises(
        ComparisonContractError,
        match="Fixed control differs at weather_configuration.weather_factor_scalar",
    ):
        build_weather_comparison(sunny, rain)


def test_rejects_a_changed_effective_weather_profile_knob() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["weather_operation_profile"]["midday_charge_priority"] = 1.0

    with pytest.raises(
        ComparisonContractError,
        match="weather_operation_profile.midday_charge_priority",
    ):
        build_weather_comparison(sunny, rain)


def test_rejects_smoke_run_or_inconsistent_cost_components() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["time_limit_sec"] = 20

    with pytest.raises(ComparisonContractError, match="rain.time_limit_sec"):
        build_weather_comparison(sunny, rain)

    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["costs_jpy"]["fuel_cost"] += 1.0

    with pytest.raises(
        ComparisonContractError,
        match="rain costs_jpy components differ from total_cost",
    ):
        build_weather_comparison(sunny, rain)


def test_rejects_a_different_contract_power_limit() -> None:
    sunny, rain = _valid_pair()
    rain = deepcopy(rain)
    rain["depot_import_limit_kw_by_depot"]["tsurumaki"] = 500.0

    with pytest.raises(
        ComparisonContractError,
        match="Fixed contract-power control differs at depot_import_limit_kw_by_depot",
    ):
        build_weather_comparison(sunny, rain)
