from __future__ import annotations

import json
from pathlib import Path

import pytest

from bff.services import experiment_reports
from experiment_logger import ExperimentLogger


def test_experiment_logger_preserves_explicit_zero_accounting_components(
    tmp_path: Path,
) -> None:
    """Zero canonical components are values, not missing-data fallbacks."""

    report = ExperimentLogger(results_dir=tmp_path).log(
        scenario={
            "depot": "tsurumaki",
            "routes": ["R1"],
            "fleet": [],
            "objective": "total_cost",
            "solver": {"name": "gurobi", "time_limit_sec": 60},
            "costs": {"tou_rates": {}},
            "grid": {"max_kw": 1000.0},
        },
        result={
            "status": "FEASIBLE",
            "objective_value": 0.0,
            "total_cost_jpy": 0.0,
            "electricity_cost_jpy": 0.0,
            "diesel_cost_jpy": 0.0,
            "demand_charge_jpy": 0.0,
            "vehicle_fixed_cost_jpy": 0.0,
            "vehicle_usage_cost_jpy": 640_000.0,
            "co2_cost_jpy": 0.0,
            "cost_breakdown": {
                "total": 1.0,
                "electricity": 2.0,
                "diesel": 3.0,
                "demand": 4.0,
                "vehicle_fixed": 5.0,
            },
        },
        git_commit="test-sha",
    )

    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    results = payload["results"]

    assert results["objective_value"] == 0.0
    assert results["total_cost_jpy"] == 0.0
    assert results["electricity_cost_jpy"] == 0.0
    assert results["diesel_cost_jpy"] == 0.0
    assert results["demand_charge_jpy"] == 0.0
    assert results["vehicle_fixed_cost_jpy"] == 0.0
    assert results["vehicle_usage_cost_jpy"] == 640_000.0
    assert results["co2_cost_jpy"] == 0.0


def test_optimization_report_uses_finalized_electricity_component() -> None:
    """The final report must not label electricity-plus-fuel as electricity."""

    payload = experiment_reports._optimization_result_payload(
        {
            "solver_status": "FEASIBLE",
            "cost_breakdown": {
                "electricity_cost_final": 66_659.49730088498,
                "fuel_cost": 66_659.49730088498,
                "demand_cost": 0.0,
                "vehicle_usage_cost": 640_000.0,
                "co2_cost": 1_149.1630718191466,
            },
        },
        accounting_summary_override={
            "total_cost_jpy": 707_808.6603727042,
            "energy_cost_jpy": 66_659.49730088498,
            "electricity_cost_jpy": -1.8189894035458565e-12,
            "fuel_cost_jpy": 66_659.49730088498,
            "demand_charge_cost_jpy": 0.0,
            "vehicle_usage_cost_jpy": 640_000.0,
            "co2_cost_jpy": 1_149.1630718191466,
        },
    )

    assert payload["electricity_cost_jpy"] == -1.8189894035458565e-12
    assert payload["diesel_cost_jpy"] == 66_659.49730088498
    assert payload["demand_charge_jpy"] == 0.0
    assert payload["vehicle_usage_cost_jpy"] == 640_000.0


def test_bff_logger_persists_finalized_components_at_report_top_level(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The final report schema must expose canonical reconciliation fields."""

    monkeypatch.setattr(
        experiment_reports,
        "_results_dir",
        lambda _scenario_id, _report_type: tmp_path,
    )
    canonical_components = {
        "electricity_cost_jpy": -1.8189894035458565e-12,
        "fuel_cost_jpy": 66_659.49730088498,
        "demand_charge_cost_jpy": 0.0,
        "vehicle_usage_cost_jpy": 640_000.0,
        "co2_cost_jpy": 1_149.1630718191466,
    }
    report = experiment_reports.log_optimization_experiment(
        scenario_id="scenario-1",
        scenario_doc={
            "dispatch_scope": {"depotId": "tsurumaki"},
            "vehicles": [],
            "simulation_config": {},
            "scenario_overlay": {"solver_config": {}},
        },
        optimization_result={
            "mode": "mode_milp_only",
            "objective_mode": "total_cost",
            "solver_status": "FEASIBLE",
            "summary": {},
            "solver_metadata": {},
            "solver_settings": {},
            "cost_breakdown": {
                "total_cost": 707_808.6603727042,
                "fuel_cost": 66_659.49730088498,
                "demand_cost": 0.0,
                "vehicle_usage_cost": 640_000.0,
                "co2_cost": 1_149.1630718191466,
            },
        },
        accounting_summary_override={
            "total_cost_jpy": 707_808.6603727042,
            "accounting_total_cost_jpy": 707_808.6603727042,
            "energy_cost_jpy": 66_659.49730088498,
            "electricity_cost_jpy": canonical_components[
                "electricity_cost_jpy"
            ],
            "fuel_cost_jpy": canonical_components["fuel_cost_jpy"],
            "demand_charge_cost_jpy": canonical_components[
                "demand_charge_cost_jpy"
            ],
            "vehicle_usage_cost_jpy": canonical_components[
                "vehicle_usage_cost_jpy"
            ],
            "co2_cost_jpy": canonical_components["co2_cost_jpy"],
            "canonical_cost_components_jpy": canonical_components,
            "canonical_cost_component_status": {
                key: {"enabled": True, "status": "ENABLED"}
                for key in canonical_components
            },
        },
        git_commit_override="test-sha",
    )

    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    results = persisted["results"]

    assert results["electricity_cost_jpy"] == pytest.approx(
        canonical_components["electricity_cost_jpy"]
    )
    assert results["demand_charge_jpy"] == 0.0
    assert results["vehicle_usage_cost_jpy"] == 640_000.0
    assert results["canonical_cost_components_jpy"] == canonical_components
    assert results["canonical_cost_component_status"][
        "demand_charge_cost_jpy"
    ]["status"] == "ENABLED"
