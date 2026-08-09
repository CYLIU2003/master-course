from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException

from bff.routers import optimization
from bff.services.direct_runtime import is_direct_supported
from src.optimization.common.problem import OptimizationMode


def test_interactive_operation_time_window_controls_force_full_day_without_losing_pair() -> None:
    scenario = {
        "simulation_config": {
            "operation_time_window_enabled": False,
            "start_time": "05:00",
            "end_time": "23:00",
            "planning_days": 1,
        }
    }

    controls = optimization._apply_interactive_operation_time_window_controls(
        scenario
    )

    assert scenario["simulation_config"]["start_time"] == "05:00"
    assert scenario["simulation_config"]["end_time"] == "23:00"
    assert scenario["simulation_config"]["planning_horizon_hours"] == 24.0
    assert scenario["simulation_config"]["operation_time_window_effective_start_time"] == "00:00"
    assert scenario["simulation_config"]["operation_time_window_effective_end_time"] == "23:59"
    assert controls["effective"] == {
        "operation_time_window_enabled": False,
        "start_time": "00:00",
        "end_time": "23:59",
        "planning_horizon_hours": 24.0,
    }


def test_run_optimization_uses_canonical_engine_for_ga_mode() -> None:
    scenario_doc = {
        "meta": {"id": "scenario-1"},
        "feed_context": {},
        "scenario_overlay": {"solver_config": {"objective_mode": "total_cost"}},
        "dispatch_scope": {"effectiveRouteIds": ["route-a"]},
    }
    prepared_input = {
        "prepared_input_id": "prepared-1",
        "dispatch_scope": {"effectiveRouteIds": ["route-a"]},
        "scenario_overlay": {"solver_config": {"objective_mode": "total_cost"}},
        "simulation_config": {
            "solver_mode": "mode_ga_only",
            "operation_time_window_enabled": False,
            "start_time": "05:00",
            "end_time": "23:00",
        },
        "depots": [{"id": "dep1"}],
        "routes": [{"id": "route-a"}],
        "vehicles": [{"id": "veh-1", "depotId": "dep1", "type": "BEV"}],
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90}],
        "stops": [],
        "trips": [
            {
                "trip_id": "trip-1",
                "route_id": "route-a",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
            }
        ],
    }
    canonical_problem = SimpleNamespace(
        scenario=SimpleNamespace(
            service_coverage_mode="strict",
            fixed_route_band_mode=False,
            daily_fragment_limit=1,
            timestep_min=30,
        ),
        metadata={},
        trips=[object()],
        vehicles=[SimpleNamespace(vehicle_id="veh-1", vehicle_type="BEV")],
        chargers=[],
        price_slots=[],
        pv_slots=[],
        feasible_connections={"trip-1": ()},
    )
    engine_result = SimpleNamespace(
        solver_status="feasible",
        objective_value=123.0,
        plan=SimpleNamespace(
            vehicle_paths=lambda: {"veh-1": ["trip-1"]},
            unserved_trip_ids=[],
            vehicle_fragment_counts=lambda: {"veh-1": 1},
            vehicles_with_multiple_fragments=lambda: [],
            max_fragments_observed=lambda: 1,
            unused_available_vehicle_ids=lambda _problem: [],
            metadata={},
        ),
        solver_metadata={"objective_mode": "total_cost"},
        cost_breakdown={"energy_cost": 10.0, "demand_cost": 0.0, "vehicle_cost": 0.0},
        mode=OptimizationMode.GA,
        feasible=True,
        warnings=(),
        infeasibility_reasons=(),
        operator_stats={},
        incumbent_history=(),
    )
    stored_fields: dict[str, object] = {}

    def _record_set_field(_scenario_id: str, field: str, value, **_kwargs) -> None:
        stored_fields[field] = value

    with (
        mock.patch.object(optimization, "load_prepared_input", return_value=prepared_input),
        mock.patch.object(optimization.store, "get_scenario_document_shallow", return_value=scenario_doc),
        mock.patch.object(optimization, "_rebuild_dispatch_artifacts") as rebuild_dispatch,
        mock.patch.object(optimization, "build_problem_data_from_scenario") as build_problem_data,
        mock.patch.object(optimization, "ProblemBuilder") as problem_builder_cls,
        mock.patch.object(optimization, "OptimizationEngine") as engine_cls,
        mock.patch.object(optimization, "solve_problem_data") as solve_problem_data,
        mock.patch.object(
            optimization.ResultSerializer,
            "serialize_result",
            return_value={"solver_mode": "ga", "vehicle_paths": {"veh-1": ["trip-1"]}},
        ),
        mock.patch.object(optimization, "_scenario_feed_context", return_value={}),
            mock.patch.object(optimization, "_scoped_output_dir", return_value="outputs/test"),
            mock.patch.object(
                optimization,
                "persist_run_input_provenance",
                return_value={"status": "OK"},
            ) as persist_input_provenance,
            mock.patch.object(optimization, "_persist_canonical_graph_exports", return_value={"enabled": False, "diagram_count": 0}),
        mock.patch.object(optimization, "_persist_json_outputs"),
        mock.patch.object(optimization, "_cost_breakdown", return_value={}),
        mock.patch.object(optimization, "log_optimization_experiment", return_value={"experiment_id": "exp-1"}),
        mock.patch.object(optimization.store, "set_field", side_effect=_record_set_field),
        mock.patch.object(optimization, "_canonical_charging_output_payload", return_value=None),
        mock.patch.object(optimization.store, "update_scenario"),
        mock.patch.object(optimization.store, "get_field", return_value=None),
        mock.patch.object(optimization.job_store, "update_job"),
        mock.patch.multiple(
            optimization,
            _git_sha=mock.Mock(return_value="deadbeef"),
            persist_frontend_day_ahead_rolling_contract=mock.DEFAULT,
            execute_frontend_rolling_chain=mock.DEFAULT,
        ) as rolling_mocks,
    ):
        rolling_mocks["execute_frontend_rolling_chain"].return_value = (
            SimpleNamespace(
                status="executed_and_accepted",
                chain_summary_path=(
                    "outputs/test/rolling_hourly_chain/"
                    "rolling_chain_summary.json"
                ),
                chain_accepted=True,
                technical_failure_reasons=(),
            )
        )
        problem_builder_cls.return_value.build_from_scenario.return_value = canonical_problem
        engine_cls.return_value.solve.return_value = engine_result
        optimization._run_optimization(
            "scenario-1",
            "job-1",
            "prepared-1",
            "prepared-1",
            "ga",
            60,
            0.01,
            42,
            "WEEKDAY",
            "dep1",
            False,
            False,
            100,
            100,
            0.25,
            stage1_best_obj_stop_enabled=True,
            gurobi_threads=4,
            frontend_request_payload={
                "stage1_best_obj_stop_enabled": True,
                "gurobi_threads": 4,
            },
        )

    rebuild_dispatch.assert_not_called()
    build_problem_data.assert_not_called()
    solve_problem_data.assert_not_called()
    config = problem_builder_cls.return_value.build_from_scenario.call_args.kwargs["config"]
    effective_scenario = problem_builder_cls.return_value.build_from_scenario.call_args.args[0]
    assert config.warm_start is True
    assert config.stage1_best_obj_stop_enabled is False
    assert config.gurobi_threads == 4
    assert effective_scenario["simulation_config"]["bev_terminal_soc_policy"] == "return_to_initial"
    assert effective_scenario["simulation_config"]["final_soc_target_percent"] is None
    assert effective_scenario["simulation_config"]["operation_time_window_enabled"] is False
    assert effective_scenario["simulation_config"]["operation_time_window_effective_start_time"] == "00:00"
    persist_input_provenance.assert_called_once()
    provenance_kwargs = persist_input_provenance.call_args.kwargs
    assert provenance_kwargs["prepared_input"]["prepared_input_id"] == "prepared-1"
    assert provenance_kwargs["frontend_request"]["mode"] == "ga"
    assert provenance_kwargs["frontend_request"]["raw_frontend_body"] == {
        "stage1_best_obj_stop_enabled": True,
        "gurobi_threads": 4,
    }
    assert provenance_kwargs["frontend_request"]["interactive_runtime_controls"][
        "effective"
    ] == {"stage1_best_obj_stop_enabled": False, "gurobi_threads": 4}
    assert provenance_kwargs["frontend_request"]["interactive_terminal_soc_controls"][
        "effective"
    ]["bev_terminal_soc_policy"] == "return_to_initial"
    assert provenance_kwargs["frontend_request"][
        "interactive_operation_time_window_controls"
    ]["effective"]["start_time"] == "00:00"
    assert provenance_kwargs["canonical_problem"] is canonical_problem
    assert "trips" not in stored_fields
    assert "timetable_rows" not in stored_fields
    assert stored_fields["optimization_result"]["solver_mode"] == "mode_ga_only"
    assert stored_fields["optimization_result"]["solver_settings"][
        "interactive_runtime_controls"
    ]["effective"] == {"stage1_best_obj_stop_enabled": False, "gurobi_threads": 4}
    assert stored_fields["optimization_result"]["solver_settings"][
        "interactive_operation_time_window_controls"
    ]["effective"]["end_time"] == "23:59"
    assert stored_fields["optimization_result"]["summary"]["trip_count_served"] == 1
    assert stored_fields["optimization_result"]["solver_result"]["assignment"] == {"veh-1": ["trip-1"]}
    assert stored_fields["optimization_result"]["canonical_solver_result"]["solver_mode"] == "ga"
    assert stored_fields["optimization_result"]["canonical_solver_result"]["vehicle_paths"] == {"veh-1": ["trip-1"]}
    assert stored_fields["optimization_result"]["canonical_solver_result"]["solution_validity"]["validated_no_cancellation"] is True
    rolling_mocks["persist_frontend_day_ahead_rolling_contract"].assert_called_once()
    rolling_mocks["execute_frontend_rolling_chain"].assert_called_once()
    assert (
        rolling_mocks["execute_frontend_rolling_chain"].call_args.kwargs["problem"]
        is canonical_problem
    )
    assert (
        rolling_mocks["execute_frontend_rolling_chain"]
        .call_args.kwargs["execution_minutes"]
        == 60
    )


