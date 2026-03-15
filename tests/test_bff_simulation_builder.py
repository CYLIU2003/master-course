import json
from pathlib import Path

import pandas as pd
import pytest

from bff.routers import scenarios, simulation
from bff.services.run_preparation import _prep_cache
from bff.store import job_store, scenario_store


@pytest.fixture()
def temp_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store_dir = tmp_path / "scenarios"
    app_context_path = tmp_path / "app_context.json"
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)
    monkeypatch.setattr(scenario_store, "_APP_CONTEXT_PATH", app_context_path)
    monkeypatch.setattr(job_store, "_JOB_DIR", jobs_dir)
    _prep_cache.clear()
    return store_dir


def _make_built_dir(tmp_path: Path, *, route_id: str, depot_id: str) -> tuple[Path, pd.DataFrame]:
    built_dir = tmp_path / "built"
    built_dir.mkdir(parents=True, exist_ok=True)
    route_code = route_id.split(":")[-1]
    routes_df = pd.DataFrame(
        [
            {
                "route_id": route_id,
                "route_code": route_code,
                "depot_id": depot_id,
                "route_name": route_code,
                "region": "tokyo",
            }
        ]
    )
    routes_df.to_parquet(built_dir / "routes.parquet")
    pd.DataFrame(
        [
            {
                "trip_id": "builder-t001",
                "route_id": route_id,
                "route_code": route_code,
                "depot_id": depot_id,
                "service_id": "WEEKDAY",
                "departure": "06:00",
                "arrival": "06:20",
                "direction": "outbound",
                "origin": "A",
                "destination": "B",
            }
        ]
    ).to_parquet(built_dir / "trips.parquet")
    pd.DataFrame(
        [
            {
                "trip_id": "builder-t001",
                "route_id": route_id,
                "route_code": route_code,
                "depot_id": depot_id,
                "service_id": "WEEKDAY",
                "stop_id": "stop:A",
                "stop_name": "A",
                "stop_sequence": 1,
                "arrival": "06:00",
                "departure": "06:00",
                "origin": "A",
                "destination": "B",
            },
            {
                "trip_id": "builder-t001",
                "route_id": route_id,
                "route_code": route_code,
                "depot_id": depot_id,
                "service_id": "WEEKDAY",
                "stop_id": "stop:B",
                "stop_name": "B",
                "stop_sequence": 2,
                "arrival": "06:20",
                "departure": "06:20",
                "origin": "A",
                "destination": "B",
            },
        ]
    ).to_parquet(built_dir / "timetables.parquet")
    return built_dir, routes_df


