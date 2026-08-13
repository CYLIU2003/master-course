from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from bff.routers import optimization
from bff.services.run_preparation import (
    PREPARED_INPUT_SCHEMA_VERSION,
    PreparedInputIdentityCollisionError,
    _persist_prepared_input_immutably,
    _prepared_input_id,
    _scenario_hash,
    _scope_cache_payload,
    _scope_hash,
    _materialize_explicit_fleet_state,
    RunPreparation,
    get_or_build_run_preparation,
    invalidate_scenario,
    materialize_scenario_from_prepared_input,
    solver_prepare_profile,
)


def test_prepared_artifact_reuses_original_bytes_when_only_timestamp_changes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prepared.json"
    original = {
        "prepared_input_id": "prepared-fixed",
        "prepared_at": 1.0,
        "trips": [{"trip_id": "trip-1", "distance_km": 5.0}],
    }
    rebuilt = {**original, "prepared_at": 2.0}

    first = _persist_prepared_input_immutably(path, original)
    original_bytes = path.read_bytes()
    second = _persist_prepared_input_immutably(path, rebuilt)

    assert first == original
    assert second == original
    assert path.read_bytes() == original_bytes
    assert json.loads(path.read_text(encoding="utf-8"))["prepared_at"] == 1.0


def test_prepared_artifact_rejects_content_change_under_same_id(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prepared.json"
    original = {
        "prepared_input_id": "prepared-fixed",
        "prepared_at": 1.0,
        "trips": [{"trip_id": "trip-1", "distance_km": 5.0}],
    }
    changed = {
        **original,
        "prepared_at": 2.0,
        "trips": [{"trip_id": "trip-1", "distance_km": 6.0}],
    }
    _persist_prepared_input_immutably(path, original)
    original_bytes = path.read_bytes()

    with pytest.raises(PreparedInputIdentityCollisionError):
        _persist_prepared_input_immutably(path, changed)

    assert path.read_bytes() == original_bytes


def test_process_restart_reuses_persisted_prepared_input_without_rebuild(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = {
        "meta": {"id": "scenario-restart"},
        "scenario_overlay": {
            "dataset_id": "tokyu_full",
            "dataset_version": "dataset-v1",
        },
        "simulation_config": {
            "service_date": "2025-08-05",
            "service_dates": ["2025-08-05"],
            "planning_days": 1,
        },
        "dispatch_scope": {"serviceId": "WEEKDAY", "depotId": "dep1"},
    }
    scope = SimpleNamespace(
        depot_ids=["dep1"],
        route_ids=["route-a"],
        service_ids=["WEEKDAY"],
        service_date="2025-08-05",
        route_selectors=["route-a"],
    )
    scenario_hash = _scenario_hash(scenario)
    scope_hash = _scope_hash(_scope_cache_payload(scenario, scope))
    prepared_input_id = _prepared_input_id(scenario_hash, scope_hash)
    prepared_root = tmp_path / "prepared_inputs"
    prepared_dir = prepared_root / "scenario-restart"
    prepared_dir.mkdir(parents=True)
    prepared_path = prepared_dir / f"{prepared_input_id}.json"
    payload = {
        "prepared_input_id": prepared_input_id,
        "prepared_input_schema_version": PREPARED_INPUT_SCHEMA_VERSION,
        "scenario_id": "scenario-restart",
        "dataset_id": "tokyu_full",
        "dataset_version": "dataset-v1",
        "scenario_hash": scenario_hash,
        "scope_hash": scope_hash,
        "prepared_at": 1.0,
        "depot_ids": ["dep1"],
        "route_ids": ["route-a"],
        "service_ids": ["WEEKDAY"],
        "service_date": "2025-08-05",
        "service_dates": ["2025-08-05"],
        "planning_days": 1,
        "primary_depot_id": "dep1",
        "trip_count": 1,
        "timetable_row_count": 1,
        "prepared_scope_audit": {
            "trip_distance_audit": {"total_count": 1},
            "warnings": ["persisted warning"],
        },
    }
    prepared_path.write_text(json.dumps(payload), encoding="utf-8")
    invalidate_scenario("scenario-restart")
    monkeypatch.setattr("src.runtime_scope.resolve_scope", lambda *_args: scope)

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("persisted prepared input must not be rebuilt")

    monkeypatch.setattr(
        "bff.services.run_preparation._build_run_preparation",
        fail_rebuild,
    )

    result = get_or_build_run_preparation(
        scenario,
        tmp_path / "built",
        prepared_root,
        None,
    )

    assert result.is_valid is True
    assert result.prepared_input_id == prepared_input_id
    assert result.solver_input_path == prepared_path
    assert result.scope_summary["load_source"] == "persisted_prepared_input"
    assert result.warnings == ["persisted warning"]


def test_explicit_thesis_phases_use_milp_exact_prepare_profile() -> None:
    for phase in (
        "phase1_charging_only",
        "phase2_assignment_only",
        "phase3_two_stage",
        "phase4_integrated",
    ):
        profile = solver_prepare_profile(phase)
        assert profile["solver_mode_effective"] == phase
        assert profile["profile"] == "milp_exact"


def test_prepare_materializes_explicit_fleet_state_from_existing_solver_rules() -> None:
    vehicles = [
        {
            "id": "bev-1",
            "type": "BEV",
            "depotId": "dep1",
            "batteryKwh": 314.0,
            "chargePowerKw": 90.0,
            "initialSoc": 0.8,
        },
        {
            "id": "ice-1",
            "type": "ICE",
            "depotId": "dep1",
            "fuelTankL": 300.0,
            "fuelEfficiencyKmPerL": 4.5,
        },
    ]
    chargers = [
        {"id": "dep1-fast-1", "siteId": "dep1", "powerKw": 90.0},
        {"id": "dep1-normal-1", "siteId": "dep1", "powerKw": 50.0},
        {"id": "other-fast-1", "siteId": "other", "powerKw": 90.0},
    ]

    materialized, audit = _materialize_explicit_fleet_state(
        vehicles,
        chargers,
        {
            "initial_ice_fuel_percent": 100.0,
            "max_ice_fuel_percent": 90.0,
        },
        selected_depot_ids=["dep1"],
    )

    assert materialized[0]["compatibleChargerIds"] == [
        "dep1-fast-1",
        "dep1-normal-1",
    ]
    assert materialized[1]["initialFuelL"] == 270.0
    assert audit["charger_compatibility_derived_vehicle_count"] == 1
    assert audit["initial_fuel_derived_vehicle_count"] == 1


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
        "scope": {
            "primary_depot_id": "dep1",
            "prepared_scope_audit": {
                "warning_codes": ["trip_distance_zero_or_missing"],
            },
        },
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
    assert hydrated["prepared_scope_summary"]["prepared_scope_audit"]["warning_codes"] == [
        "trip_distance_zero_or_missing"
    ]
    assert hydrated["deadhead_rules"][0]["travel_time_min"] == 5


def test_materialize_scenario_from_prepared_input_preserves_current_runtime_flags() -> None:
    scenario = {
        "meta": {"id": "scenario-1"},
        "scenario_overlay": {
            "dataset_id": "tokyu_full",
            "charging_constraints": {"depot_power_limit_kw": 200.0},
            "cost_coefficients": {"grid_flat_price_per_kwh": 25.0},
            "solver_config": {
                "fixed_route_band_mode": True,
                "enable_vehicle_diagram_output": True,
                "output_vehicle_diagram": True,
                "objective_mode": "total_cost",
            },
        },
        "dispatch_scope": {
            "serviceId": "WEEKDAY",
            "fixedRouteBandMode": True,
            "allowIntraDepotRouteSwap": False,
        },
        "simulation_config": {
            "solver_mode": "mode_milp_only",
            "fixed_route_band_mode": True,
            "enable_vehicle_diagram_output": True,
            "output_vehicle_diagram": True,
            "objective_mode": "total_cost",
        },
    }
    prepared_input = {
        "prepared_input_id": "prepared-1",
        "scenario_overlay": {
            "dataset_id": "tokyu_full",
            "solver_config": {
                "fixed_route_band_mode": False,
                "enable_vehicle_diagram_output": False,
                "output_vehicle_diagram": False,
                "objective_mode": "co2",
            },
        },
        "dispatch_scope": {
            "effectiveRouteIds": ["route-a"],
            "fixedRouteBandMode": False,
            "allowIntraDepotRouteSwap": True,
        },
        "simulation_config": {
            "solver_mode": "hybrid",
            "fixed_route_band_mode": False,
            "enable_vehicle_diagram_output": False,
            "output_vehicle_diagram": False,
            "objective_mode": "co2",
        },
        "trips": [],
    }

    hydrated = materialize_scenario_from_prepared_input(scenario, prepared_input)

    assert hydrated["dispatch_scope"]["fixedRouteBandMode"] is True
    assert hydrated["dispatch_scope"]["allowIntraDepotRouteSwap"] is False
    assert hydrated["simulation_config"]["fixed_route_band_mode"] is True
    assert hydrated["simulation_config"]["enable_vehicle_diagram_output"] is True
    assert hydrated["simulation_config"]["objective_mode"] == "total_cost"
    assert hydrated["scenario_overlay"]["solver_config"]["fixed_route_band_mode"] is True
    assert hydrated["scenario_overlay"]["solver_config"]["enable_vehicle_diagram_output"] is True
    assert hydrated["scenario_overlay"]["cost_coefficients"]["grid_flat_price_per_kwh"] == 25.0


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
            run_profile=optimization.DAY_AHEAD_EXPLORATORY_PROFILE,
        )

    rebuild_dispatch.assert_not_called()
    # Canonical path uses ProblemBuilder, not build_problem_data_from_scenario
    # Verify the canonical problem was built from the prepared scenario
    problem_builder_cls.assert_called()
    assert "trips" not in stored_fields
    assert "timetable_rows" not in stored_fields


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


def test_run_preparation_cache_includes_selected_scope(monkeypatch) -> None:
    scenario = {
        "meta": {"id": "scenario-cache"},
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "simulation_config": {"service_date": "2025-08-05", "planning_days": 1},
        "dispatch_scope": {"serviceId": "WEEKDAY", "depotId": "dep1"},
    }
    scopes = [
        SimpleNamespace(
            depot_ids=["dep1"],
            route_ids=["route-a"],
            service_ids=["WEEKDAY"],
            service_date="2025-08-05",
            route_selectors=["route-a"],
        ),
        SimpleNamespace(
            depot_ids=["dep1"],
            route_ids=["route-b"],
            service_ids=["WEEKDAY"],
            service_date="2025-08-05",
            route_selectors=["route-b"],
        ),
    ]
    build_calls: list[str] = []

    def fake_build_run_preparation(
        _scenario,
        _built_dir,
        _scenarios_dir,
        _routes_df,
        scenario_hash,
        *,
        scope,
        scope_payload,
        scope_hash,
    ):
        build_calls.append(scope_hash)
        return RunPreparation(
            scenario_id="scenario-cache",
            dataset_version="dataset-v1",
            scenario_hash=scenario_hash,
            scope_hash=scope_hash,
            solver_input_path=Path("C:/tmp/prepared.json"),
            prepared_input_id=f"prepared-{scope_hash}",
            scope_summary={"prepared_input_id": f"prepared-{scope_hash}"},
        )

    invalidate_scenario("scenario-cache")
    monkeypatch.setattr("src.runtime_scope.resolve_scope", lambda *_args, **_kwargs: scopes.pop(0))
    monkeypatch.setattr("bff.services.run_preparation._build_run_preparation", fake_build_run_preparation)

    first = get_or_build_run_preparation(scenario, Path("C:/tmp"), Path("C:/tmp"), None)
    second = get_or_build_run_preparation(scenario, Path("C:/tmp"), Path("C:/tmp"), None)

    assert first.prepared_input_id != second.prepared_input_id
    assert build_calls == [first.scope_hash, second.scope_hash]