def test_run_optimization_records_canonical_graph_artifacts_for_milp_mode() -> None:
    scenario_doc = {
        "meta": {"id": "scenario-1"},
        "feed_context": {},
        "scenario_overlay": {"solver_config": {"objective_mode": "total_cost"}},
        "simulation_config": {"enable_vehicle_diagram_output": True},
        "dispatch_scope": {"effectiveRouteIds": ["route-a"]},
    }
    prepared_input = {
        "prepared_input_id": "prepared-1",
        "dispatch_scope": {"effectiveRouteIds": ["route-a"]},
        "scenario_overlay": {"solver_config": {"objective_mode": "total_cost"}},
        "simulation_config": {"solver_mode": "mode_milp_only", "enable_vehicle_diagram_output": True},
        "depots": [{"id": "dep1"}],
        "routes": [{"id": "route-a"}],
        "vehicles": [{"id": "veh-1", "depotId": "dep1", "type": "BEV"}],
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90}],
        "stops": [],
        "trips": [
            {
                "trip_id": "trip-1",
                "route_id": "route-a",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
            }
        ],
    }
    canonical_problem = SimpleNamespace(
        scenario=SimpleNamespace(
            service_coverage_mode="strict",
            fixed_route_band_mode=False,
            daily_fragment_limit=1,
            timestep_min=30,
        ),
        metadata={},
        trips=[object()],
        vehicles=[SimpleNamespace(vehicle_id="veh-1", vehicle_type="BEV")],
        chargers=[],
        price_slots=[],
        pv_slots=[],
        feasible_connections={"trip-1": ()},
    )
    engine_result = SimpleNamespace(
        solver_status="optimal",
        objective_value=111.0,
        plan=SimpleNamespace(
            vehicle_paths=lambda: {"veh-1": ["trip-1"]},
            unserved_trip_ids=[],
            vehicle_fragment_counts=lambda: {"veh-1": 1},
            vehicles_with_multiple_fragments=lambda: [],
            max_fragments_observed=lambda: 1,
            unused_available_vehicle_ids=lambda _problem: [],
            metadata={},
        ),
        solver_metadata={"objective_mode": "total_cost"},
        cost_breakdown={"energy_cost": 10.0, "demand_cost": 0.0, "vehicle_cost": 0.0},
        mode=OptimizationMode.MILP,
        feasible=True,
        warnings=(),
        infeasibility_reasons=(),
        operator_stats={},
        incumbent_history=(),
    )
    stored_fields: dict[str, object] = {}

    def _record_set_field(_scenario_id: str, field: str, value, **_kwargs) -> None:
        stored_fields[field] = value

    with (
        mock.patch.object(optimization, "load_prepared_input", return_value=prepared_input),
        mock.patch.object(optimization.store, "get_scenario_document_shallow", return_value=scenario_doc),
        mock.patch.object(optimization, "_rebuild_dispatch_artifacts") as rebuild_dispatch,
        mock.patch.object(optimization, "build_problem_data_from_scenario") as build_problem_data,
        mock.patch.object(optimization, "ProblemBuilder") as problem_builder_cls,
        mock.patch.object(optimization, "OptimizationEngine") as engine_cls,
        mock.patch.object(optimization, "solve_problem_data") as solve_problem_data,
        mock.patch.object(
            optimization.ResultSerializer,
            "serialize_result",
            return_value={"solver_mode": "milp", "vehicle_paths": {"veh-1": ["trip-1"]}},
        ),
        mock.patch.object(
            optimization,
            "_persist_canonical_graph_exports",
            return_value={
                "enabled": True,
                "diagram_count": 1,
                "manifest_path": "graph/route_band_diagrams/manifest.json",
                "vehicle_timeline_path": "graph/vehicle_timeline.csv",
            },
        ) as persist_graph_exports,
            mock.patch.object(optimization, "_scenario_feed_context", return_value={}),
            mock.patch.object(optimization, "_scoped_output_dir", return_value="outputs/test"),
            mock.patch.object(
                optimization,
                "persist_run_input_provenance",
                return_value={"status": "OK"},
            ) as persist_input_provenance,
            mock.patch.object(optimization, "_persist_json_outputs"),
        mock.patch.object(optimization, "_cost_breakdown", return_value={}),
        mock.patch.object(optimization, "log_optimization_experiment", return_value={"experiment_id": "exp-1"}),
        mock.patch.object(optimization.store, "set_field", side_effect=_record_set_field),
        mock.patch.object(optimization, "_canonical_charging_output_payload", return_value=None),
        mock.patch.object(optimization.store, "update_scenario"),
        mock.patch.object(optimization.store, "get_field", return_value=None),
        mock.patch.object(optimization.job_store, "update_job"),
        mock.patch.object(optimization, "_git_sha", return_value="deadbeef"),
    ):
        problem_builder_cls.return_value.build_from_scenario.return_value = canonical_problem
        engine_cls.return_value.solve.return_value = engine_result
        optimization._run_optimization(
            "scenario-1",
            "job-1",
            "prepared-1",
            "prepared-1",
            "mode_milp_only",
            60,
            0.01,
            42,
            "WEEKDAY",
            "dep1",
            False,
            False,
            100,
            100,
            0.25,
            run_profile=optimization.DAY_AHEAD_EXPLORATORY_PROFILE,
        )

    rebuild_dispatch.assert_not_called()
    build_problem_data.assert_not_called()
    solve_problem_data.assert_not_called()
    persist_input_provenance.assert_called_once()
    assert (
        persist_input_provenance.call_args.kwargs["frontend_request"][
            "solver_mode_effective"
        ]
        == "mode_milp_only"
    )
    persist_graph_exports.assert_called_once()
    assert problem_builder_cls.return_value.build_from_scenario.call_args.kwargs["config"].warm_start is True
    assert canonical_problem.metadata["phase3_diagnostics_dir"] == str(
        Path("outputs/test") / "diagnostics"
    )
    assert "trips" not in stored_fields
    assert "timetable_rows" not in stored_fields
    assert stored_fields["optimization_result"]["solver_mode"] == "mode_milp_only"
    expected_graph_artifacts = {
        "enabled": True,
        "diagram_count": 1,
        "manifest_path": "graph/route_band_diagrams/manifest.json",
        "vehicle_timeline_path": "graph/vehicle_timeline.csv",
    }
    for key, value in expected_graph_artifacts.items():
        assert stored_fields["optimization_result"]["graph_artifacts"][key] == value


