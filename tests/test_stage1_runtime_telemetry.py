from __future__ import annotations

from types import SimpleNamespace

from bff.routers.optimization import (
    RunOptimizationBody,
    _apply_interactive_bev_utilization_policy,
    _apply_interactive_research_contract,
    _apply_interactive_bev_terminal_soc_policy,
    _interactive_runtime_controls_payload,
    _research_claim_scope_payload,
    _solver_settings_payload,
)


def test_solver_settings_separate_raw_gap_from_certified_gap_and_stop_rule() -> None:
    settings = _solver_settings_payload(
        time_limit_seconds_requested=1_500,
        mip_gap_requested=0.10,
        solver_metadata={
            "has_feasible_incumbent": True,
            "achieved_mip_gap": 0.092,
            "stage1_solver_status": "objective_limit",
            "stage1_termination_reason": "best_obj_stop",
            "stage1_best_obj_stop_enabled": True,
            "stage1_best_obj_stop_applied": True,
            "stage1_certified_gap_stop_threshold": 711_111.11,
            "stage1_certified_gap_stop_triggered": True,
            "stage1_gurobi_raw_best_bound": 0.0,
            "stage1_gurobi_raw_mip_gap_ratio": 1.0,
            "stage1_certified_best_bound": 640_000.0,
            "stage1_certified_mip_gap_ratio": 0.092,
            "gurobi_threads": 1,
        },
    )

    assert settings["stage1_termination_reason"] == "best_obj_stop"
    assert settings["stage1_gurobi_raw_mip_gap_ratio"] == 1.0
    assert settings["stage1_certified_mip_gap_ratio"] == 0.092
    assert settings["runtime_comparison_eligible"] is False
    assert settings["gurobi_threads"] == 1


def test_manual_pv_only_claim_scope_rejects_weather_dispatch_and_runtime_claims() -> None:
    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "solver_metadata": {
                "research_run": False,
                "research_run_accepted": False,
                "supports_integrated_exact_milp": False,
                "optimization_structure": "two_stage",
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={
            "runtime_comparison_eligible": False,
            "stage1_best_obj_stop_applied": True,
        },
        weather_policy={
            "enabled": True,
            "audit": {"decision_policy": {"policy_scope": "pv_curve_only"}},
        },
        rolling_execution={"status": "not_executed"},
    )

    assert claim_scope["result_label"] == (
        "exploratory_pv_supply_sensitivity_not_weather_adaptive_dispatch"
    )
    assert claim_scope["weather_adaptive_dispatch_claim_eligible"] is False
    assert "wall_clock_runtime_comparison" in claim_scope["disallowed_claims"]
    assert "weather_adaptive_dispatch_or_charging_policy" in claim_scope[
        "disallowed_claims"
    ]


def test_single_manual_run_cannot_claim_runtime_comparison_after_disabling_stop_rule() -> None:
    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "solver_metadata": {
                "research_run": False,
                "research_run_accepted": False,
                "supports_integrated_exact_milp": False,
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={
            "runtime_comparison_eligible": True,
            "stage1_best_obj_stop_applied": False,
        },
        weather_policy={"enabled": False},
        rolling_execution={"status": "not_executed"},
    )

    assert claim_scope["runtime_comparison_claim_eligible"] is False
    assert "wall_clock_runtime_comparison" in claim_scope["disallowed_claims"]
    assert claim_scope["evidence"]["stage1_stop_rule_runtime_control_eligible"] is True


def test_teacher_release_preserves_vehicle_inventory_blocker() -> None:
    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "run_profile": "day_ahead_and_hourly_rolling",
            "solver_metadata": {
                "research_run": True,
                "research_run_accepted": False,
                "research_submission_git_provenance_eligible": True,
                "research_acceptance_checks": {
                    "research_vehicle_inventory_contract": False,
                },
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={},
        weather_policy={"enabled": False},
        rolling_execution={
            "status": "executed_and_accepted",
            "rolling_execution_minutes": 60,
        },
    )

    assert claim_scope["teacher_release_status"] == "BLOCKED"
    assert "research_vehicle_inventory_contract" in claim_scope[
        "teacher_release_failed_checks"
    ]
    assert claim_scope["research_submission_ready"] is False


