"""Seven-day distribution preserves actual/forecast separation and horizon."""
import base64
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from bff.services.cluster.contracts import canonical, digest
from bff.services.cluster.weekly_inputs import stage_execution_inputs, install_execution_inputs, horizon_summary
from bff.services.cluster.scheduler import collect_artifacts, validate_portable_paths
from bff.services.cluster.artifacts import archive_to_disk
from bff.services.optimization_run.rolling_chain import _prepare_actual_pv_execution_file
from src.optimization.common.date_series import consecutive_service_dates
from src.optimization.common.problem import OptimizationConfig, EnergyPriceSlot
from src.optimization.milp.solver_adapter import _stage2_slot_indices, ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT
from test_multiday_rolling_contract import _two_day_problem


@pytest.fixture
def weekly(tmp_path):
    dates = consecutive_service_dates("2025-05-12", 7)
    actual = {"schema_version": "historical_pv_capacity_factor_execution_v1", "depot_id": "tsurumaki",
              "service_dates": dates, "timestep_minutes": 15, "source_sha256": ["source"],
              "profiles": [{"date": day, "slot_minutes": 15, "capacity_factor_by_slot": [0.5] * 96} for day in dates]}
    content = canonical(actual)
    name = "data/derived/pv_execution_inputs/tsurumaki/actual.json"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    config = {"service_date": dates[0], "service_dates": dates, "planning_days": 7,
              "date_series_contract": {"pv_information_mode": "training_only_forecast_proxy",
                                       "pv_execution_input": {"path": name, "sha256": digest(content)}},
              "pv_capacity_factor_by_date": [{"date": day, "slot_minutes": 15, "capacity_factor_by_slot": [0.1] * 96} for day in dates]}
    return config, name, content


def test_seven_day_actuals_survive_transfer_without_changing_forecasts(tmp_path, monkeypatch, weekly):
    config, name, original = weekly
    before = canonical(config)
    prepared = canonical({"simulation_config": config, "trips": [{"operator_id": "tokyu", "departure": "167:00"}]})
    staged = stage_execution_inputs([config, config], tmp_path)
    validate_portable_paths(config, set(staged))
    bundle = {"scenario": {"simulation_config": config}, "prepared_base64": base64.b64encode(prepared).decode(),
              "execution_inputs": staged}
    root = tmp_path / "worker"
    install_execution_inputs(bundle, root)
    assert (root / name).read_bytes() == original
    assert canonical(config) == before
    assert base64.b64decode(bundle["prepared_base64"]) == prepared
    problem = SimpleNamespace(metadata={"date_series_contract": config["date_series_contract"], "service_dates": config["service_dates"]},
                              scenario=SimpleNamespace(timestep_min=15),
                              depot_energy_assets={"tsurumaki": SimpleNamespace(pv_capacity_kw=100, pv_supply_scale=1, pv_enabled=True)})
    local = _prepare_actual_pv_execution_file(problem, tmp_path / "local-output", repo_root=tmp_path)
    monkeypatch.setenv("MC_EXECUTION_INPUTS_ROOT", str(root))
    remote = _prepare_actual_pv_execution_file(problem, tmp_path / "worker-output")
    assert json.loads(open(local, encoding="utf-8").read()) == json.loads(open(remote, encoding="utf-8").read())
    assert len(json.loads(open(remote, encoding="utf-8").read())["depot_profiles"]["tsurumaki"]) == 672
    (root / name).unlink()
    with pytest.raises(ValueError, match="must be a file"):
        _prepare_actual_pv_execution_file(problem, tmp_path / "missing")


def test_weekly_input_tampering_and_missing_payload_fail(tmp_path, weekly):
    config, name, _ = weekly
    bundle = {"scenario": {"simulation_config": config}, "prepared_base64": "e30="}
    with pytest.raises(ValueError, match="inventory"):
        install_execution_inputs(bundle, tmp_path / "worker")
    (tmp_path / name).write_text("tampered")
    with pytest.raises(ValueError, match="changed after Prepare"):
        stage_execution_inputs([config], tmp_path)


def test_weekly_summary_and_final_rolling_window(weekly):
    config, _, _ = weekly
    summary = horizon_summary({"simulation_config": config})
    assert summary["horizon_hours"] == summary["expected_rolling_windows"] == 168
    assert len(summary["service_dates"]) == 7
    assert summary["research_status"] == "MULTIDAY_RESEARCH_BLOCKED"
    assert horizon_summary({"simulation_config": config}, kwargs={"run_hourly_rolling": False})["expected_rolling_windows"] == 0
    problem = _two_day_problem()
    problem = replace(problem, scenario=replace(problem.scenario, planning_days=7, horizon_end="168:00"),
                      depot_energy_assets={"DEPOT": replace(problem.depot_energy_assets["DEPOT"], pv_generation_kwh_by_slot=(0.0,)*168)},
                      price_slots=tuple(EnergyPriceSlot(i, grid_buy_yen_per_kwh=10) for i in range(168)))
    for hour in (23, 24, 143, 144, 167):
        controls = OptimizationConfig(rolling_current_min=hour*60, rolling_lookahead_hours=24,
                                      rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT)
        assert _stage2_slot_indices(problem, controls, range(168)) == tuple(range(hour, min(hour+24, 168)))


def test_formal_weekly_rejected_before_prepare_or_enqueue(monkeypatch):
    from bff.routers import optimization
    monkeypatch.setattr(optimization, "_require_scenario", lambda _: None)
    monkeypatch.setattr(optimization.store, "get_scenario_document_shallow", lambda _: {"simulation_config": {"planning_days": 7}})
    monkeypatch.setattr(optimization, "_require_research_git_preflight_before_job_creation", lambda **_: None)
    monkeypatch.setattr(optimization, "get_or_build_run_preparation", lambda **_: pytest.fail("must reject before prepare"))
    with pytest.raises(HTTPException, match="MULTIDAY_RESEARCH_BLOCKED"):
        optimization.enqueue_optimization("weekly", optimization.RunOptimizationBody(research_run=True), {})


def test_disk_transfer_bypasses_legacy_memory_limit_and_checks_hashes(tmp_path, monkeypatch):
    from bff.services.cluster import scheduler
    source = tmp_path / "worker" / "job"
    source.mkdir(parents=True)
    manifest = {"id": "job"}
    state = {"id": "job", "state": "COMPLETED", "manifest_sha256": digest(canonical(manifest))}
    (source / "manifest.json").write_bytes(canonical(manifest))
    (source / "state.json").write_bytes(canonical(state))
    (source / "large.bin").write_bytes(b"x" * 10000)
    response = archive_to_disk(source, state)
    monkeypatch.setattr(scheduler, "MAX_ARTIFACT_BYTES", 1)
    target = tmp_path / "controller" / "artifacts"
    collect_artifacts(response, manifest, target, source.with_suffix(".zip"))
    assert (target / "large.bin").stat().st_size == 10000
    with pytest.raises(ValueError, match="transfer hash"):
        collect_artifacts({**response, "archive_sha256": "bad"}, manifest, target, source.with_suffix(".zip"))