def test_phase4_problem_enables_seed_candidate_diagnostics_without_feedback() -> None:
    phase4_problem = SimpleNamespace(metadata={})
    phase3_problem = SimpleNamespace(metadata={})

    optimization._configure_assignment_energy_diagnostics(
        phase4_problem,
        phase_token="phase4_integrated",
        output_dir="outputs/phase4-test",
        research_run=True,
    )

    assert phase4_problem.metadata["phase3_diagnostics_dir"] == str(
        Path("outputs/phase4-test") / "diagnostics"
    )
    assert "stage2_feedback_max_iterations" not in phase4_problem.metadata
    assert "stage2_feedback_policy" not in phase4_problem.metadata

    optimization._configure_assignment_energy_diagnostics(
        phase3_problem,
        phase_token="phase3_two_stage",
        output_dir="outputs/phase3-test",
        research_run=True,
    )

    assert phase3_problem.metadata["phase3_diagnostics_dir"] == str(
        Path("outputs/phase3-test") / "diagnostics"
    )
    assert phase3_problem.metadata["stage2_feedback_max_iterations"] == 2
    assert phase3_problem.metadata["stage2_feedback_policy"].startswith(
        "retry_only_after_gurobi_infeasible_certificate"
    )


def test_run_optimization_endpoint_submits_current_prepared_input_job() -> None:
    fake_job = SimpleNamespace(
        job_id="job-1",
        status="pending",
        progress=0,
        message="",
        result_key=None,
        error=None,
        metadata={},
    )
    prep = SimpleNamespace(
        is_valid=True,
        prepared_input_id="prepared-current",
        scope_summary={"trip_count": 1},
        error=None,
    )

    with (
        mock.patch.object(optimization, "_require_scenario"),
        mock.patch.object(
            optimization,
            "collect_git_state",
            return_value={
                "git_state_available": True,
                "git_sha": "clean-commit",
                "git_dirty": False,
                "status_porcelain": [],
            },
        ),
        mock.patch.object(optimization.store, "get_scenario_document_shallow", return_value={}),
        mock.patch.object(optimization, "get_or_build_run_preparation", return_value=prep),
        mock.patch.object(
            optimization,
            "_resolve_dispatch_scope",
            return_value={"serviceId": "WEEKDAY", "depotId": "dep1"},
        ),
        mock.patch.object(optimization.job_store, "create_job", return_value=fake_job),
        mock.patch.object(optimization.job_store, "update_job"),
        mock.patch.object(
            optimization.job_store,
            "job_to_dict",
            return_value={"job_id": "job-1", "status": "pending"},
        ),
        mock.patch.object(optimization, "_submit_optimization_job", return_value=True) as submit_job,
    ):
        result = optimization.run_optimization(
            "scenario-1",
            optimization.RunOptimizationBody(
                mode="mode_milp_only",
                research_run=True,
            ),
            {"built_ready": True, "built_dir": "data/built/tokyu_full", "routes_df": None},
        )

    assert result == {"job_id": "job-1", "status": "pending"}
    submitted_args = submit_job.call_args.kwargs["args"]
    assert submitted_args[2] == "prepared-current"
    assert submitted_args[4] == "mode_milp_only"
    assert submitted_args[18] is True
    assert submitted_args[23] == "day_ahead_and_hourly_rolling"
    assert submitted_args[24] is True
    assert submitted_args[25] == 60
    assert submitted_args[26]["run_hourly_rolling"] is True
    assert submitted_args[26]["rolling_execution_minutes"] == 60