def _make_shard_root(tmp_path: Path, *, route_id: str, depot_id: str) -> Path:
    route_code = route_id.split(":")[-1]
    shard_root = tmp_path / "tokyu_shards"
    trip_dir = shard_root / "trip_shards" / depot_id / route_code
    stop_time_dir = shard_root / "stop_time_shards" / depot_id / route_code
    trip_dir.mkdir(parents=True, exist_ok=True)
    stop_time_dir.mkdir(parents=True, exist_ok=True)

    (shard_root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "tokyu_core",
                "dataset_version": "2026-03-14",
                "build_timestamp": "2026-03-14T00:00:00Z",
                "available_depots": [depot_id],
                "available_routes": [route_code],
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
                        "depot_id": depot_id,
                        "depot_name": depot_id,
                        "operator_id": "tokyu",
                        "lat": 35.0,
                        "lon": 139.0,
                        "route_ids": [route_code],
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
                        "route_id": route_code,
                        "route_short_name": route_code,
                        "route_long_name": route_code,
                        "operator_id": "tokyu",
                        "depot_ids": [depot_id],
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
                "depots": [{"depot_id": depot_id, "route_ids": [route_code]}],
                "routes": [
                    {
                        "route_id": route_code,
                        "depot_ids": [depot_id],
                        "available_day_types": ["weekday"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (shard_root / "depot_route_summary.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "depot_id": depot_id,
                        "route_id": route_code,
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
                        "trip_id": "builder-shard-t001",
                        "depot_id": depot_id,
                        "route_id": route_code,
                        "day_type": "weekday",
                        "direction": "outbound",
                        "service_variant": "main",
                        "origin_stop_id": "stop:A",
                        "destination_stop_id": "stop:B",
                        "origin_name": "A",
                        "destination_name": "B",
                        "departure_time": "06:00:00",
                        "arrival_time": "06:20:00",
                        "runtime_minutes": 20,
                        "distance_hint_km": 5.0,
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
                        "trip_id": "builder-shard-t001",
                        "depot_id": depot_id,
                        "route_id": route_code,
                        "day_type": "weekday",
                        "direction": "outbound",
                        "origin_stop_id": "stop:A",
                        "destination_stop_id": "stop:B",
                        "stop_times": [
                            {
                                "seq": 1,
                                "stop_id": "stop:A",
                                "stop_name": "A",
                                "arrival_time": "06:00:00",
                                "departure_time": "06:00:00",
                            },
                            {
                                "seq": 2,
                                "stop_id": "stop:B",
                                "stop_name": "B",
                                "arrival_time": "06:20:00",
                                "departure_time": "06:20:00",
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
                        "depot_id": depot_id,
                        "route_id": route_code,
                        "day_type": "weekday",
                        "artifact_path": f"trip_shards/{depot_id}/{route_code}/weekday.json",
                    },
                    {
                        "artifact_kind": "stop_time_shard",
                        "depot_id": depot_id,
                        "route_id": route_code,
                        "day_type": "weekday",
                        "artifact_path": f"stop_time_shards/{depot_id}/{route_code}/weekday.json",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return shard_root


def test_editor_bootstrap_returns_builder_only_payload(temp_store_dir: Path):
    meta = scenarios.create_scenario(scenarios.CreateScenarioBody(name="Builder case"))

    payload = scenarios.get_editor_bootstrap(meta["id"])

    assert payload["scenario"]["id"] == meta["id"]
    assert payload["depots"]
    assert payload["routes"]
    assert payload["vehicleTemplates"]
    assert payload["depotRouteIndex"]
    assert payload["availableDayTypes"]
    assert "trips" not in payload
    assert "timetableRows" not in payload
    assert payload["builderDefaults"]["demandChargeCostPerKw"] == 1200.0
    assert payload["builderDefaults"]["dieselPricePerL"] == 150.0
    assert payload["builderDefaults"]["depotPowerLimitKw"] == 200.0
    assert len(payload["builderDefaults"]["touPricing"]) == 3


def test_prepare_and_run_prepared_simulation_builder_flow(
    temp_store_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from src import tokyu_shard_loader

    monkeypatch.setattr(tokyu_shard_loader, "TOKYU_SHARD_ROOT", tmp_path / "missing_shards")
    meta = scenarios.create_scenario(scenarios.CreateScenarioBody(name="Builder simulation"))
    bootstrap = scenarios.get_editor_bootstrap(meta["id"])
    selected_depot_id = bootstrap["builderDefaults"]["selectedDepotIds"][0]
    selected_route_id = bootstrap["depotRouteIndex"][selected_depot_id][0]
    built_dir, routes_df = _make_built_dir(
        tmp_path,
        route_id=selected_route_id,
        depot_id=selected_depot_id,
    )
    prepared_root = tmp_path / "prepared_inputs"
    monkeypatch.setattr(simulation, "_prepared_inputs_root", lambda: prepared_root)
    monkeypatch.setattr(simulation, "_submit_simulation_job", lambda **_: True)

    prepare_result = simulation.prepare_simulation(
        meta["id"],
        simulation.PrepareSimulationBody(
            selected_depot_ids=[selected_depot_id],
            selected_route_ids=[selected_route_id],
            day_type="WEEKDAY",
        ),
        _app_state={"built_dir": built_dir, "routes_df": routes_df, "built_ready": True},
    )

    assert prepare_result["ready"] is True
    assert prepare_result["tripCount"] == 1
    assert prepare_result["primaryDepotId"] == selected_depot_id
    persisted = scenario_store.get_scenario_document(meta["id"], repair_missing_master=False)
    assert persisted["dispatch_scope"]["serviceId"] == "WEEKDAY"
    assert persisted["dispatch_scope"]["depotId"] == selected_depot_id
    assert persisted["vehicles"]

    job = simulation.run_prepared_simulation(
        meta["id"],
        simulation.RunPreparedSimulationBody(
            prepared_input_id=prepare_result["preparedInputId"],
            source="duties",
        ),
        _app_state={"built_dir": built_dir, "routes_df": routes_df, "built_ready": True},
    )

    assert job["status"] == "pending"
    assert job["metadata"]["prepared_input_id"] == prepare_result["preparedInputId"]


def test_prepare_and_run_prepared_simulation_builder_flow_uses_tokyu_shards(
    temp_store_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from src import tokyu_shard_loader

    meta = scenarios.create_scenario(scenarios.CreateScenarioBody(name="Builder shard simulation"))
    bootstrap = scenarios.get_editor_bootstrap(meta["id"])
    selected_depot_id = bootstrap["builderDefaults"]["selectedDepotIds"][0]
    selected_route_id = bootstrap["depotRouteIndex"][selected_depot_id][0]
    shard_root = _make_shard_root(
        tmp_path,
        route_id=selected_route_id,
        depot_id=selected_depot_id,
    )
    monkeypatch.setattr(tokyu_shard_loader, "TOKYU_SHARD_ROOT", shard_root)

    doc = scenario_store.get_scenario_document(meta["id"], repair_missing_master=False)
    doc["timetable_rows"] = []
    doc["stop_timetables"] = []
    doc["trips"] = []
    doc["graph"] = None
    doc["duties"] = None
    doc["feed_context"] = {
        **dict(doc.get("feed_context") or {}),
        "source": "tokyu_shards",
    }
    doc["runtime_features"] = {
        "tokyuShards": {
            "enabled": True,
            "datasetId": "tokyu_core",
            "root": str(shard_root),
        }
    }
    scenario_store._save(doc)

    prepared_root = tmp_path / "prepared_inputs"
    monkeypatch.setattr(simulation, "_prepared_inputs_root", lambda: prepared_root)
    monkeypatch.setattr(simulation, "_submit_simulation_job", lambda **_: True)

    prepare_result = simulation.prepare_simulation(
        meta["id"],
        simulation.PrepareSimulationBody(
            selected_depot_ids=[selected_depot_id],
            selected_route_ids=[selected_route_id],
            day_type="WEEKDAY",
        ),
        _app_state={
            "built_dir": tmp_path / "missing_built",
            "routes_df": pd.DataFrame(doc["routes"]),
            "built_ready": True,
        },
    )

    assert prepare_result["ready"] is True
    assert prepare_result["tripCount"] == 1
    assert prepare_result["timetableRowCount"] == 2
    assert prepare_result["primaryDepotId"] == selected_depot_id
    assert prepare_result["scopeSummary"]["load_source"] == "tokyu_shard"
    assert any("Tokyu shard runtime artifacts" in item for item in prepare_result["warnings"])

    prepared_payload = json.loads(
        (
            prepared_root
            / meta["id"]
            / f"{prepare_result['preparedInputId']}.json"
        ).read_text(encoding="utf-8")
    )
    assert prepared_payload["trips"][0]["source"] == "tokyu_shard"
    assert prepared_payload["trips"][0]["departure"] == "06:00"
    assert [row["stop_sequence"] for row in prepared_payload["stop_time_sequences"]] == [1, 2]
    assert [row["departure"] for row in prepared_payload["stop_time_sequences"]] == ["06:00", "06:20"]

    job = simulation.run_prepared_simulation(
        meta["id"],
        simulation.RunPreparedSimulationBody(
            prepared_input_id=prepare_result["preparedInputId"],
            source="duties",
        ),
        _app_state={
            "built_dir": tmp_path / "missing_built",
            "routes_df": pd.DataFrame(doc["routes"]),
            "built_ready": True,
        },
    )

    assert job["status"] == "pending"
    assert job["metadata"]["prepared_input_id"] == prepare_result["preparedInputId"]


def test_prepare_keeps_existing_scope_flags_when_body_does_not_override(
    temp_store_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from src import tokyu_shard_loader

    monkeypatch.setattr(tokyu_shard_loader, "TOKYU_SHARD_ROOT", tmp_path / "missing_shards")
    meta = scenarios.create_scenario(scenarios.CreateScenarioBody(name="Builder scope flags"))
    bootstrap = scenarios.get_editor_bootstrap(meta["id"])
    selected_depot_id = bootstrap["builderDefaults"]["selectedDepotIds"][0]
    selected_route_id = bootstrap["depotRouteIndex"][selected_depot_id][0]
    built_dir, routes_df = _make_built_dir(
        tmp_path,
        route_id=selected_route_id,
        depot_id=selected_depot_id,
    )
    prepared_root = tmp_path / "prepared_inputs"
    monkeypatch.setattr(simulation, "_prepared_inputs_root", lambda: prepared_root)

    scenario_store.set_dispatch_scope(
        meta["id"],
        {
            "depotSelection": {
                "depotIds": [selected_depot_id],
                "primaryDepotId": selected_depot_id,
            },
            "tripSelection": {
                "includeShortTurn": False,
                "includeDepotMoves": False,
                "includeDeadhead": True,
            },
            "allowIntraDepotRouteSwap": True,
            "allowInterDepotSwap": True,
        },
    )

    prepare_result = simulation.prepare_simulation(
        meta["id"],
        simulation.PrepareSimulationBody(
            selected_depot_ids=[selected_depot_id],
            selected_route_ids=[selected_route_id],
            day_type="WEEKDAY",
        ),
        _app_state={"built_dir": built_dir, "routes_df": routes_df, "built_ready": True},
    )

    assert prepare_result["ready"] is True
    persisted = scenario_store.get_scenario_document(meta["id"], repair_missing_master=False)
    assert persisted["dispatch_scope"]["tripSelection"]["includeShortTurn"] is False
    assert persisted["dispatch_scope"]["tripSelection"]["includeDepotMoves"] is False
    assert persisted["dispatch_scope"]["allowIntraDepotRouteSwap"] is True
    assert persisted["dispatch_scope"]["allowInterDepotSwap"] is True


def test_update_dispatch_scope_router_preserves_unspecified_swap_flags(
    temp_store_dir: Path,
):
    meta = scenarios.create_scenario(scenarios.CreateScenarioBody(name="Dispatch scope router"))

    scope = scenarios.update_dispatch_scope(
        meta["id"],
        scenarios.UpdateDispatchScopeBody(
            allowIntraDepotRouteSwap=True,
            allowInterDepotSwap=True,
        ),
    )
    assert scope["allowIntraDepotRouteSwap"] is True
    assert scope["allowInterDepotSwap"] is True

    scope = scenarios.update_dispatch_scope(
        meta["id"],
        scenarios.UpdateDispatchScopeBody(
            allowIntraDepotRouteSwap=False,
        ),
    )
    assert scope["allowIntraDepotRouteSwap"] is False
    assert scope["allowInterDepotSwap"] is True
