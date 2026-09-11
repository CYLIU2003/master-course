from __future__ import annotations

import json
import tracemalloc
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bff.desktop_server import DesktopAuthentication
from bff.routers import desktop, scenarios
from bff.store import (
    desktop_store,
    master_data_store,
    scenario_meta_store,
    scenario_store,
    trip_store,
)


@pytest.fixture
def desktop_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario_store, "_STORE_DIR", tmp_path)
    sid = "desktop-test"
    refs = scenario_meta_store.default_refs(tmp_path, sid)
    scenario_meta_store.save_meta(
        tmp_path,
        sid,
        {"meta": {"id": sid, "name": "大規模データ", "status": "draft"}, "refs": refs},
    )
    master_data_store.save_master_data(
        Path(refs["masterData"]),
        {"routes": [{"id": f"r{i}"} for i in range(1001)], "timetable_import_meta": {}},
    )
    return sid, refs


def test_desktop_authentication_requires_token_for_every_http_path():
    app = FastAPI()
    app.get("/health")(lambda: {"status": "ok"})
    client = TestClient(DesktopAuthentication(app, "a" * 64))
    assert client.get("/health").status_code == 401
    assert (
        client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert client.get(
        "/health", headers={"Authorization": "Bearer " + "a" * 64}
    ).json() == {"status": "ok"}


def test_desktop_table_rejects_unbounded_requests_and_path_traversal(desktop_scenario):
    app = FastAPI()
    app.include_router(desktop.router)
    client = TestClient(app)
    assert (
        client.get(
            "/desktop/scenarios/desktop-test/tables/routes?limit=251"
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/desktop/scenarios/desktop-test/tables/routes?offset=-1"
        ).status_code
        == 422
    )
    assert (
        client.get("/desktop/scenarios/desktop-test/tables/secrets").status_code == 422
    )
    assert client.get("/desktop/scenarios/..%5Cother/tables/routes").status_code == 422
    response = client.get(
        "/desktop/scenarios/desktop-test/tables/routes?offset=997&limit=250"
    )
    assert response.json()["items"] == [{"id": f"r{i}"} for i in range(997, 1001)]
    assert response.json()["total"] == 1001


def test_paged_timetable_does_not_hydrate_other_data(desktop_scenario):
    sid, refs = desktop_scenario
    rows = [
        {
            "trip_id": f"t{i}",
            "service_id": "SAT" if i % 2 else "WEEKDAY",
            "operator_id": "TokyuBus",
            "distance_km": i + 1,
        }
        for i in range(1001)
    ]
    trip_store.save_timetable_rows(Path(refs["artifactStore"]), rows)
    with patch.object(
        scenario_store, "get_field", side_effect=AssertionError("full read")
    ), patch.object(
        scenario_store, "_load_shallow", side_effect=AssertionError("master read")
    ):
        result = scenarios.get_timetable(sid, service_id="SAT", limit=10, offset=490)
    assert result["items"] == rows[981::2]
    assert result["total"] == 500


def test_summary_matches_previous_semantics_without_hydration(desktop_scenario):
    sid, refs = desktop_scenario
    rows = [
        {
            "trip_id": "a",
            "route_id": "r",
            "service_id": "WEEKDAY",
            "departure": "05:10",
            "arrival": "06:00",
            "distance_km": 2.3456,
        },
        {"trip_id": "a__v1", "route_id": "r", "distance_km": 99},
        {
            "trip_id": "b",
            "route_id": "s",
            "service_id": "SAT",
            "departure": "25:00",
            "arrival": "26:00",
            "distance_km": 3.4,
        },
        {
            "trip_id": "c",
            "route_id": "",
            "service_id": "SAT",
            "departure": "",
            "arrival": "",
            "distance_km": None,
        },
    ]
    trip_store.save_timetable_rows(Path(refs["artifactStore"]), rows)
    expected = scenario_store._build_timetable_summary_artifact(rows, {})
    with patch.object(
        trip_store, "page_timetable_rows", side_effect=AssertionError("full read")
    ), patch.object(
        scenario_store, "_load_shallow", side_effect=AssertionError("master read")
    ):
        assert scenario_store.get_field_summary(sid, "timetable_rows") == expected


def test_parquet_deep_page_skips_unrelated_row_groups(tmp_path):
    pytest.importorskip("pyarrow")
    path = tmp_path / "rows.parquet"
    rows = [{"id": index} for index in range(100_000)]
    trip_store.save_parquet_rows(path, rows)
    real = trip_store.pq.ParquetFile(path)
    seen = []

    class ObservedFile:
        metadata = real.metadata

        def iter_batches(self, **kwargs):
            seen.extend(kwargs["row_groups"])
            return real.iter_batches(**kwargs)

    with patch.object(trip_store.pq, "ParquetFile", return_value=ObservedFile()):
        assert (
            trip_store.page_parquet_rows(path, offset=99_750, limit=250) == rows[-250:]
        )
        assert (
            trip_store.page_parquet_rows(path, offset=16_380, limit=10)
            == rows[16_380:16_390]
        )
        assert trip_store.page_parquet_rows(path, offset=100_000, limit=250) == []
    assert seen == [6, 0, 1]


def test_result_projection_keeps_null_zero_and_skips_large_trajectories(tmp_path):
    path = tmp_path / "result.json"
    with path.open("w", encoding="utf-8") as output:
        output.write(
            '{"objective_value":0,"final_accounting_total_cost_jpy":null,"trajectory":['
        )
        output.write(",".join('{"trip":"x","soc":52.0}' for _ in range(100_000)))
        output.write('],"solution_validity":{"research_acceptance_status":"REJECTED"}}')
    tracemalloc.start()
    projected = desktop_store._json_projection(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert projected == {
        "objective_value": 0,
        "final_accounting_total_cost_jpy": None,
        "solution_validity": {"research_acceptance_status": "REJECTED"},
    }
    assert peak < 6 * 1024 * 1024


def test_index_observes_updates_and_deletions_without_hydrating(desktop_scenario):
    sid, _ = desktop_scenario
    assert desktop_store.scenario_page("大規模", 0, 1)["total"] == 1
    path = scenario_meta_store.scenario_path(scenario_store._STORE_DIR, sid)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["meta"]["name"] = "更新後の名前"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert desktop_store.scenario_page("大規模", 0, 1)["total"] == 0
    assert (
        desktop_store.scenario_page("更新", 0, 1)["items"][0]["name"] == "更新後の名前"
    )
    path.unlink()
    assert desktop_store.scenario_page("", 0, 1)["total"] == 0


def test_sqlite_result_projection_streams_and_refreshes(desktop_scenario):
    sid, refs = desktop_scenario
    path = Path(refs["artifactStore"])
    trip_store.save_scalar(path, "optimization_result", None)
    assert desktop_store.result_summary(sid)["available"] is False
    trip_store.save_scalar(
        path,
        "optimization_result",
        {
            "feasible": False,
            "objective_value": 0,
            "trajectory": [{"soc": 10}] * 100_000,
        },
    )
    tracemalloc.start()
    result = desktop_store.result_summary(sid)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result["values"] == {"feasible": False, "objective_value": 0}
    assert peak < 6 * 1024 * 1024
    trip_store.save_scalar(
        path, "optimization_result", {"feasible": True, "objective_value": 100}
    )
    assert desktop_store.result_summary(sid)["values"]["objective_value"] == 100


def test_sqlite_legacy_nonfinite_values_are_displayed_without_rewriting(desktop_scenario):
    import hashlib

    sid, refs = desktop_scenario
    path = Path(refs["artifactStore"])
    trip_store.save_scalar(path, "optimization_result", {
        "objective_value": float("inf"),
        "mip_gap": float("nan"),
        "feasible": False,
        "ignored": [float("-inf")],
    })
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    result = desktop_store.result_summary(sid)
    assert result["values"] == {
        "objective_value": "Infinity", "mip_gap": "NaN", "feasible": False,
    }
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
