from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bff.routers import desktop, scenarios
from bff.services import desktop_configuration as config, desktop_timetable as timetable, desktop_weather as weather
from bff.store import scenario_store, desktop_store, trip_store


@pytest.fixture
def editable(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario_store, "_STORE_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(scenarios, "_ensure_runtime_master_data", lambda _: None)
    monkeypatch.setattr(timetable, "outputs_root", lambda: tmp_path / "output")
    sid = scenario_store.create_scenario("desktop editor", "test", "mode_milp_only")["id"]
    scenario_store.set_field(sid, "depots", [{"id": "d", "name": "Depot"}])
    scenario_store.set_field(sid, "routes", [{"id": "r", "name": "Route", "depotId": "d", "enabled": True}])
    scenario_store.set_dispatch_scope(sid, {"depotSelection": {"mode": "include", "depotIds": ["d"]}, "routeSelection": {"mode": "include", "includeRouteIds": ["r"]}})
    scenario_store.set_field(sid, "simulation_config", {"service_date": "2025-02-03", "planning_days": 7, "initial_soc": 0.8, "final_soc_target_percent": 80, "rolling_window_terminal_policy": "day_ahead_boundary_state"})
    return sid


def test_configuration_preserves_scope_syncs_soc_and_dates(editable):
    before = config.configuration(editable)
    result = config.save_configuration(editable, {"initialSoc": .65, "planningDays": 2, "gridFlatPricePerKwh": 0, "enableWeatherOperationPolicy": False}, before["revision"])
    saved = scenario_store.get_field(editable, "simulation_config")
    assert saved["initial_soc"] == .65
    assert saved["initial_soc_percent"] == 65
    assert saved["service_dates"] == ["2025-02-03", "2025-02-04"]
    assert saved["planning_horizon_hours"] == 48
    assert result["values"]["selectedDepotIds"] == before["values"]["selectedDepotIds"]
    assert result["values"]["selectedRouteIds"] == before["values"]["selectedRouteIds"]
    assert result["values"]["gridFlatPricePerKwh"] == 0
    assert result["revision"] != before["revision"]
    with pytest.raises(HTTPException) as error:
        config.save_configuration(editable, {"timeLimitSeconds": 1}, before["revision"])
    assert error.value.status_code == 409


def test_bess_free_terminal_is_persisted_without_changing_bev(editable):
    before = config.configuration(editable)
    asset = {"depot_id": "d", "bess_enabled": True, "bess_energy_kwh": 100, "bess_power_kw": 10, "bess_initial_soc_kwh": 50, "bess_soc_min_kwh": 20, "bess_soc_max_kwh": 80, "bess_terminal_soc_min_kwh": 20, "bess_terminal_soc_target_kwh": 0, "bess_terminal_soc_policy": "minimum_only", "bess_balance_period": "evaluation_period"}
    result = config.save_configuration(editable, {"depotEnergyAssets": [asset], "bessBalancePeriod": "evaluation_period", "rollingBessTerminalPolicy": "minimum_only"}, before["revision"])
    saved = scenario_store.get_field(editable, "simulation_config")
    assert saved["bess_balance_period"] == "evaluation_period"
    assert saved["rolling_bess_terminal_policy"] == "minimum_only"
    assert saved["rolling_window_terminal_policy"] == "day_ahead_boundary_state"
    assert saved["final_soc_target_percent"] == 80
    assert result["values"]["depotEnergyAssets"][0]["bess_terminal_soc_policy"] == "minimum_only"


def test_execution_profile_is_saved_in_prepared_hash_input(editable):
    from bff.services.run_preparation import _scenario_hash
    before = config.configuration(editable)
    original = scenario_store.get_scenario_document_shallow(editable)
    previous_hash = _scenario_hash(original)
    result = config.save_configuration(editable, {"executionProfile": "alns_no_gurobi_v1", "solverMode": "mode_alns_only"}, before["revision"])
    assert result["values"]["executionProfile"] == "alns_no_gurobi_v1"
    changed = scenario_store.get_scenario_document_shallow(editable)
    assert changed["simulation_config"]["execution_profile"] == "alns_no_gurobi_v1"
    assert _scenario_hash(changed) != previous_hash


def test_configuration_does_not_hydrate_trip_or_result_collections(editable):
    original = desktop_store.collection
    def bounded(sid, key):
        assert key not in {"trips", "timetable_rows", "optimization_result"}
        return original(sid, key)
    with patch.object(desktop_store, "collection", side_effect=bounded):
        assert config.configuration(editable)["revision"]


def test_configuration_rejects_invalid_patch_before_writing(editable):
    before = config.configuration(editable)
    for changes in ({"invented": 1}, {"initialSoc": None}, {"socMin": 0.99, "socMax": 0.1}):
        with pytest.raises((ValueError, HTTPException)):
            config.save_configuration(editable, changes, before["revision"])
        assert config.configuration(editable) == before


def original_rows():
    base = {"trip_id": "001", "route_id": "002", "service_id": "003", "departure": "25:10", "arrival": "26:00", "operator_id": "0001", "distance_km": 2.5, "count": 2, "active": False, "nullable": None, "nested": {"japanese": "日本語"}}
    return [base, {**base, "trip_id": "001__v1", "extra": [0, "a"]}]


def test_timetable_roundtrip_preserves_hidden_rows_types_and_missing_fields(editable):
    original = original_rows()
    scenario_store.set_field(editable, "timetable_rows", original)
    exported = timetable.export_timetable(editable)
    assert exported["rows"] == 2
    content = Path(exported["path"]).read_text(encoding="utf-8-sig")
    assert timetable.parse_timetable_csv(content) == original
    preview = timetable.import_timetable(editable, content, False, "")
    assert not preview["applied"]
    assert Path(timetable.export_timetable(editable)["path"]).read_text(encoding="utf-8-sig") == content
    applied = timetable.import_timetable(editable, content, True, preview["revision"])
    assert applied["applied"] and Path(applied["previous_timetable"]["path"]).exists()


@pytest.mark.parametrize("replacement", ["UNKNOWN", "", "unknown"])
def test_csv_rejects_missing_operator(replacement):
    row = original_rows()[0]
    row["operator_id"] = replacement
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=row)
    writer.writeheader(); writer.writerow(row)
    with pytest.raises(ValueError):
        timetable.parse_timetable_csv(output.getvalue())