def test_run_optimization_endpoint_only_allows_day_ahead_with_explicit_profile() -> None:
    fake_job = SimpleNamespace(
        job_id="job-2",
        status="pending",
        progress=0,
        message="",
        result_key=None,
        error=None,
        metadata={},
    )
    prep = SimpleNamespace(
        is_valid=True,
        prepared_input_id="prepared-current",
        scope_summary={"trip_count": 1},
        error=None,
    )

    with (
        mock.patch.object(optimization, "_require_scenario"),
        mock.patch.object(
            optimization,
            "collect_git_state",
            return_value={
                "git_state_available": True,
                "git_sha": "dirty-commit",
                "git_dirty": True,
                "status_porcelain": [" M README.md"],
            },
        ) as collect_git_state,
        mock.patch.object(
            optimization.store,
            "get_scenario_document_shallow",
            return_value={},
        ),
        mock.patch.object(
            optimization, "get_or_build_run_preparation", return_value=prep
        ),
        mock.patch.object(
            optimization,
            "_resolve_dispatch_scope",
            return_value={"serviceId": "WEEKDAY", "depotId": "dep1"},
        ),
        mock.patch.object(
            optimization.job_store, "create_job", return_value=fake_job
        ),
        mock.patch.object(optimization.job_store, "update_job"),
        mock.patch.object(
            optimization.job_store,
            "job_to_dict",
            return_value={"job_id": "job-2", "status": "pending"},
        ),
        mock.patch.object(
            optimization, "_submit_optimization_job", return_value=True
        ) as submit_job,
    ):
        optimization.run_optimization(
            "scenario-1",
            optimization.RunOptimizationBody(
                mode="mode_milp_only",
                run_profile="day_ahead_exploratory",
                run_hourly_rolling=True,
                rolling_execution_minutes=15,
            ),
            {
                "built_ready": True,
                "built_dir": "data/built/tokyu_full",
                "routes_df": None,
            },
        )

    submitted_args = submit_job.call_args.kwargs["args"]
    collect_git_state.assert_not_called()
    assert submitted_args[18] is False
    assert submitted_args[23] == "day_ahead_exploratory"
    assert submitted_args[24] is False
    assert submitted_args[25] == 60


