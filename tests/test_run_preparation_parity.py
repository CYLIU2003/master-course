import copy
import json

import pandas as pd

from bff.services.run_preparation import (
    _prep_cache,
    _scenario_hash,
    get_or_build_run_preparation,
)
from src.runtime_scope import resolve_scope


def _make_routes_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "route_id": "tokyu:route-01",
                "route_code": "route-01",
                "depot_id": "meguro",
                "route_name": "route-01",
                "region": "tokyo",
            },
            {
                "route_id": "tokyu:route-02",
                "route_code": "route-02",
                "depot_id": "meguro",
                "route_name": "route-02",
                "region": "tokyo",
            },
        ]
    )


def _make_built_dir(tmp_path):
    built_dir = tmp_path / "tokyu_core"
    built_dir.mkdir(parents=True)
    _make_routes_df().to_parquet(built_dir / "routes.parquet")
    pd.DataFrame(
        [
            {
                "trip_id": "t001",
                "route_id": "tokyu:route-01",
                "route_code": "route-01",
                "depot_id": "meguro",
                "service_type": "weekday",
                "departure_time": "06:00:00",
                "arrival_time": "07:00:00",
                "direction_id": 0,
            }
        ]
    ).to_parquet(built_dir / "trips.parquet")
    pd.DataFrame(
        [
            {
                "trip_id": "t001",
                "route_id": "tokyu:route-01",
                "depot_id": "meguro",
                "stop_sequence": 1,
                "stop_id": "s001",
                "arrival_time": "06:00:00",
                "departure_time": "06:00:00",
                "service_type": "weekday",
            }
        ]
    ).to_parquet(built_dir / "timetables.parquet")
    return built_dir


SCENARIO_A = {
    "scenario_id": "test-parity-001",
    "dataset_id": "tokyu_core",
    "dataset_version": "2026-03-13",
    "random_seed": 42,
    "depot_ids": ["meguro"],
    "route_ids": ["route-01", "route-02"],
    "fleet": {"n_bev": 5, "n_ice": 10},
    "charging_constraints": {"max_charge_kw": 50},
    "cost_coefficients": {"tou_peak": 30.0},
    "solver_config": {"time_limit_s": 300},
}


def test_same_scenario_produces_same_hash():
    assert _scenario_hash(SCENARIO_A) == _scenario_hash(copy.deepcopy(SCENARIO_A))


def test_scenario_hash_changes_on_field_change():
    modified = copy.deepcopy(SCENARIO_A)
    modified["random_seed"] = 99
    assert _scenario_hash(SCENARIO_A) != _scenario_hash(modified)


def test_simulation_and_optimization_share_run_preparation(tmp_path):
    _prep_cache.clear()
    built_dir = _make_built_dir(tmp_path)
    routes_df = _make_routes_df()
    scenarios_dir = tmp_path / "scenarios"

    prep_sim = get_or_build_run_preparation(
        scenario=SCENARIO_A,
        built_dir=built_dir,
        scenarios_dir=scenarios_dir,
        routes_df=routes_df,
    )

    _prep_cache.clear()

    prep_opt = get_or_build_run_preparation(
        scenario=SCENARIO_A,
        built_dir=built_dir,
        scenarios_dir=scenarios_dir,
        routes_df=routes_df,
    )

    assert prep_sim.is_valid, prep_sim.error
    assert prep_opt.is_valid, prep_opt.error
    assert prep_sim.scenario_hash == prep_opt.scenario_hash
    assert prep_sim.scope_summary == prep_opt.scope_summary
    assert prep_sim.dataset_version == prep_opt.dataset_version

    sim_input = json.loads(prep_sim.solver_input_path.read_text(encoding="utf-8"))
    opt_input = json.loads(prep_opt.solver_input_path.read_text(encoding="utf-8"))
    for field in ["dataset_version", "random_seed", "depot_ids", "route_ids", "trip_count"]:
        assert sim_input.get(field) == opt_input.get(field)


def test_scope_resolution_is_deterministic(tmp_path):
    del tmp_path
    routes_df = _make_routes_df()
    scope1 = resolve_scope(SCENARIO_A, routes_df)
    scope2 = resolve_scope(SCENARIO_A, routes_df)
    assert sorted(scope1.depot_ids) == sorted(scope2.depot_ids)
    assert sorted(scope1.route_ids) == sorted(scope2.route_ids)


def test_random_seed_is_preserved_in_solver_input(tmp_path):
    _prep_cache.clear()
    prep = get_or_build_run_preparation(
        scenario=SCENARIO_A,
        built_dir=_make_built_dir(tmp_path),
        scenarios_dir=tmp_path / "scenarios",
        routes_df=_make_routes_df(),
    )
    assert prep.is_valid, prep.error
    solver_input = json.loads(prep.solver_input_path.read_text(encoding="utf-8"))
    assert solver_input["random_seed"] == SCENARIO_A["random_seed"]


def test_dataset_version_is_preserved_in_solver_input(tmp_path):
    _prep_cache.clear()
    prep = get_or_build_run_preparation(
        scenario=SCENARIO_A,
        built_dir=_make_built_dir(tmp_path),
        scenarios_dir=tmp_path / "scenarios",
        routes_df=_make_routes_df(),
    )
    assert prep.is_valid
    solver_input = json.loads(prep.solver_input_path.read_text(encoding="utf-8"))
    assert solver_input["dataset_version"] == SCENARIO_A["dataset_version"]