def test_interactive_run_defaults_and_provenance_record_server_enforcement() -> None:
    request = RunOptimizationBody()
    assert request.stage1_best_obj_stop_enabled is False
    assert request.gurobi_threads == 1
    assert request.run_profile == "day_ahead_and_hourly_rolling"
    assert request.run_hourly_rolling is True
    assert request.rolling_execution_minutes == 60
    assert request.require_all_available_bevs is False

    controls = _interactive_runtime_controls_payload(
        requested_stage1_best_obj_stop_enabled=True,
        requested_gurobi_threads=8,
    )
    assert controls["enforced"] is True
    assert controls["override_applied"] is True
    assert controls["effective"] == {
        "stage1_best_obj_stop_enabled": False,
        "gurobi_threads": 1,
    }


def test_all_available_bev_policy_reuses_minimum_use_constraint() -> None:
    problem = SimpleNamespace(
        vehicles=(
            SimpleNamespace(
                vehicle_id="bev-1", vehicle_type="BEV", available=True
            ),
            SimpleNamespace(
                vehicle_id="bev-2", vehicle_type="BEV", available=True
            ),
            SimpleNamespace(
                vehicle_id="bev-maintenance",
                vehicle_type="BEV",
                available=False,
            ),
            SimpleNamespace(
                vehicle_id="ice-1", vehicle_type="ICE", available=True
            ),
        ),
        metadata={},
    )

    policy = _apply_interactive_bev_utilization_policy(
        problem,
        require_all_available_bevs=True,
    )

    assert policy["minimum_used_bev_count"] == 2
    assert policy["available_bev_ids"] == ["bev-1", "bev-2"]
    assert problem.metadata["minimum_used_bev_count"] == 2
    assert problem.metadata["minimum_used_bev_count_policy_case"] is True


def test_formal_frontend_contract_forces_fleet_and_full_network() -> None:
    scenario = {
        "simulation_config": {
            "research_vehicle_inventory": {"BEV": 1, "ICE": 1},
            "milp_max_successors_per_trip": 8,
        },
        "scenario_overlay": {
            "solver_config": {"milp_max_successors_per_trip": 16}
        },
    }

    contract = _apply_interactive_research_contract(
        scenario,
        research_run=True,
    )

    assert contract["expected_available_inventory"] == {
        "BEV": 35,
        "ICE": 26,
    }
    assert contract["successor_pruning_allowed"] is False
    assert contract["milp_successor_policy"] == "full_network"
    assert contract["milp_max_successors_per_trip"] == 0
    assert scenario["simulation_config"]["research_vehicle_inventory"] == {
        "BEV": 35,
        "ICE": 26,
    }
    assert (
        scenario["simulation_config"]["milp_max_successors_per_trip"]
        == 0
    )
    assert (
        scenario["scenario_overlay"]["solver_config"][
            "milp_max_successors_per_trip"
        ]
        == 0
    )


def test_interactive_run_enforces_energy_neutral_bev_terminal_soc() -> None:
    scenario = {
        "simulation_config": {
            "bev_terminal_soc_policy": "fixed_target",
            "final_soc_target_percent": 80.0,
            "final_soc_target_tolerance_percent": 20.0,
        },
        "scenario_overlay": {
            "charging_constraints": {
                "bev_terminal_soc_policy": "fixed_target",
                "final_soc_target_percent": 80.0,
                "final_soc_target_tolerance_percent": 20.0,
            }
        },
    }

    controls = _apply_interactive_bev_terminal_soc_policy(scenario)

    assert controls["enforced"] is True
    assert controls["override_applied"] is True
    assert controls["effective"] == {
        "bev_terminal_soc_policy": "return_to_initial",
        "terminal_soc_policy": "return_to_initial",
        "final_soc_target_percent": None,
        "final_soc_target_tolerance_percent": None,
    }
    assert scenario["simulation_config"]["bev_terminal_soc_policy"] == "return_to_initial"
    assert scenario["simulation_config"]["final_soc_target_percent"] is None
    assert (
        scenario["scenario_overlay"]["charging_constraints"][
            "final_soc_target_tolerance_percent"
        ]
        is None
    )