def test_import_requires_unchanged_preview(editable):
    output = io.StringIO()
    row = original_rows()[0]
    writer = csv.DictWriter(output, fieldnames=row)
    writer.writeheader(); writer.writerow(row)
    content = output.getvalue()
    preview = timetable.import_timetable(editable, content, False, "")
    with pytest.raises(ValueError, match="変わりました"):
        timetable.import_timetable(editable, content.replace("2.5", "3.5"), True, preview["revision"])


def test_result_paging_is_bounded_and_keeps_zero(editable):
    result = {"canonical_solver_result": {"vehicle_soc_kwh_by_vehicle_slot": {"v.1": {str(i): i for i in range(1000)}}, "daily_cost_ledger": [{"day": i} for i in range(1000)]}}
    scenario_store.set_field(editable, "optimization_result", result)
    page = desktop_store.result_page(editable, "vehicle_soc_kwh_by_vehicle_slot", "v.1", 0, 5)
    assert page["total"] == 1000 and len(page["items"]) == 5
    assert page["items"][0]["value"] == 0
    assert page["owners"] == ["v.1"]
    assert desktop_store.result_page(editable, "daily_cost_ledger", "", 999, 5)["items"] == [{"day": 999}]
    app = FastAPI(); app.include_router(desktop.router)
    client = TestClient(app)
    assert client.get(f"/desktop/scenarios/{editable}/result-data/secret").status_code == 422
    assert client.get(f"/desktop/scenarios/{editable}/result-data/daily_cost_ledger?limit=251").status_code == 422


def test_timeline_rejects_paths_outside_output(editable, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_store, "outputs_root", lambda: tmp_path / "output")
    scenario_store.set_field(editable, "optimization_result", {"audit": {"output_dir": str(tmp_path)}})
    with pytest.raises(ValueError, match="フォルダー外"):
        desktop_store.timeline_page(editable, "", 0, 250)
    run = tmp_path / "output" / "run"; run.mkdir(parents=True)
    (run / "vehicle_timelines.json").write_text(json.dumps({"vehicle_gantt_rows": [{"vehicle_id": "v", "start_time": "25:00", "end_time": "26:00"}]}))
    scenario_store.set_field(editable, "optimization_result", {"audit": {"output_dir": str(run)}})
    assert desktop_store.timeline_page(editable, "v", 0, 1)["total"] == 1


def test_weather_local_source_is_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(weather, "project_root", lambda: tmp_path)
    monkeypatch.setattr(weather, "outputs_root", lambda: tmp_path / "output")
    outside = tmp_path / "private.json"; outside.write_text("{}")
    with pytest.raises(ValueError):
        weather.local_source(str(outside))
    data = tmp_path / "data"; data.mkdir()
    source = data / "weather.json"; source.write_text("{}")
    assert weather.local_source("data/weather.json") == source


