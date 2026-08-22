from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from scripts.audit_small_integrated_weather_milp import (
    _available_vehicle_subset,
    _align_objective_with_accounting,
    _day_spanning_trip_subset,
    _five_minute_sensitivity_comparison,
    _is_integrated_exact_oracle_case,
    _restore_prepared_weather_comparison_contract,
    _sensitivity_summary,
)
from src.optimization.common.cost_components import normalize_cost_component_flags


def test_day_spanning_trip_subset_includes_both_service_edges() -> None:
    trips = tuple(
        SimpleNamespace(trip_id=f"t{index}", departure_min=index * 10, arrival_min=index * 10 + 5)
        for index in range(10)
    )

    selected = _day_spanning_trip_subset(SimpleNamespace(trips=trips), 4)

    assert [trip.trip_id for trip in selected] == ["t0", "t3", "t6", "t9"]


def test_vehicle_subset_can_isolate_ice_accounting_path() -> None:
    vehicles = (
        SimpleNamespace(vehicle_id="bev-1", vehicle_type="BEV", available=True),
        SimpleNamespace(vehicle_id="ice-2", vehicle_type="ICE", available=True),
        SimpleNamespace(vehicle_id="ice-1", vehicle_type="ICE", available=True),
    )

    selected = _available_vehicle_subset(
        SimpleNamespace(vehicles=vehicles),
        per_type=2,
        vehicle_types=("ICE",),
    )

    assert [vehicle.vehicle_id for vehicle in selected] == ["ice-1", "ice-2"]


def test_small_oracle_restores_explicit_prepared_counterfactual_contract() -> None:
    scenario = {
        "simulation_config": {
            "comparison_type": None,
            "comparison_role": "pv_curve_counterfactual",
        }
    }
    prepared = {
        "simulation_config": {
            "comparison_type": "same_service_date_pv_counterfactual",
            "comparison_role": "pv_curve_counterfactual",
            "counterfactual_pv_source_date": "2025-08-10",
            "weather_observation_date": "2025-08-10",
        }
    }

    _restore_prepared_weather_comparison_contract(scenario, prepared)

    assert scenario["simulation_config"]["comparison_type"] == (
        "same_service_date_pv_counterfactual"
    )
    assert scenario["simulation_config"]["weather_observation_date"] == (
        "2025-08-10"
    )


def test_small_oracle_rejects_conflicting_current_counterfactual_contract() -> None:
    scenario = {"simulation_config": {"comparison_type": "actual_service_day"}}
    prepared = {
        "simulation_config": {
            "comparison_type": "same_service_date_pv_counterfactual"
        }
    }

    with pytest.raises(ValueError, match="contract conflicts"):
        _restore_prepared_weather_comparison_contract(scenario, prepared)


def test_small_oracle_disables_non_accounting_preference_terms() -> None:
    @dataclass(frozen=True)
    class ProblemStub:
        metadata: dict

    problem = ProblemStub(
        metadata={
            "cost_component_flags": {
                "electricity_cost": True,
                "grid_to_bus_priority_penalty": True,
                "grid_to_bess_priority_penalty": True,
            }
        }
    )

    aligned = _align_objective_with_accounting(problem)

    flags = aligned.metadata["cost_component_flags"]
    assert flags["electricity_cost"] is True
    assert flags["grid_to_bus_priority_penalty"] is False
    assert flags["grid_to_bess_priority_penalty"] is False
    assert flags["opportunistic_topup_deficit_penalty"] is False
    normalized_flags = normalize_cost_component_flags(flags)
    assert normalized_flags["opportunistic_topup_deficit_penalty"] is False
    assert aligned.metadata["small_integrated_objective_semantics"] == (
        "validated_accounting_cost_components_only"
    )
    assert aligned.metadata["bev_terminal_soc_policy"] == "return_to_initial"


def test_integrated_oracle_gate_fails_closed_on_accounting_residual() -> None:
    case = {
        "phase": "phase4_integrated",
        "feasible": True,
        "trip_count_unserved": 0,
        "solver_status": "optimal",
        "raw_plan_solver_status": "optimal",
        "supports_integrated_exact_milp": True,
        "final_gap_ratio": 0.0,
        "integrated_actual_cost_objective_requested": True,
        "integrated_actual_cost_contract_applied": True,
        "objective_is_actual_cost": True,
        "objective_matches_accounting": True,
        "ev_energy_inventory_balanced": True,
        "validation_metrics": {"all_required_validation_checks_passed": True},
    }

    assert _is_integrated_exact_oracle_case(case) is True
    case["objective_matches_accounting"] = False
    assert _is_integrated_exact_oracle_case(case) is False


def test_integrated_oracle_gate_requires_actual_cost_contract() -> None:
    case = {
        "phase": "phase4_integrated",
        "feasible": True,
        "trip_count_unserved": 0,
        "solver_status": "optimal",
        "raw_plan_solver_status": "optimal",
        "supports_integrated_exact_milp": True,
        "final_gap_ratio": 0.0,
        "integrated_actual_cost_objective_requested": True,
        "integrated_actual_cost_contract_applied": True,
        "objective_is_actual_cost": True,
        "objective_matches_accounting": True,
        "ev_energy_inventory_balanced": True,
        "validation_metrics": {"all_required_validation_checks_passed": True},
    }

    assert _is_integrated_exact_oracle_case(case) is True
    for required_field in (
        "integrated_actual_cost_objective_requested",
        "integrated_actual_cost_contract_applied",
        "objective_is_actual_cost",
    ):
        invalid = dict(case)
        invalid[required_field] = False
        assert _is_integrated_exact_oracle_case(invalid) is False