def test_formal_dirty_request_is_rejected_before_job_creation() -> None:
    create_job = mock.Mock()
    dirty_state = {
        "git_state_available": True,
        "git_sha": "dirty-commit",
        "git_dirty": True,
        "git_state_error": None,
        "status_porcelain": [
            " M src/optimization/model.py",
            "?? tests/test_model.py",
        ],
    }

    with (
        mock.patch.object(optimization, "_require_scenario"),
        mock.patch.object(
            optimization,
            "collect_git_state",
            return_value=dirty_state,
        ),
        mock.patch.object(
            optimization.job_store,
            "create_job",
            create_job,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        optimization.run_optimization(
            "scenario-1",
            optimization.RunOptimizationBody(research_run=True),
            {
                "built_ready": True,
                "built_dir": "data/built/tokyu_full",
                "routes_df": None,
            },
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == (
        "RESEARCH_GIT_STATE_INVALID"
    )
    assert exc_info.value.detail["uncommitted_changes"] == (
        dirty_state["status_porcelain"]
    )
    create_job.assert_not_called()


def test_research_git_preflight_reports_clean_and_dirty_states() -> None:
    with mock.patch.object(
        optimization,
        "collect_git_state",
        return_value={
            "git_state_available": True,
            "git_sha": "clean-commit",
            "git_dirty": False,
            "git_state_error": None,
            "status_porcelain": [],
            "repository_root": "C:/master-course",
        },
    ):
        clean = optimization.get_research_git_preflight()

    assert clean["formal_research_ready"] is True
    assert clean["uncommitted_changes"] == []

    with mock.patch.object(
        optimization,
        "collect_git_state",
        return_value={
            "git_state_available": True,
            "git_sha": "dirty-commit",
            "git_dirty": True,
            "git_state_error": None,
            "status_porcelain": [" M README.md"],
        },
    ):
        dirty = optimization.get_research_git_preflight()

    assert dirty["formal_research_ready"] is False
    assert dirty["uncommitted_changes"] == [" M README.md"]


def test_research_git_preflight_is_available_in_direct_runtime() -> None:
    assert is_direct_supported("GET", "/research/git-preflight") is True
