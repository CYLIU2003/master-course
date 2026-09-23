from __future__ import annotations

from bff.services import run_preparation as preparation_module
from bff.services.run_preparation import RunPreparation, _random_seed, _scenario_hash


def _base_scenario() -> dict:
    return {
        "meta": {
            "id": "scenario-1",
            "operatorId": "tokyu",
            "createdAt": "2026-03-21T00:00:00Z",
            "updatedAt": "2026-03-21T00:00:00Z",
        },
        "feed_context": {
            "datasetId": "tokyu_core",
            "snapshotId": "2026-03-21",
        },
        "scenario_overlay": {
            "dataset_id": "tokyu_core",
            "dataset_version": "2026-03-21",
            "random_seed": 42,
        },
        "dispatch_scope": {
            "depotSelection": {
                "mode": "include",
                "depotIds": ["tokyu:depot:1"],
                "primaryDepotId": "tokyu:depot:1",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["tokyu:route:1"],
                "excludeRouteIds": [],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {
                "includeShortTurn": True,
                "includeDepotMoves": False,
                "includeDeadhead": True,
            },
            "depotId": "tokyu:depot:1",
            "serviceId": "WEEKDAY",
        },
        "simulation_config": {
            "day_type": "WEEKDAY",
            "solver_mode": "mode_milp_only",
            "time_limit_seconds": 300,
        },
        "depots": [{"id": "tokyu:depot:1", "name": "Depot 1"}],
        "routes": [{"id": "tokyu:route:1", "name": "Route 1"}],
        "vehicles": [{"id": "veh-1", "depotId": "tokyu:depot:1", "type": "BEV"}],
        "chargers": [{"id": "charger-1", "siteId": "tokyu:depot:1", "powerKw": 90}],
    }


def test_scenario_hash_ignores_heavy_runtime_artifacts() -> None:
    shallow_doc = _base_scenario() | {
        "timetable_rows": [],
        "stop_timetables": [],
        "trips": None,
        "graph": None,
        "blocks": None,
        "duties": None,
        "dispatch_plan": None,
        "simulation_result": None,
        "optimization_result": None,
    }
    full_doc = _base_scenario() | {
        "refs": {"artifactStore": "outputs/scenarios/scenario-1/artifacts.sqlite"},
        "stats": {"tripCount": 12, "dutyCount": 4},
        "timetable_rows": [{"trip_id": "trip-1"}],
        "stop_timetables": [{"trip_id": "trip-1", "stop_sequence": 1}],
        "trips": [{"trip_id": "trip-1"}],
        "graph": {"arcs": [{"from_trip_id": "trip-1", "to_trip_id": "trip-2"}]},
        "blocks": [{"block_id": "block-1"}],
        "duties": [{"duty_id": "duty-1"}],
        "dispatch_plan": {"plans": [{"plan_id": "plan-1"}]},
        "simulation_result": {"summary": {"vehicle_count_used": 1}},
        "optimization_result": {"solver_status": "FEASIBLE"},
    }

    assert _scenario_hash(shallow_doc) == _scenario_hash(full_doc)


def test_random_seed_preserves_explicit_zero() -> None:
    scenario = _base_scenario()
    scenario["scenario_overlay"]["random_seed"] = 0

    assert _random_seed(scenario) == 0


def _stub_preparation_identity(monkeypatch, tmp_path):
    from src import runtime_scope

    prepared_directory = tmp_path / "prepared_inputs" / "scenario-1"
    prepared_directory.mkdir(parents=True)
    scope = object()
    monkeypatch.setattr(runtime_scope, "resolve_scope", lambda _scenario, _routes: scope)
    monkeypatch.setattr(preparation_module, "_scenario_id", lambda _scenario: "scenario-1")
    monkeypatch.setattr(preparation_module, "_dataset_id", lambda _scenario: "dataset-1")
    monkeypatch.setattr(preparation_module, "_dataset_version", lambda _scenario: "dataset-version-1")
    monkeypatch.setattr(preparation_module, "_scenario_hash", lambda _scenario: "scenario-hash")
    monkeypatch.setattr(preparation_module, "_scope_cache_payload", lambda _scenario, _scope: {"scope": "fixed"})
    monkeypatch.setattr(preparation_module, "_scope_hash", lambda _scope: "scope-hash")
    monkeypatch.setattr(preparation_module, "_prepared_input_id",
                        lambda scenario_hash, scope_hash: f"prepared-{scenario_hash}-{scope_hash}")
    monkeypatch.setattr(preparation_module, "_prepared_input_dir",
                        lambda _scenarios_dir, _scenario_id: prepared_directory)
    return prepared_directory


def test_pinned_stale_prepared_input_is_rejected_without_rebuilding(monkeypatch, tmp_path):
    _stub_preparation_identity(monkeypatch, tmp_path)
    monkeypatch.setattr(preparation_module, "_build_run_preparation",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not rebuild")))

    result = preparation_module.get_or_build_run_preparation(
        scenario={}, built_dir=tmp_path, scenarios_dir=tmp_path, routes_df=object(),
        expected_prepared_input_id="prepared-old-scenario-scope",
    )

    assert result.is_valid is False
    assert result.prepared_input_id == "prepared-scenario-hash-scope-hash"
    assert result.error_code == "PREPARED_INPUT_STALE"


def test_pinned_prepared_input_reuses_existing_immutable_file(monkeypatch, tmp_path):
    prepared_directory = _stub_preparation_identity(monkeypatch, tmp_path)
    prepared_id = "prepared-scenario-hash-scope-hash"
    prepared_path = prepared_directory / f"{prepared_id}.json"
    prepared_path.write_text("{}", encoding="utf-8")
    loaded = []

    def load_existing(**kwargs):
        loaded.append(kwargs)
        return RunPreparation(
            scenario_id="scenario-1", dataset_version="dataset-version-1",
            scenario_hash="scenario-hash", scope_hash="scope-hash",
            solver_input_path=prepared_path, prepared_input_id=prepared_id,
            scope_summary={"trip_count": 1},
        )

    monkeypatch.setattr(preparation_module, "_run_preparation_from_persisted_input", load_existing)
    monkeypatch.setattr(preparation_module, "_build_run_preparation",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not rebuild")))

    result = preparation_module.get_or_build_run_preparation(
        scenario={}, built_dir=tmp_path, scenarios_dir=tmp_path, routes_df=object(),
        expected_prepared_input_id=prepared_id,
    )

    assert result.is_valid is True
    assert result.prepared_input_id == prepared_id
    assert len(loaded) == 1


def test_pinned_missing_prepared_input_is_not_created_implicitly(monkeypatch, tmp_path):
    _stub_preparation_identity(monkeypatch, tmp_path)
    monkeypatch.setattr(preparation_module, "_build_run_preparation",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not rebuild")))

    result = preparation_module.get_or_build_run_preparation(
        scenario={}, built_dir=tmp_path, scenarios_dir=tmp_path, routes_df=object(),
        expected_prepared_input_id="prepared-scenario-hash-scope-hash",
    )

    assert result.is_valid is False
    assert result.error_code == "PREPARED_INPUT_MISSING"