def test_frontend_rolling_passes_saved_bess_terminal_policy(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from bff.services.optimization_run.rolling_chain import execute_frontend_rolling_chain
    from scripts import run_hourly_charging_reoptimization as hourly
    class Captured(Exception):
        pass
    def capture(request):
        assert request.bess_terminal_policy == "minimum_only"
        assert request.lookahead_hours == 24
        raise Captured
    monkeypatch.setattr(hourly, "run_rolling_chain", capture)
    problem = SimpleNamespace(metadata={"service_date": "2025-02-03", "rolling_bess_terminal_policy": "minimum_only", "rolling_lookahead_hours": 24})
    with pytest.raises(Captured):
        execute_frontend_rolling_chain(run_dir=tmp_path, problem=problem, scenario_id="s", prepared_input_id="p", service_id="WEEKDAY", depot_id="d", execution_minutes=60, time_limit_sec=1, mip_gap=.1, random_seed=42, gurobi_threads=1)


@pytest.mark.parametrize("policy,expected", [("minimum_only", "minimum_only"), (None, "return_to_initial")])
def test_dated_prepare_preserves_explicit_bess_policy(tmp_path, monkeypatch, policy, expected):
    from bff.services import date_series_inputs as dated
    from src.optimization.common.date_series import DATE_SERIES_INPUT_MODE
    template = {"selected_routes": [{"id": "r"}], "timetable_rows": [{"trip_id": "t", "route_id": "r", "operator_id": "tokyu", "service_id": "WEEKDAY", "departure": "08:00", "arrival": "09:00", "distance_km": 5, "distance_source": "verified_test_distance"}], "stop_sequences": [], "stops": []}
    monkeypatch.setattr(dated, "_verified_timetable", lambda _: (template, {"source_version": "test", "distance_semantics": "test"}))
    monkeypatch.setattr(dated, "_verified_holiday_manifest", lambda *args: {"holiday_dates": [], "sha256": "h"})
    monkeypatch.setattr(dated, "_digest", lambda _: "test")
    monkeypatch.setattr(dated, "_date_pv_rows", lambda *args: ([{"date": "2025-02-03", "slot_minutes": 30, "capacity_factor_by_slot": [0.] * 48}], [{"sha256": "pv"}]))
    asset = {"depot_id": "tsurumaki", "bess_enabled": True, "bess_energy_kwh": 100, "bess_initial_soc_kwh": 50, "bess_soc_min_kwh": 20, "bess_soc_max_kwh": 80, "bess_terminal_soc_min_kwh": 20}
    if policy: asset["bess_terminal_soc_policy"] = policy
    original = {"meta": {"id": "new"}, "simulation_config": {"multi_day_input_mode": DATE_SERIES_INPUT_MODE, "service_date": "2025-02-03", "planning_days": 1, "depot_energy_assets": [asset], "bess_balance_period": "evaluation_period"}, "dispatch_scope": {"depotSelection": {"depotIds": ["tsurumaki"]}, "routeSelection": {"includeRouteIds": ["r"]}}}
    materialized = dated.prepare_date_series_scenario(original, repo_root=tmp_path)
    assert materialized["simulation_config"]["depot_energy_assets"][0]["bess_terminal_soc_policy"] == expected
    assert original["simulation_config"]["depot_energy_assets"][0].get("bess_terminal_soc_policy") == policy


def test_invalid_bess_asset_is_rejected_without_partial_writes(editable):
    before = config.configuration(editable)
    with pytest.raises(HTTPException):
        config.save_configuration(editable, {"depotEnergyAssets": [{"depot_id": "d", "bess_enabled": True, "bess_energy_kwh": 100, "bess_initial_soc_kwh": 99, "bess_soc_min_kwh": 20, "bess_soc_max_kwh": 80}], "timeLimitSeconds": 37}, before["revision"])
    assert config.configuration(editable) == before


def test_simulation_projection_is_separate_from_optimization(editable):
    scenario_store.set_field(editable, "optimization_result", {"objective_value": 100})
    scenario_store.set_field(editable, "simulation_result", {"total_operating_cost": 42, "total_energy_cost": 0, "feasibility_report": {"valid": False}, "ignored": list(range(10000))})
    result = desktop_store.simulation_summary(editable)
    assert result["available"] and result["source"] == "simulation_result"
    assert result["values"] == {"total_operating_cost": 42, "total_energy_cost": 0, "feasibility_report": {"valid": False}}
    assert desktop_store.result_summary(editable)["values"]["objective_value"] == 100


def test_master_crud_and_templates_use_existing_endpoints(editable):
    from bff.routers import master_data, timetable as timetable_router
    app = FastAPI(); app.include_router(master_data.router); app.include_router(timetable_router.router)
    client = TestClient(app)
    base = f"/scenarios/{editable}"
    before = config.configuration(editable)["revision"]
    response = client.post(base + "/vehicle-templates", json={"name": "BEV standard", "type": "BEV", "batteryKwh": 300, "minSoc": .2, "maxSoc": .8})
    assert response.status_code == 201, response.text
    template = response.json()
    response = client.post(base + "/vehicles/bulk", json={"type": template["type"], "batteryKwh": template["batteryKwh"], "minSoc": .2, "maxSoc": .8, "initialSoc": .5, "quantity": 2, "depotId": "d", "energyConsumption": 1.2})
    assert response.status_code == 201, response.text
    vehicle = response.json()["items"][0]
    assert len(response.json()["items"]) == 2
    assert config.configuration(editable)["revision"] != before
    update = {key: value for key, value in vehicle.items() if key in master_data.UpdateVehicleBody.model_fields}
    response = client.put(base + "/vehicles/" + vehicle["id"], json={**update, "initialSoc": .6})
    assert response.status_code == 200, response.text
    assert response.json()["initialSoc"] == .6 and response.json()["batteryKwh"] == 300
    duplicated = client.post(base + "/vehicles/" + vehicle["id"] + "/duplicate-bulk", json={"quantity": 2, "targetDepotId": "d"})
    assert duplicated.status_code == 201, duplicated.text
    assert len(duplicated.json()["items"]) == 2
    assert client.delete(base + "/vehicles/" + vehicle["id"]).status_code == 204
    calendar = client.get(base + "/calendar").json()["items"]
    assert client.put(base + "/calendar", json={"entries": calendar}).status_code == 200


def test_weather_source_preserves_content_with_generated_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(weather, "outputs_root", lambda: tmp_path)
    original = '{"station": "日本語", "value": 0}\n'
    result = weather.import_source("../../weather.json", original)
    path = Path(result["path"])
    assert path.is_relative_to(tmp_path) and path.read_text(encoding="utf-8") == original
    assert path.name != "weather.json"
    with pytest.raises(ValueError):
        weather.import_source("script.exe", "x")


def test_nonfinite_result_points_remain_visible_as_text(editable):
    scenario_store.set_field(editable, "optimization_result", {"canonical_solver_result": {"vehicle_soc_kwh_by_vehicle_slot": {"v": {"0": float("inf"), "1": 0}}}})
    result = desktop_store.result_page(editable, "vehicle_soc_kwh_by_vehicle_slot", "v", 0, 250)
    assert result["total"] == 2
    assert result["items"] == [{"slot_index": 0, "owner": "v", "value": "Infinity"}, {"slot_index": 1, "owner": "v", "value": 0}]


def test_result_download_is_confined_to_saved_output_and_attachment(editable, tmp_path, monkeypatch):
    root = tmp_path / "output"; run = root / "run"; run.mkdir(parents=True)
    monkeypatch.setattr(desktop_store, "outputs_root", lambda: root)
    (run / "report.csv").write_bytes(b"key,value\nx,0\n")
    (run / "unsafe.html").write_text("<script>alert(1)</script>")
    (root / "other.csv").write_text("private")
    scenario_store.set_field(editable, "optimization_result", {"audit": {"output_dir": str(run)}})
    app = FastAPI(); app.include_router(desktop.router); client = TestClient(app)
    base = f"/desktop/scenarios/{editable}/artifacts"
    listed = client.get(base).json()
    assert [item["name"] for item in listed["items"]] == ["report.csv"]
    downloaded = client.get(base + "/file", params={"name": "report.csv"})
    assert downloaded.status_code == 200 and downloaded.content == b"key,value\nx,0\n"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert client.get(base + "/file", params={"name": "../other.csv"}).status_code == 422
    assert client.get(base + "/file", params={"name": "unsafe.html"}).status_code == 422


@pytest.mark.parametrize("departure,arrival", [("bad", "09:00"), ("25:60", "27:00"), ("23:00", "01:00")])
def test_timetable_preview_rejects_invalid_clock_without_rewriting(departure, arrival):
    row = original_rows()[0]; row.update(departure=departure, arrival=arrival)
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=row)
    writer.writeheader(); writer.writerow(row)
    with pytest.raises(ValueError):
        timetable.parse_timetable_csv(output.getvalue())
