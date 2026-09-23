"""Configuration and boundary regressions only: these tests must not solve."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.benchmarks import prepare_shibu21_24_seasonal_inputs as preparation
from scripts.benchmarks.run_exact_seasonal_campaign import run_campaign
from scripts.benchmarks import run_shibu21_24_seasonal_diagnostic as runner
from scripts.benchmarks.run_shibu21_seasonal_diagnostic import solve_week
from scripts.benchmarks.seasonal_design_contract import (
    require_execution_enabled,
    seasonal_bess_controls,
)
from src.optimization.common.problem import OptimizationConfig
from src.optimization.engine import OptimizationEngine
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from test_rolling_bess_boundary_policy import _boundary_problem, _CaptureEngine


ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "config/shibu21_23_monthly_cyclic_draft_20260919.json"


@pytest.fixture(autouse=True)
def no_solver(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("This configuration regression must not start a solver")
    monkeypatch.setattr(OptimizationEngine, "solve", forbidden)


def _parent_asset():
    return {
        "depot_id": "tsurumaki", "bess_enabled": True,
        "bess_energy_kwh": 6000.0, "bess_power_kw": 900.0,
        "bess_initial_soc_kwh": 3000.0,
        "bess_charge_efficiency": 0.95, "bess_discharge_efficiency": 0.95,
        "allow_grid_to_bess": False,
    }


def test_cyclic_draft_changes_only_declared_conditions_and_is_held():
    import hashlib

    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    origin = draft["derived_from_design"]
    source = ROOT / origin["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == origin["sha256"]
    old = json.loads(source.read_text(encoding="utf-8"))
    expected_changes = {
        "bess_terminal_soc_policy", "rolling_bess_terminal_policy",
        "rolling_window_terminal_policy_description", "time_budget_semantics",
        "input_manifests_directory", "limitations",
    }
    assert {key for key in old if old[key] != draft[key]} == expected_changes
    assert len(draft["evaluation_weeks"]) == 12
    assert draft["execution_enabled"] is False
    controls = seasonal_bess_controls(draft)
    parent = _parent_asset()
    unchanged = deepcopy(parent)
    asset = preparation.apply_seasonal_bess_policy(parent, design=draft)
    assert parent == unchanged
    assert asset["bess_terminal_soc_target_kwh"] == parent["bess_initial_soc_kwh"]
    assert asset["bess_terminal_soc_target_ratio"] == 0.5
    assert asset["bess_terminal_soc_target_percent"] == 50.0
    assert asset["bess_soc_min_kwh"] == 1200.0
    assert asset["bess_soc_max_kwh"] == 4800.0
    for key, value in parent.items():
        assert asset[key] == value
    problem = SimpleNamespace(
        vehicles=(), depot_energy_assets={"tsurumaki": SimpleNamespace(**asset)},
        metadata={**controls, "bev_terminal_soc_policy": "return_to_initial",
                  "final_soc_target_tolerance_percent": 0,
                  "daily_return_depot_id": "tsurumaki",
                  "rolling_window_terminal_policy": "day_ahead_boundary_state"},
    )
    audit = runner.verify_evaluation_contract(problem, draft)
    assert audit["bess_controls"]["tsurumaki"]["terminal_soc_target_kwh"] == 3000.0
    problem.depot_energy_assets["tsurumaki"].bess_terminal_soc_policy = "minimum_only"
    with pytest.raises(ValueError, match="terminal policy differs"):
        runner.verify_evaluation_contract(problem, draft)


@pytest.mark.parametrize("change", [
    {"bess_terminal_soc_policy": "return_to_initial"},
    {"bess_terminal_soc_policy": "fixed_target"},
    {"bess_balance_period": "daily"},
    {"bess_terminal_soc_floor_percent": 25},
    {"bess_terminal_soc_floor_percent": float("nan")},
    {"rolling_bess_terminal_policy": "invented"},
])
def test_unsupported_or_target_erasing_controls_fail_before_materialization(change):
    document = {"untouched": True}
    with pytest.raises(ValueError):
        preparation.configure_doc(document, "2025-01-06", {}, design=change)
    assert document == {"untouched": True}


@pytest.mark.parametrize("entrypoint", [run_campaign, runner.run_diagnostic, solve_week])
def test_held_design_blocks_all_execution_entrypoints_without_outputs(tmp_path, monkeypatch, entrypoint):
    def forbidden(*args, **kwargs):
        pytest.fail("Held design must fail before preflight, scenario IO or solve")
    monkeypatch.setattr(runner, "run_preflight", forbidden)
    monkeypatch.setattr(preparation, "prepare_week", forbidden)
    output = tmp_path / "never-created"
    design = {"execution_enabled": False}
    with pytest.raises(RuntimeError, match="EXECUTION_DISABLED"):
        if entrypoint is solve_week:
            entrypoint("2025-01-06", output, design)
        else:
            entrypoint(design, output)
    assert not output.exists()


@pytest.mark.parametrize("value", ["false", "true", None, 0, 1])
def test_execution_control_rejects_non_boolean(value):
    with pytest.raises(ValueError, match="JSON boolean"):
        require_execution_enabled({"execution_enabled": value})


def test_legacy_and_explicitly_enabled_execution_controls_are_compatible():
    require_execution_enabled({})
    require_execution_enabled({"execution_enabled": True})


@pytest.mark.parametrize("capacity", [0.0, -1.0, float("inf"), float("nan")])
def test_seasonal_asset_requires_finite_positive_capacity(capacity):
    asset = {**_parent_asset(), "bess_energy_kwh": capacity}
    with pytest.raises(ValueError, match="positive bess_energy_kwh"):
        preparation.apply_seasonal_bess_policy(asset)


@pytest.mark.parametrize("current_min,expected_target", [(0, 1800.0), (1440, 3000.0)])
def test_cyclic_rolling_keeps_forecast_boundary_and_original_period_target(current_min, expected_target):
    problem, plan, depot = _boundary_problem(bess_reference=1800.0)
    asset = replace(problem.depot_energy_assets[depot], bess_balance_period="evaluation_period")
    problem = replace(problem, depot_energy_assets={depot: asset})
    rolling = RollingReoptimizer()
    capture = _CaptureEngine()
    rolling._engine = capture
    from src.optimization.rolling.vehicle_execution import vehicle_positions_at
    rolling.reoptimize_charging_hour(
        problem, plan, OptimizationConfig(), current_min, lookahead_hours=24,
        actual_bess_soc_kwh={depot: 2100.0}, bess_terminal_policy="scenario",
        actual_soc={"bev-1": 80.0},
        actual_vehicle_positions=vehicle_positions_at(problem, plan, current_min),
        actual_vehicle_fuel_l={},
        observed_on_peak_kw_by_depot={depot: 0.0},
        observed_off_peak_kw_by_depot={depot: 0.0},
    )
    actual = capture.problem.depot_energy_assets[depot]
    assert actual.bess_initial_soc_kwh == 2100.0
    assert actual.bess_terminal_soc_target_kwh == expected_target
    assert actual.bess_terminal_soc_policy == "fixed_target"
    assert actual.bess_balance_period == "evaluation_period"


def test_zero_initial_target_survives_rolling_freeze():
    problem, plan, depot = _boundary_problem(physical_floor=0.0)
    asset = replace(problem.depot_energy_assets[depot], bess_initial_soc_kwh=0.0,
                    bess_terminal_soc_min_kwh=0.0, bess_terminal_soc_target_kwh=0.0)
    problem = replace(problem, depot_energy_assets={depot: asset})
    frozen = RollingReoptimizer._freeze_bess_terminal_soc_targets(problem)
    from src.optimization.common.bess_terminal_policy import resolve_bess_terminal_soc_target_kwh
    actual = frozen.depot_energy_assets[depot]
    assert resolve_bess_terminal_soc_target_kwh(
        policy=actual.bess_terminal_soc_policy, initial_soc_kwh=actual.bess_initial_soc_kwh,
        configured_target_kwh=actual.bess_terminal_soc_target_kwh,
        terminal_soc_floor_kwh=actual.bess_terminal_soc_min_kwh,
        maximum_soc_kwh=actual.bess_soc_max_kwh,
    ) == 0.0


@pytest.mark.parametrize("policy,rolling", [("minimum_only", "minimum_only"), ("return_to_initial", "scenario")])
@pytest.mark.parametrize("planning_days", [1, 7])
def test_configure_doc_preserves_controls_in_config_overlay_and_date_contract(monkeypatch, policy, rolling, planning_days):
    """Stub source IO; exercise the real scenario mutation and policy propagation."""
    design = {"bess_terminal_soc_policy": policy, "rolling_bess_terminal_policy": rolling}
    asset = _parent_asset()
    doc = {"simulation_config": {"depot_energy_assets": [asset]},
           "dispatch_scope": {"routeSelection": {}}, "meta": {}}
    source_files = {
        "selected_routes.json": [{"id": "route-1"}],
        "timetable_rows.json": [{"route_id": "route-1", "trip_id": "template-1",
                                  "service_id": "WEEKDAY", "distance_km": 10.0}],
        "stop_sequences.json": [], "stops.json": [],
    }
    row = {"trip_id": "dated-1", "template_trip_id": "template-1", "route_id": "route-1",
           "service_id": "WEEKDAY", "service_date": "2025-01-06", "day_index": 0}
    monkeypatch.setattr(preparation, "read_json", lambda path: deepcopy(source_files[path.name]))
    monkeypatch.setattr(preparation, "sha256", lambda path: "source-hash")
    monkeypatch.setattr(preparation, "_verified_holiday_manifest", lambda *a: {"holiday_dates": [], "sha256": "calendar-hash"})
    monkeypatch.setattr(preparation, "materialize_dated_timetable", lambda *a, **kw: ([row], {}))
    monkeypatch.setattr(preparation, "_date_pv_rows", lambda *a: ([], []))
    monkeypatch.setattr(preparation, "_persist_actual_profiles", lambda *a: {"actuals": "stub"})
    monkeypatch.setattr(preparation, "_date_forecast_rows", lambda *a, **kw: ([], {}))
    monkeypatch.setattr(preparation, "dated_capacity_factors", lambda *a: None)
    monkeypatch.setattr(preparation, "validate_dated_timetable", lambda *a: None)
    configured = preparation.configure_doc(doc, "2025-01-06", {"distance_semantics": "fixture"},
                                           design=design, planning_days=planning_days)
    cfg = configured["simulation_config"]
    assert cfg["planning_days"] == planning_days
    assert cfg["planning_horizon_hours"] == 24 * planning_days
    assert len(cfg["service_dates"]) == planning_days
    controls = seasonal_bess_controls(design)
    for key, value in controls.items():
        assert cfg[key] == value
        assert cfg["date_series_contract"][key] == value
    actual = cfg["depot_energy_assets"][0]
    assert actual == configured["scenario_overlay"]["depot_energy_assets"]["tsurumaki"]
    assert actual["bess_terminal_soc_policy"] == policy
    assert actual["bess_terminal_soc_target_kwh"] == (3000.0 if policy == "return_to_initial" else 0.0)
