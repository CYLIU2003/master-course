from __future__ import annotations

from types import SimpleNamespace

import pytest

from bff.routers.optimization import (
    RunOptimizationBody,
    _apply_interactive_bev_utilization_policy,
    _apply_interactive_research_contract,
    _apply_interactive_bev_terminal_soc_policy,
    _interactive_runtime_controls_payload,
    _research_claim_scope_payload,
    _solver_objective_accounting_reconciliation_payload,
    _solver_settings_payload,
)
from bff.services.optimization_run.artifact_completeness import (
    validate_solver_objective_accounting_reconciliation,
)


def test_solver_settings_separate_raw_gap_from_certified_gap_and_stop_rule() -> None:
    settings = _solver_settings_payload(
        time_limit_seconds_requested=1_500,
        mip_gap_requested=0.10,
        random_seed_requested=42,
        stage1_time_limit_seconds_requested=1_200,
        stage2_time_limit_seconds_requested=300,
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
            "stage1_analytical_objective_lower_bound": 640_000.0,
            "stage1_analytical_total_objective_certificate_eligible": True,
            "stage1_analytical_total_objective_certificate_blockers": [],
            "stage1_primary_runtime_seconds": 1_100.0,
            "stage1_primary_search_time_limit_seconds": 1_100.0,
            "stage1_candidate_enumeration_reserve_seconds": 100.0,
            "stage1_candidate_enumeration_runtime_seconds": 95.0,
            "stage1_candidate_powertrain_pattern_no_good_cut_count": 20,
            "stage1_primary_incumbent_objective_jpy": 704_845.8,
            "stage1_selected_candidate_relaxed_objective_jpy": 705_100.0,
            "stage1_candidate_enumeration_events": [
                {
                    "enumeration_iteration": 1,
                    "accepted_as_distinct_candidate": True,
                }
            ],
            "gurobi_threads": 1,
            "git_sha": "abc123",
            "git_dirty": False,
            "git_sha_after_solve": "abc123",
            "git_dirty_after_solve": False,
            "git_state_unchanged_during_solve": True,
        },
    )

    assert settings["stage1_termination_reason"] == "best_obj_stop"
    assert settings["stage1_gurobi_raw_mip_gap_ratio"] == 1.0
    assert settings["stage1_certified_mip_gap_ratio"] == 0.092
    assert settings["stage1_analytical_objective_lower_bound"] == 640_000.0
    assert (
        settings[
            "stage1_analytical_total_objective_certificate_eligible"
        ]
        is True
    )
    assert settings["stage1_primary_runtime_seconds"] == 1_100.0
    assert settings["stage1_candidate_enumeration_runtime_seconds"] == 95.0
    assert (
        settings["stage1_candidate_powertrain_pattern_no_good_cut_count"]
        == 20
    )
    assert settings[
        "stage1_primary_incumbent_objective_jpy"
    ] == pytest.approx(704_845.8)
    assert settings[
        "stage1_selected_candidate_relaxed_objective_jpy"
    ] == pytest.approx(705_100.0)
    assert len(settings["stage1_candidate_enumeration_events"]) == 1
    assert settings["runtime_comparison_eligible"] is False
    assert settings["gurobi_threads"] == 1
    assert settings["random_seed"] == 42
    assert settings["stage1_time_limit_seconds_requested"] == 1_200
    assert settings["stage2_time_limit_seconds_requested"] == 300
    assert settings["git_sha_after_solve"] == "abc123"
    assert settings["git_dirty_after_solve"] is False
    assert settings["git_state_unchanged_during_solve"] is True


