from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from bff.routers import optimization
from src.optimization.common.problem import OptimizationMode


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
        "simulation_config": {"solver_mode": "mode_ga_only"},
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
        mock.patch.object(optimization, "_persist_canonical_graph_exports", return_value={"enabled": False, "diagram_count": 0}),
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
        )

    rebuild_dispatch.assert_not_called()
    build_problem_data.assert_not_called()
    solve_problem_data.assert_not_called()
    assert problem_builder_cls.return_value.build_from_scenario.call_args.kwargs["config"].warm_start is True
    assert "trips" not in stored_fields
    assert "timetable_rows" not in stored_fields
    assert stored_fields["optimization_result"]["solver_mode"] == "mode_ga_only"
    assert stored_fields["optimization_result"]["summary"]["trip_count_served"] == 1
    assert stored_fields["optimization_result"]["solver_result"]["assignment"] == {"veh-1": ["trip-1"]}
    assert stored_fields["optimization_result"]["canonical_solver_result"] == {
        "solver_mode": "ga",
        "vehicle_paths": {"veh-1": ["trip-1"]},
    }


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
        )

    rebuild_dispatch.assert_not_called()
    build_problem_data.assert_not_called()
    solve_problem_data.assert_not_called()
    persist_graph_exports.assert_called_once()
    assert problem_builder_cls.return_value.build_from_scenario.call_args.kwargs["config"].warm_start is True
    assert "trips" not in stored_fields
    assert "timetable_rows" not in stored_fields
    assert stored_fields["optimization_result"]["solver_mode"] == "mode_milp_only"
    assert stored_fields["optimization_result"]["graph_artifacts"] == {
        "enabled": True,
        "diagram_count": 1,
        "manifest_path": "graph/route_band_diagrams/manifest.json",
        "vehicle_timeline_path": "graph/vehicle_timeline.csv",
    }


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
            optimization.RunOptimizationBody(mode="mode_milp_only"),
            {"built_ready": True, "built_dir": "data/built/tokyu_full", "routes_df": None},
        )

    assert result == {"job_id": "job-1", "status": "pending"}
    assert submit_job.call_args.kwargs["args"][2] == "prepared-current"
    assert submit_job.call_args.kwargs["args"][4] == "mode_milp_only"
