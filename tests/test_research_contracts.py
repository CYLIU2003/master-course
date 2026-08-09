from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from bff.routers.optimization import _solver_settings_payload
from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.accounting.aggregators import build_accounting_summary
from src.optimization.common.problem import AssignmentPlan
from bff.services.optimization_run.canonical_graph import canonical_output_base_date


def _trip(trip_id: str, departure: str, arrival: str) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="r1",
        origin="A",
        destination="B",
        departure_time=departure,
        arrival_time=arrival,
        distance_km=1.0,
        allowed_vehicle_types=("BEV",),
    )


def test_assignment_plan_uses_chronological_duty_order_not_trip_id() -> None:
    late = VehicleDuty("duty-10", "BEV", (DutyLeg(_trip("trip-1", "10:00", "10:30")),))
    early = VehicleDuty("duty-2", "BEV", (DutyLeg(_trip("trip-9", "08:00", "08:30")),))
    plan = AssignmentPlan(
        duties=(late, early),
        metadata={"duty_vehicle_map": {"duty-10": "veh-1", "duty-2": "veh-1"}},
    )

    assert plan.vehicle_paths() == {"veh-1": ("trip-9", "trip-1")}


def test_assignment_plan_orders_after_midnight_relative_to_horizon_start() -> None:
    late = VehicleDuty("duty-late", "BEV", (DutyLeg(_trip("trip-late", "23:30", "23:50")),))
    after_midnight = VehicleDuty(
        "duty-midnight",
        "BEV",
        (DutyLeg(_trip("trip-midnight", "00:10", "00:25")),),
    )
    early_after_midnight = VehicleDuty(
        "duty-early",
        "BEV",
        (DutyLeg(_trip("trip-early", "00:30", "00:45")),),
    )
    plan = AssignmentPlan(
        duties=(early_after_midnight, late, after_midnight),
        metadata={
            "horizon_start": "05:00",
            "duty_vehicle_map": {
                "duty-late": "veh-1",
                "duty-midnight": "veh-1",
                "duty-early": "veh-1",
            },
        },
    )

    assert plan.vehicle_paths() == {
        "veh-1": ("trip-late", "trip-midnight", "trip-early")
    }


def test_solver_gap_is_null_without_incumbent_and_phase_is_explicit() -> None:
    payload = _solver_settings_payload(
        time_limit_seconds_requested=300,
        mip_gap_requested=0.1,
        solver_metadata={
            "final_gap": 0.0,
            "has_feasible_incumbent": False,
            "requested_phase": "phase3_two_stage",
            "resolved_phase": "phase3_two_stage",
            "executed_phase": "phase3_two_stage",
        },
    )

    assert payload["mip_gap_achieved_ratio"] is None
    assert payload["mip_gap_achieved_percent"] is None
    assert payload["requested_phase"] == "phase3_two_stage"
    assert payload["resolved_phase"] == "phase3_two_stage"
    assert payload["executed_phase"] == "phase3_two_stage"


def test_solver_settings_preserves_enabled_bev_frontier_control() -> None:
    payload = _solver_settings_payload(
        time_limit_seconds_requested=3600,
        mip_gap_requested=0.1,
        solver_metadata={
            "stage1_bev_frontier_enabled": True,
        },
    )

    assert payload["stage1_bev_frontier_enabled"] is True


def test_solver_settings_uses_integrated_certified_gap_without_hiding_raw_gap() -> None:
    payload = _solver_settings_payload(
        time_limit_seconds_requested=3_600,
        mip_gap_requested=0.001,
        solver_metadata={
            "has_feasible_incumbent": True,
            "best_bound": 0.0,
            "final_gap": 1.0,
            "raw_best_bound": 0.0,
            "raw_mip_gap_ratio": 1.0,
            "certified_best_bound": 640_000.0,
            "certified_mip_gap_ratio": 0.0005,
            "certified_mip_gap_semantics": (
                "maximum_of_gurobi_and_independent_bound"
            ),
        },
    )

    assert payload["mip_gap_achieved_ratio"] == pytest.approx(1.0)
    assert payload["gurobi_raw_mip_gap_ratio"] == pytest.approx(1.0)
    assert payload["certified_best_bound"] == pytest.approx(640_000.0)
    assert payload["certified_mip_gap_ratio"] == pytest.approx(0.0005)
    assert payload["mip_gap_target_met"] is True


def test_solver_settings_persists_integrated_search_profile() -> None:
    search_profile = {
        "schema_version": "phase4_integrated_search_profile_v1",
        "phase_count_executed": 1,
        "phases": [
            {
                "phase": "uninterrupted_incumbent_and_bound_search",
                "mip_focus": 1,
            },
        ],
    }
    payload = _solver_settings_payload(
        time_limit_seconds_requested=3_600,
        mip_gap_requested=0.001,
        solver_metadata={
            "integrated_mip_focus": 1,
            "integrated_heuristics": 0.5,
            "integrated_symmetry": -1,
            "integrated_search_profile": search_profile,
            "integrated_analytical_objective_lower_bound": 640_000.0,
            "integrated_vehicle_usage_analytical_lower_bound": 640_000.0,
            "integrated_analytical_weather_energy_fuel_lower_bound": 0.0,
            "integrated_analytical_objective_floor_constraint_count": 1,
            "integrated_analytical_objective_floor_certificate_eligible": True,
            "integrated_analytical_objective_floor_blockers": [],
            "integrated_verified_start_search_bounds": {
                "eligible": True,
                "objective_upper_bound_jpy": 666_164.001,
                "vehicle_day_upper_bound": 33,
            },
            "integrated_verified_start_objective_cap_constraint_count": 1,
            "integrated_verified_start_vehicle_day_cap_constraint_count": 1,
            "integrated_verified_start_search_bound_semantics": (
                "preserves_seed_and_all_improving_solutions"
            ),
            "integrated_identical_vehicle_groups": [
                ["ice-001", "ice-002"]
            ],
            "integrated_identical_vehicle_group_count": 1,
            "integrated_identical_vehicle_activation_prefix_constraint_count": 1,
        },
    )

    assert payload["integrated_mip_focus"] == 1
    assert payload["integrated_heuristics"] == pytest.approx(0.5)
    assert payload["integrated_symmetry"] == -1
    assert payload["integrated_search_profile"] == search_profile
    assert payload[
        "integrated_analytical_objective_lower_bound"
    ] == pytest.approx(640_000.0)
    assert payload[
        "integrated_analytical_objective_floor_constraint_count"
    ] == 1
    assert payload[
        "integrated_analytical_objective_floor_certificate_eligible"
    ] is True
    assert payload["integrated_verified_start_search_bounds"][
        "vehicle_day_upper_bound"
    ] == 33
    assert payload[
        "integrated_verified_start_objective_cap_constraint_count"
    ] == 1
    assert payload[
        "integrated_verified_start_vehicle_day_cap_constraint_count"
    ] == 1
    assert payload["integrated_identical_vehicle_group_count"] == 1
    assert payload[
        "integrated_identical_vehicle_activation_prefix_constraint_count"
    ] == 1