def test_lexicographic_cost_stage_reconciles_to_executed_accounting(
    tmp_path,
) -> None:
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    (graph_dir / "canonical_cost_ledger.json").write_text(
        """{
          "accounting_total_cost_jpy": 650234.7293959259,
          "source": "rolling_hourly_chain/executed_day_accounting.json",
          "accounting_residual_tolerance_jpy": 0.000001,
          "objective_is_actual_cost": false
        }""",
        encoding="utf-8",
    )
    payload = _solver_objective_accounting_reconciliation_payload(
        run_dir=tmp_path,
        optimization_result={
            "objective_value": 12.0,
            "solver_metadata": {
                "integrated_actual_cost_contract_applied": True,
                "integrated_lexicographic_cost_objective_jpy": (
                    650234.729395926
                ),
                "objective_semantics": (
                    "lexicographic_vehicle_days_then_canonical_cost"
                ),
            },
        },
    )

    assert payload["objective_is_actual_cost"] is False
    assert payload["matches_canonical_accounting_total"] is False
    assert payload["canonical_cost_numeric_values_available"] is True
    assert payload["canonical_cost_residual_within_tolerance"] is True
    assert payload["canonical_cost_contract_applied"] is True
    assert payload["canonical_cost_matches_accounting_total"] is True
    assert not validate_solver_objective_accounting_reconciliation(
        payload,
        require_match=False,
    )

    payload["canonical_cost_contract_applied"] = False
    assert (
        "solver_objective_accounting_reconciliation.json: "
        "canonical_cost_matches_accounting_total is not derived from cost, "
        "contract, and accounting source"
    ) in validate_solver_objective_accounting_reconciliation(
        payload,
        require_match=False,
    )


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
    assert claim_scope["diagnostic_only"] is True
    assert claim_scope["research_submission_ready"] is False
    assert claim_scope["teacher_release_status"] == "BLOCKED"
    assert claim_scope["blocking_reason"] == "dirty_or_nonformal_run"
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


def test_explicit_diagnostic_result_cannot_claim_physical_or_research_evidence() -> None:
    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "run_profile": "day_ahead_and_hourly_rolling",
            "solver_metadata": {
                "research_run": True,
                "research_run_accepted": False,
                "research_submission_git_provenance_eligible": True,
                "diagnostic_mode": True,
                "result_class": "debug_result",
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={},
        weather_policy={"enabled": False},
        rolling_execution={"status": "executed_and_accepted"},
    )

    assert claim_scope["diagnostic_only"] is True
    assert claim_scope["blocking_reason"] == "explicit_diagnostic_run"
    assert claim_scope["result_label"] == (
        "diagnostic_run_not_used_for_research_conclusions"
    )
    assert claim_scope["allowed_claims"] == []
    assert claim_scope["research_submission_ready"] is False


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
    assert "diagnostic_only" not in claim_scope
    assert "blocking_reason" not in claim_scope


def test_single_run_stays_blocked_until_counterfactual_pair_is_verified() -> None:
    """A completed operational run alone is not a teacher-ready release."""

    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "run_profile": "day_ahead_and_hourly_rolling",
            "solver_metadata": {
                "research_run": True,
                "research_run_accepted": True,
                "research_submission_git_provenance_eligible": True,
                "research_acceptance_checks": {},
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={"mip_gap_target_met": True},
        weather_policy={"enabled": False},
        rolling_execution={
            "status": "executed_and_accepted",
            "rolling_execution_minutes": 60,
        },
    )

    assert claim_scope["teacher_release_status"] == "BLOCKED"
    assert claim_scope["research_submission_ready"] is False
    assert "controlled_counterfactual_pair_not_verified" in claim_scope[
        "teacher_release_failed_checks"
    ]


def test_teacher_release_blocks_incomplete_vehicle_trip_compatibility() -> None:
    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "run_profile": "day_ahead_and_hourly_rolling",
            "solver_metadata": {
                "research_run": True,
                "research_run_accepted": True,
                "research_submission_git_provenance_eligible": True,
                "research_acceptance_checks": {},
            },
            "prepared_scope_audit": {
                "formal_transition_network_ready": True,
                "formal_vehicle_trip_compatibility_ready": False,
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={"mip_gap_target_met": True},
        weather_policy={"enabled": False},
        rolling_execution={
            "status": "executed_and_accepted",
            "rolling_execution_minutes": 60,
        },
    )

    assert "vehicle_trip_compatibility_contract_incomplete" in claim_scope[
        "teacher_release_failed_checks"
    ]


