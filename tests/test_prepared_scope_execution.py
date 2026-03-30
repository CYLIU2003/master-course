from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from bff.routers import optimization
from bff.services.run_preparation import (
    _scenario_hash,
    materialize_scenario_from_prepared_input,
    solver_prepare_profile,
)


def test_materialize_scenario_from_prepared_input_overlays_scope_artifacts() -> None:
    scenario = {
        "meta": {"id": "scenario-1"},
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "dispatch_scope": {"serviceId": "WEEKDAY"},
        "simulation_config": {"solver_mode": "mode_milp_only"},
        "deadhead_rules": [{"from_stop": "A", "to_stop": "B", "travel_time_min": 5}],
    }
    prepared_input = {
        "prepared_input_id": "prepared-1",
        "depot_ids": ["dep1"],
        "route_ids": ["route-a"],
        "service_ids": ["WEEKDAY"],
        "prepare_profile": solver_prepare_profile("hybrid"),
        "scope": {"primary_depot_id": "dep1"},
        "scenario_overlay": {"dataset_id": "tokyu_full", "route_ids": ["route-a"]},
        "dispatch_scope": {"effectiveRouteIds": ["route-a"]},
        "simulation_config": {"solver_mode": "hybrid"},
        "depots": [{"id": "dep1"}],
        "routes": [{"id": "route-a"}],
        "vehicles": [{"id": "veh-1", "depotId": "dep1", "type": "BEV"}],
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90}],
        "stops": [{"id": "stop-a"}],
        "trips": [
            {
                "trip_id": "trip-1",
                "route_id": "route-a",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:30",
                "allowed_vehicle_types": ["BEV"],
            }
        ],
        "stop_time_sequences": [{"trip_id": "trip-1", "stop_id": "stop-a"}],
    }

    hydrated = materialize_scenario_from_prepared_input(scenario, prepared_input)

    assert hydrated["prepared_input_id"] == "prepared-1"
    assert hydrated["meta"]["selectedRouteIds"] == ["route-a"]
    assert hydrated["dispatch_scope"]["effectiveRouteIds"] == ["route-a"]
    assert hydrated["simulation_config"]["solver_mode"] == "hybrid"
    assert hydrated["trips"][0]["trip_id"] == "trip-1"
    assert hydrated["timetable_rows"][0]["trip_id"] == "trip-1"
    assert hydrated["prepare_profile"]["profile"] == "hybrid_seeded"
    assert hydrated["deadhead_rules"][0]["travel_time_min"] == 5


def test_run_optimization_uses_prepared_scope_without_dispatch_rebuild_fallback() -> None:
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
        "simulation_config": {"solver_mode": "hybrid"},
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
    data = SimpleNamespace(vehicles=[], tasks=[])
    build_report = SimpleNamespace(
        to_dict=lambda: {},
        vehicle_count=1,
        task_count=1,
        charger_count=0,
        travel_connection_count=0,
        warnings=[],
        errors=[],
    )
    canonical_problem = SimpleNamespace(
        trips=[object()],
        vehicles=[object()],
        chargers=[],
        price_slots=[],
        pv_slots=[],
    )
    stored_fields: dict[str, object] = {}

    def _record_set_field(_scenario_id: str, field: str, value, **_kwargs) -> None:
        stored_fields[field] = value

    with (
        mock.patch.object(optimization, "load_prepared_input", return_value=prepared_input),
        mock.patch.object(optimization.store, "get_scenario_document_shallow", return_value=scenario_doc),
        mock.patch.object(optimization, "_rebuild_dispatch_artifacts") as rebuild_dispatch,
        mock.patch.object(optimization, "build_problem_data_from_scenario", return_value=(data, build_report)) as build_problem_data,
        mock.patch.object(optimization, "ProblemBuilder") as problem_builder_cls,
        mock.patch.object(optimization, "solve_problem_data", return_value={"result": object(), "sim_result": None}),
        mock.patch.object(
            optimization,
            "serialize_milp_result",
            return_value={
                "status": "FEASIBLE",
                "objective_value": 0.0,
                "solve_time_seconds": 0.1,
                "mip_gap": 0.0,
                "assignment": {},
                "unserved_tasks": [],
            },
        ),
        mock.patch.object(optimization, "_scenario_feed_context", return_value={}),
        mock.patch.object(optimization, "_scoped_output_dir", return_value="outputs/test"),
        mock.patch.object(optimization, "_persist_json_outputs"),
        mock.patch.object(optimization, "_cost_breakdown", return_value={}),
        mock.patch.object(optimization, "log_optimization_experiment", return_value={"experiment_id": "exp-1"}),
        mock.patch.object(optimization.store, "set_field", side_effect=_record_set_field),
        mock.patch.object(optimization.store, "update_scenario"),
        mock.patch.object(optimization.store, "get_field", return_value=None),
        mock.patch.object(optimization.job_store, "update_job"),
        mock.patch.object(optimization, "_git_sha", return_value="deadbeef"),
    ):
        problem_builder_cls.return_value.build_from_scenario.return_value = canonical_problem
        optimization._run_optimization(
            "scenario-1",
            "job-1",
            "prepared-1",
            "prepared-1",
            "hybrid",
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
    # Canonical path uses ProblemBuilder, not build_problem_data_from_scenario
    # Verify the canonical problem was built from the prepared scenario
    problem_builder_cls.assert_called()


def test_scenario_hash_ignores_optimization_and_build_audits() -> None:
    base = {
        "meta": {"id": "scenario-1"},
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "dispatch_scope": {"serviceId": "WEEKDAY", "depotId": "dep1"},
        "simulation_config": {"solver_mode": "mode_milp_only"},
    }
    with_audits = {
        **base,
        "__unloaded_artifact_fields__": ["trips", "graph"],
        "optimization_audit": {"executed_at": "2026-03-28T09:00:00+00:00", "output_dir": "output/x"},
        "problemdata_build_audit": {"task_count": 488, "vehicle_count": 70},
        "simulation_audit": {"executed_at": "2026-03-28T09:05:00+00:00"},
    }

    assert _scenario_hash(base) == _scenario_hash(with_audits)