def test_solver_settings_persists_phase4_seed_and_total_time_budget() -> None:
    payload = _solver_settings_payload(
        time_limit_seconds_requested=3600,
        mip_gap_requested=0.05,
        solver_metadata={
            "phase4_phase3_seed_audit": {
                "requested": True,
                "seed_time_limit_sec": 600,
                "seed_wall_clock_budget_sec": 700,
                "seed_wall_runtime_sec": 650.0,
                "seed_model_build_overhead_allowance_sec": 100,
                "seed_stage1_time_limit_sec": 480,
                "seed_stage2_time_limit_sec": 120,
                "seed_stage1_stage2_candidate_limit": 10,
                "seed_stage1_stage2_candidate_evaluation_order": (
                    "candidate_priority_cost_ascending_then_candidate_hash"
                ),
                "seed_stage1_stage2_candidate_evaluation_initial_budget_sec": 25.0,
                "seed_stage1_composition_search_radius": 2,
                "seed_search_directionality": (
                    "primary_plus_symmetric_adjacent_compositions"
                ),
                "seed_bev_frontier_enabled": False,
                "integrated_seed_recourse_preflight_enabled": True,
                "integrated_seed_recourse_time_limit_sec": 300,
                "total_solver_time_budget_sec": 4500,
            },
            "integrated_warm_start_audit": {
                "dispatch_fixed_recourse_requested": True,
                "integrated_dispatch_fixed_recourse_feasible": True,
            },
        },
    )

    assert payload["phase4_phase3_seed_enabled"] is True
    assert payload["phase4_phase3_seed_time_limit_sec"] == 600
    assert payload["phase4_phase3_seed_wall_clock_budget_sec"] == 700
    assert payload["phase4_phase3_seed_wall_runtime_sec"] == pytest.approx(
        650.0
    )
    assert payload[
        "phase4_phase3_seed_model_build_overhead_allowance_sec"
    ] == 100
    assert payload["phase4_phase3_seed_stage1_time_limit_sec"] == 480
    assert payload["phase4_phase3_seed_stage2_time_limit_sec"] == 120
    assert payload["phase4_phase3_seed_candidate_limit"] == 10
    assert payload["phase4_phase3_seed_candidate_evaluation_order"] == (
        "candidate_priority_cost_ascending_then_candidate_hash"
    )
    assert payload[
        "phase4_phase3_seed_candidate_evaluation_initial_budget_sec"
    ] == pytest.approx(25.0)
    assert payload["phase4_phase3_seed_composition_search_radius"] == 2
    assert payload["phase4_phase3_seed_bev_frontier_enabled"] is False
    assert payload[
        "phase4_integrated_seed_recourse_preflight_enabled"
    ] is True
    assert payload["phase4_integrated_seed_recourse_time_limit_sec"] == 300
    assert payload[
        "phase4_integrated_seed_recourse_preflight_requested"
    ] is True
    assert payload[
        "phase4_integrated_seed_recourse_preflight_feasible"
    ] is True
    assert payload["phase4_total_solver_time_budget_sec"] == 4500


def test_infeasible_accounting_has_distinct_cost_fields_and_null_validated_cost() -> None:
    summary = build_accounting_summary(
        vehicle_rows=(),
        energy_rows=(),
        metadata={
            "scenario_id": "s1",
            "run_id": "r1",
            "service_date": date(2025, 8, 10).isoformat(),
            "solver_status": "INFEASIBLE",
            "objective_value": 1234.0,
            "validated_feasible": False,
        },
    )

    assert summary["solver_objective_value"] == 1234.0
    assert summary["accounting_total_cost_jpy"] == 0.0
    assert summary["validated_operating_cost_jpy"] is None


def test_research_output_date_never_falls_back_to_execution_date() -> None:
    with pytest.raises(ValueError, match="research service_date"):
        canonical_output_base_date(
            SimpleNamespace(metadata={"research_run": True, "service_date": "not-a-date"}),
            None,
        )


def test_phase2_accounting_cost_is_not_validated_operating_cost() -> None:
    summary = build_accounting_summary(
        vehicle_rows=(),
        energy_rows=(),
        metadata={
            "solver_status": "PHASE2_ASSIGNMENT_FEASIBLE",
            "phase": "phase2_assignment_only",
            "validated_feasible": True,
            "objective_value": 100.0,
        },
    )

    assert summary["validated_operating_cost_jpy"] is None