def test_teacher_release_blocks_invalid_turnaround_buffer_sensitivity() -> None:
    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "run_profile": "day_ahead_and_hourly_rolling",
            "solver_metadata": {
                "research_run": True,
                "research_run_accepted": True,
                "research_submission_git_provenance_eligible": True,
                "research_acceptance_checks": {},
            },
            "prepared_scope_audit": {
                "formal_transition_network_ready": True,
                "formal_vehicle_trip_compatibility_ready": True,
                "formal_turnaround_sensitivity_ready": False,
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={"mip_gap_target_met": True},
        weather_policy={"enabled": False},
        rolling_execution={
            "status": "executed_and_accepted",
            "rolling_execution_minutes": 60,
        },
    )

    assert "turnaround_buffer_sensitivity_invalid" in claim_scope[
        "teacher_release_failed_checks"
    ]


def test_teacher_release_distinguishes_failed_transition_audit_from_missing_od() -> None:
    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "run_profile": "day_ahead_and_hourly_rolling",
            "solver_metadata": {
                "research_run": True,
                "research_run_accepted": True,
                "research_submission_git_provenance_eligible": True,
                "research_acceptance_checks": {},
            },
            "prepared_scope_audit": {
                "formal_transition_network_ready": False,
                "route_band_off_deadhead_missing_count": 0,
                "formal_vehicle_trip_compatibility_ready": True,
                "formal_turnaround_sensitivity_ready": True,
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={"mip_gap_target_met": True},
        weather_policy={"enabled": False},
        rolling_execution={
            "status": "executed_and_accepted",
            "rolling_execution_minutes": 60,
        },
    )

    assert "route_band_off_transition_audit_invalid" in claim_scope[
        "teacher_release_failed_checks"
    ]
    assert "route_band_off_deadhead_matrix_incomplete" not in claim_scope[
        "teacher_release_failed_checks"
    ]


def test_two_stage_formal_release_blocks_unreconciled_or_frozen_composition() -> None:
    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "run_profile": "day_ahead_and_hourly_rolling",
            "solver_metadata": {
                "research_run": True,
                "research_run_accepted": True,
                "research_submission_git_provenance_eligible": True,
                "research_acceptance_checks": {},
                "optimization_structure": "two_stage",
                "solver_objective_matches_accounting_total": False,
                "stage1_used_powertrain_composition_search_accepted": False,
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={"mip_gap_target_met": True},
        weather_policy={"enabled": False},
        rolling_execution={
            "status": "executed_and_accepted",
            "rolling_execution_minutes": 60,
        },
    )

    assert claim_scope["teacher_release_status"] == "BLOCKED"
    assert "solver_objective_canonical_accounting_mismatch" in claim_scope[
        "teacher_release_failed_checks"
    ]
    assert "used_powertrain_composition_search_not_certified" in claim_scope[
        "teacher_release_failed_checks"
    ]


def test_two_stage_formal_release_requires_numeric_and_certificate_evidence() -> None:
    """True legacy metadata cannot turn incomplete evidence into a release."""

    claim_scope = _research_claim_scope_payload(
        optimization_result={
            "run_profile": "day_ahead_and_hourly_rolling",
            "solver_metadata": {
                "research_run": True,
                "research_run_accepted": True,
                "research_submission_git_provenance_eligible": True,
                "research_acceptance_checks": {},
                "optimization_structure": "two_stage",
                "solver_objective_matches_accounting_total": True,
                "stage1_used_powertrain_composition_search_accepted": True,
            },
            "solution_validity": {"validated_feasible": True},
        },
        solver_settings={"mip_gap_target_met": True},
        weather_policy={"enabled": False},
        rolling_execution={
            "status": "executed_and_accepted",
            "rolling_execution_minutes": 60,
        },
        objective_accounting_reconciliation={
            "schema_version": "solver_objective_accounting_reconciliation_v1",
            "solver_objective_value_jpy": 100.0,
            "solver_objective_source": "optimization_result.objective_value",
            "canonical_accounting_total_jpy": 110.0,
            "canonical_accounting_source": "rolling_hourly_chain/executed_day_accounting.json",
            "difference_jpy": -10.0,
            "absolute_difference_jpy": 10.0,
            "tolerance_jpy": 1.0e-6,
            "numeric_values_available": True,
            "numeric_residual_within_tolerance": False,
            "objective_is_actual_cost": True,
            "matches_canonical_accounting_total": False,
            "objective_semantics": "actual_cost",
        },
        composition_search_certificate=None,
    )

    assert claim_scope["teacher_release_status"] == "BLOCKED"
    assert "solver_objective_canonical_accounting_mismatch" in claim_scope[
        "teacher_release_failed_checks"
    ]
    assert "used_powertrain_composition_search_not_certified" in claim_scope[
        "teacher_release_failed_checks"
    ]
    assert claim_scope["evidence"][
        "solver_objective_accounting_reconciliation_errors"
    ]
    assert claim_scope["evidence"][
        "stage1_used_powertrain_composition_search_errors"
    ]