def test_integrated_oracle_accepts_optimal_multiobjective_without_scalar_gap() -> None:
    case = {
        "phase": "phase4_integrated",
        "feasible": True,
        "trip_count_unserved": 0,
        "solver_status": "optimal",
        "raw_plan_solver_status": "optimal",
        "supports_integrated_exact_milp": True,
        "final_gap_ratio": None,
        "integrated_actual_cost_objective_requested": True,
        "integrated_actual_cost_contract_applied": True,
        "objective_is_actual_cost": True,
        "objective_matches_accounting": True,
        "ev_energy_inventory_balanced": True,
        "validation_metrics": {"all_required_validation_checks_passed": True},
    }

    assert _is_integrated_exact_oracle_case(case) is True

    case["solver_status"] = "time_limit"
    assert _is_integrated_exact_oracle_case(case) is False


def test_integrated_oracle_verifies_declared_lexicographic_primary() -> None:
    case = {
        "phase": "phase4_integrated",
        "feasible": True,
        "trip_count_unserved": 0,
        "solver_status": "optimal",
        "raw_plan_solver_status": "optimal",
        "supports_integrated_exact_milp": True,
        "final_gap_ratio": None,
        "integrated_actual_cost_objective_requested": True,
        "integrated_actual_cost_contract_applied": True,
        "objective_is_actual_cost": True,
        "objective_matches_accounting": True,
        "ev_energy_inventory_balanced": True,
        "validation_metrics": {"all_required_validation_checks_passed": True},
        "objective_preset": "research_lexicographic_v1",
        "objective_hierarchy": [
            "coverage_if_partial",
            "used_vehicle_days",
            "canonical_operating_cost",
            "inter_trip_deadhead_km",
            "charge_session_count",
        ],
        "used_vehicle_count": 2,
        "raw_solver_primary_objective_value": 2.0,
    }

    assert _is_integrated_exact_oracle_case(case) is True
    case["raw_solver_primary_objective_value"] = 40_000.0
    assert _is_integrated_exact_oracle_case(case) is False


def test_five_minute_comparison_requires_both_exact_integrated_cases() -> None:
    def exact_case(timestep_min: int, cost: float) -> dict:
        return {
            "analysis_label": "primary",
            "phase": "phase4_integrated",
            "timestep_min": timestep_min,
            "feasible": True,
            "trip_count_unserved": 0,
            "solver_status": "optimal",
            "raw_plan_solver_status": "optimal",
            "supports_integrated_exact_milp": True,
            "final_gap_ratio": 0.0,
            "integrated_actual_cost_objective_requested": True,
            "integrated_actual_cost_contract_applied": True,
            "objective_is_actual_cost": True,
            "objective_matches_accounting": True,
            "ev_energy_inventory_balanced": True,
            "validation_metrics": {"all_required_validation_checks_passed": True},
            "accounted_total_cost_jpy": cost,
            "used_vehicle_count": 2,
            "used_vehicle_count_by_type": {"BEV": 2},
            "served_trip_count_by_vehicle_type": {"BEV": 10},
        }

    comparison = _five_minute_sensitivity_comparison(
        [exact_case(15, 40_000.0), exact_case(5, 40_100.0)]
    )

    assert comparison["comparison_available"] is True
    assert comparison["both_exact_oracle_eligible"] is True
    assert comparison["five_minus_fifteen_cost_jpy"] == 100.0
    assert comparison["used_vehicle_type_mix_matches"] is True

    failed_five_minute = exact_case(5, 40_100.0)
    failed_five_minute["objective_matches_accounting"] = False
    comparison = _five_minute_sensitivity_comparison(
        [exact_case(15, 40_000.0), failed_five_minute]
    )
    assert comparison["comparison_available"] is True
    assert comparison["both_exact_oracle_eligible"] is False


def test_sensitivity_summary_reports_full_cost_range_and_completeness() -> None:
    cases = [
        {
            "analysis_label": "target",
            "random_seed": 17,
            "time_limit_sec": 5,
            "feasible": True,
            "trip_count_unserved": 0,
            "accounted_total_cost_jpy": 100.0,
        },
        {
            "analysis_label": "target",
            "random_seed": 42,
            "time_limit_sec": 5,
            "feasible": True,
            "trip_count_unserved": 0,
            "accounted_total_cost_jpy": 103.0,
        },
        {"analysis_label": "other", "accounted_total_cost_jpy": 999.0},
    ]

    summary = _sensitivity_summary(cases, analysis_label="target")

    assert summary["case_count"] == 2
    assert summary["all_cases_feasible_and_complete"] is True
    assert summary["minimum_accounted_total_cost_jpy"] == 100.0
    assert summary["maximum_accounted_total_cost_jpy"] == 103.0
    assert summary["accounted_total_cost_range_jpy"] == 3.0
