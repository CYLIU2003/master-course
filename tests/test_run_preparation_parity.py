import copy
import json

import pandas as pd

from bff.services.run_preparation import (
    _prep_cache,
    _scenario_hash,
    get_or_build_run_preparation,
)
from src.runtime_scope import resolve_scope


def _disable_tokyu_shards(monkeypatch, tmp_path) -> None:
    from src import tokyu_shard_loader

    monkeypatch.setattr(tokyu_shard_loader, "TOKYU_SHARD_ROOT", tmp_path / "missing_shards")


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


def _make_shard_root(tmp_path):
    shard_root = tmp_path / "tokyu_shards"
    trip_dir = shard_root / "trip_shards" / "meguro" / "route-01"
    stop_time_dir = shard_root / "stop_time_shards" / "meguro" / "route-01"
    trip_dir.mkdir(parents=True)
    stop_time_dir.mkdir(parents=True)
    (shard_root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "tokyu_core",
                "dataset_version": "2026-03-13",
                "build_timestamp": "2026-03-13T00:00:00Z",
                "available_depots": ["meguro"],
                "available_routes": ["route-01"],
                "available_day_types": ["weekday"],
            }
        ),
        encoding="utf-8",
    )
    (shard_root / "depots.json").write_text(
        json.dumps(
            {
                "depots": [
                    {
                        "depot_id": "meguro",
                        "depot_name": "Meguro",
                        "operator_id": "tokyu",
                        "lat": 35.0,
                        "lon": 139.0,
                        "route_ids": ["route-01"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (shard_root / "routes.json").write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "route_id": "route-01",
                        "route_short_name": "route-01",
                        "route_long_name": "route-01",
                        "operator_id": "tokyu",
                        "depot_ids": ["meguro"],
                        "available_day_types": ["weekday"],
                        "direction_count": 1,
                        "service_variant_types": ["main"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (shard_root / "depot_route_index.json").write_text(
        json.dumps(
            {
                "depots": [{"depot_id": "meguro", "route_ids": ["route-01"]}],
                "routes": [{"route_id": "route-01", "depot_ids": ["meguro"]}],
            }
        ),
        encoding="utf-8",
    )
    (shard_root / "depot_route_summary.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "depot_id": "meguro",
                        "route_id": "route-01",
                        "weekday_trip_count": 1,
                        "saturday_trip_count": 0,
                        "holiday_trip_count": 0,
                        "first_departure": "06:00:00",
                        "last_departure": "06:00:00",
                        "main_trip_count": 1,
                        "short_turn_trip_count": 0,
                        "depot_in_trip_count": 0,
                        "depot_out_trip_count": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (trip_dir / "weekday.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "trip_id": "shard-t001",
                        "depot_id": "meguro",
                        "route_id": "route-01",
                        "day_type": "weekday",
                        "direction": "outbound",
                        "trip_index": 0,
                        "origin_name": "A",
                        "destination_name": "B",
                        "origin_stop_id": "s001",
                        "destination_stop_id": "s002",
                        "departure_time": "06:00:00",
                        "arrival_time": "07:00:00",
                        "distance_hint_km": 5.0,
                        "runtime_minutes": 60,
                        "allowed_vehicle_types": ["BEV", "ICE"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (stop_time_dir / "weekday.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "trip_id": "shard-t001",
                        "depot_id": "meguro",
                        "route_id": "route-01",
                        "day_type": "weekday",
                        "stop_times": [
                            {
                                "seq": 1,
                                "stop_id": "s001",
                                "stop_name": "A",
                                "arrival_time": "06:00:00",
                                "departure_time": "06:00:00",
                            },
                            {
                                "seq": 2,
                                "stop_id": "s002",
                                "stop_name": "B",
                                "arrival_time": "07:00:00",
                                "departure_time": "07:00:00",
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (shard_root / "shard_manifest.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "artifact_kind": "trip_shard",
                        "depot_id": "meguro",
                        "route_id": "route-01",
                        "day_type": "weekday",
                        "artifact_path": "trip_shards/meguro/route-01/weekday.json",
                    },
                    {
                        "artifact_kind": "stop_time_shard",
                        "depot_id": "meguro",
                        "route_id": "route-01",
                        "day_type": "weekday",
                        "artifact_path": "stop_time_shards/meguro/route-01/weekday.json",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return shard_root


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


def test_simulation_and_optimization_share_run_preparation(tmp_path, monkeypatch):
    _disable_tokyu_shards(monkeypatch, tmp_path)
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


def test_random_seed_is_preserved_in_solver_input(tmp_path, monkeypatch):
    _disable_tokyu_shards(monkeypatch, tmp_path)
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
    assert solver_input["depot_ids"] == SCENARIO_A["depot_ids"]
    assert solver_input["route_ids"] == SCENARIO_A["route_ids"]
    assert solver_input["trip_count"] == 1


def test_dataset_version_is_preserved_in_solver_input(tmp_path, monkeypatch):
    _disable_tokyu_shards(monkeypatch, tmp_path)
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


def test_run_preparation_prefers_tokyu_shards_when_available(tmp_path, monkeypatch):
    from src import tokyu_shard_loader

    _prep_cache.clear()
    shard_root = _make_shard_root(tmp_path)
    monkeypatch.setattr(tokyu_shard_loader, "TOKYU_SHARD_ROOT", shard_root)

    prep = get_or_build_run_preparation(
        scenario=SCENARIO_A,
        built_dir=tmp_path / "missing_built",
        scenarios_dir=tmp_path / "prepared_inputs",
        routes_df=_make_routes_df(),
    )

    assert prep.is_valid, prep.error
    assert prep.scope_summary["load_source"] == "tokyu_shard"
    solver_input = json.loads(prep.solver_input_path.read_text(encoding="utf-8"))
    assert solver_input["trip_count"] == 1
    assert solver_input["trips"][0]["trip_id"] == "shard-t001"
    assert solver_input["trips"][0]["departure"] == "06:00"
    assert solver_input["trips"][0]["arrival"] == "07:00"
    assert len(solver_input["stop_time_sequences"]) == 2
    assert [row["stop_sequence"] for row in solver_input["stop_time_sequences"]] == [1, 2]
    assert [row["departure"] for row in solver_input["stop_time_sequences"]] == ["06:00", "07:00"]