def test_interactive_run_defaults_and_provenance_record_server_enforcement() -> None:
    request = RunOptimizationBody()
    assert request.stage1_best_obj_stop_enabled is False
    assert request.gurobi_threads == 4
    assert request.run_profile == "day_ahead_and_hourly_rolling"
    assert request.run_hourly_rolling is True
    assert request.rolling_execution_minutes == 60
    assert request.require_all_available_bevs is False
    assert request.stage1_powertrain_selector_strengthening is False

    strengthened_request = RunOptimizationBody(
        stage1_powertrain_selector_strengthening=True
    )
    assert strengthened_request.stage1_powertrain_selector_strengthening is True

    controls = _interactive_runtime_controls_payload(
        requested_stage1_best_obj_stop_enabled=True,
        requested_gurobi_threads=4,
    )
    assert controls["enforced"] is True
    assert controls["override_applied"] is True
    assert controls["effective"] == {
        "stage1_best_obj_stop_enabled": False,
        "gurobi_threads": 4,
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
        "vehicles": [
            {
                "id": "bev-1",
                "depotId": "tsurumaki",
                "type": "BEV",
                "enabled": True,
                "initialSoc": 80.0,
                "batteryKwh": 300.0,
                "energyConsumption": 1.2,
                "chargePowerKw": 90.0,
                "compatibleChargerIds": ["charger-1"],
            },
            {
                "id": "bev-2",
                "depotId": "tsurumaki",
                "type": "EV",
                "enabled": True,
                "initialSoc": 70.0,
                "batteryKwh": 300.0,
                "energyConsumption": 1.2,
                "chargePowerKw": 90.0,
                "compatibleChargerIds": ["charger-1"],
            },
            {
                "id": "ice-1",
                "depotId": "tsurumaki",
                "type": "ICE",
                "enabled": True,
                "initialFuelL": 100.0,
                "fuelTankL": 200.0,
                "fuelEfficiencyKmPerL": 5.0,
            },
            {
                "id": "ice-disabled",
                "depotId": "tsurumaki",
                "type": "ICE",
                "enabled": False,
            },
            {
                "id": "ice-other",
                "depotId": "other",
                "type": "ICE",
                "enabled": True,
            },
        ],
    }

    contract = _apply_interactive_research_contract(
        scenario,
        research_run=True,
        depot_id="tsurumaki",
    )

    assert contract["expected_available_inventory"] == {
        "BEV": 2,
        "ICE": 1,
    }
    assert contract["inventory_source"] == "selected_scenario_depot_available_vehicles"
    assert contract["inventory_depot_id"] == "tsurumaki"
    assert contract["successor_pruning_allowed"] is False
    assert contract["milp_successor_policy"] == "full_network"
    assert contract["milp_max_successors_per_trip"] == 0
    assert scenario["simulation_config"]["research_vehicle_inventory"] == {
        "BEV": 2,
        "ICE": 1,
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


def test_formal_frontend_contract_requires_available_scenario_fleet() -> None:
    with pytest.raises(ValueError, match="active_vehicle_set_is_empty"):
        _apply_interactive_research_contract(
            {
                "vehicles": [
                    {
                        "id": "disabled",
                        "depotId": "tsurumaki",
                        "type": "ICE",
                        "enabled": False,
                    }
                ]
            },
            research_run=True,
            depot_id="tsurumaki",
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
