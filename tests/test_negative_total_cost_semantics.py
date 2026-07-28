from __future__ import annotations

import json
from types import SimpleNamespace

from bff.routers.optimization import (
    _canonical_cost_breakdown_json,
    _cost_breakdown,
    _finalized_accounting_summary_for_experiment_report,
)
from bff.services.optimization_run.cost_breakdown import canonical_cost_ledger_json
from bff.services.experiment_reports import _logger_scenario_payload, _optimization_result_payload


def test_cost_breakdown_prefers_accounting_total_cost_over_objective_value() -> None:
    payload = _cost_breakdown(
        {
            "objective_value": -49718.03699606294,
            "obj_breakdown": {
                "total_cost": 61781.96300393706,
                "return_leg_bonus": 111500.0,
            },
        },
        None,
    )

    assert payload["total_cost"] == 61781.96300393706
    assert payload["return_leg_bonus"] == 111500.0


def test_canonical_cost_breakdown_json_keeps_bonus_separate_from_total_cost() -> None:
    engine_result = SimpleNamespace(
        cost_breakdown={
            "total_cost": 61781.96300393706,
            "energy_cost": 61781.96300393706,
            "vehicle_cost": 1234.0,
            "driver_cost": 0.0,
            "return_leg_bonus": 111500.0,
        },
        objective_value=-49718.03699606294,
        solver_metadata={"objective_mode": "total_cost"},
        mode=SimpleNamespace(value="milp"),
    )
    problem = SimpleNamespace(
        scenario=SimpleNamespace(objective_mode="total_cost"),
        depot_energy_assets={},
    )

    payload = _canonical_cost_breakdown_json(
        problem=problem,
        engine_result=engine_result,
        scenario_id="scenario-1",
    )

    assert payload["total_cost"] == 61781.96300393706
    assert payload["components"]["vehicle_fixed_cost"] == 1234.0
    assert payload["components"]["return_leg_bonus"] == 111500.0


def test_canonical_cost_ledger_preserves_demand_and_grid_co2_cost() -> None:
    engine_result = SimpleNamespace(
        cost_breakdown={
            "electricity_cost": 7534.642538,
            "grid_purchase_cost": 7534.642538,
            "fuel_cost": 66659.497301,
            "demand_cost": 866.050866,
            "vehicle_usage_cost": 640000.0,
            "co2_cost": 1354.850153,
            "total_co2_kg": 1354.850153,
            "grid_electricity_co2_kg": 205.687081,
            "ice_co2_kg": 1149.163072,
            "total_cost": 716415.040858,
        },
        objective_value=716415.040858,
        solver_metadata={"solver_objective_matches_accounting_total": True},
    )
    problem = SimpleNamespace(
        scenario=SimpleNamespace(co2_price_per_kg=1.0),
    )

    ledger = canonical_cost_ledger_json(
        problem=problem,
        engine_result=engine_result,
        scenario_id="low-pv",
    )

    assert ledger["components"]["demand_charge_cost_jpy"] == 866.050866
    assert ledger["components"]["co2_cost_jpy"] == 1354.850153
    assert ledger["co2"]["grid_co2_kg"] == 205.687081
    assert ledger["accounting_residual_jpy"] == 0.0
    assert ledger["accounting_residual_satisfied"] is True


def test_experiment_report_payload_exposes_return_leg_bonus_and_demand_charge() -> None:
    payload = _optimization_result_payload(
        {
            "solver_status": "BASELINE_FALLBACK",
            "objective_value": -49718.03699606294,
            "summary": {},
            "simulation_summary": {},
            "cost_breakdown": {
                "total_cost": 61781.96300393706,
                "return_leg_bonus": 111500.0,
                "demand_charge": 4321.0,
            },
        }
    )

    assert payload["objective_value"] == -49718.03699606294
    assert payload["total_cost_jpy"] == 61781.96300393706
    assert payload["return_leg_bonus_jpy"] == 111500.0
    assert payload["demand_charge_jpy"] == 4321.0


def test_experiment_report_uses_accounting_total_and_percent_gap() -> None:
    payload = _optimization_result_payload(
        {
            "solver_status": "feasible",
            "objective_value": 721_657.93,
            "mip_gap": 0.410807,
            "solver_settings": {"mip_gap_achieved_percent": 41.0807},
            "summary": {"trip_count_served": 264},
            "cost_breakdown": {"total_cost": 721_657.93},
            "graph_artifacts": {
                "accounting_summary": {
                    "accounting_total_cost_jpy": 716_926.89,
                    "grid_purchase_cost_jpy": 21_476.40,
                    "bess_total_flow_cost_jpy": 123.45,
                    "energy_cost_jpy": 21_599.85,
                    "fuel_cost_jpy": 48_406.31,
                    "demand_charge_cost_jpy": 5_619.53,
                    "vehicle_usage_cost_jpy": 640_000.0,
                    "total_co2_kg": 1_424.66,
                    "bev_trip_count": 127,
                    "ice_trip_count": 137,
                    "served_trip_count": 264,
                    "unserved_trip_count": 0,
                }
            },
        }
    )

    assert payload["status"] == "FEASIBLE"
    assert payload["objective_value"] == 721_657.93
    assert payload["total_cost_jpy"] == 716_926.89
    assert payload["electricity_cost_jpy"] == 21_599.85
    assert payload["demand_charge_jpy"] == 5_619.53
    assert payload["mip_gap_pct"] == 41.0807
    assert payload["bev_trips"] == 127
    assert payload["ice_trips"] == 137
    assert payload["trip_count_unserved"] == 0


def test_experiment_report_payload_prefers_stage1_native_gap_and_keeps_terminal_audit() -> None:
    payload = _optimization_result_payload(
        {
            "solver_status": "feasible",
            "summary": {},
            "simulation_summary": {},
            "solver_settings": {
                "mip_gap_achieved_percent": 9.204876,
                "stage1_gurobi_raw_mip_gap_percent": 100.0,
            },
            "solver_metadata": {
                "bev_terminal_soc_policy": "return_to_initial",
                "bev_terminal_soc_balance_satisfied": True,
                "bev_terminal_soc_total_drawdown_kwh": 0.0,
            },
            "cost_breakdown": {"total_cost": 1.0},
        }
    )

    assert payload["mip_gap_pct"] == 100.0
    assert payload["bev_terminal_soc_policy"] == "return_to_initial"
    assert payload["bev_terminal_soc_balance_satisfied"] is True
    assert payload["bev_terminal_soc_total_drawdown_kwh"] == 0.0


def test_experiment_report_uses_finalized_accounting_components() -> None:
    payload = _optimization_result_payload(
        {
            "solver_status": "feasible",
            "objective_value": 721_185.99,
            "summary": {},
            "simulation_summary": {},
            "cost_breakdown": {
                "total_cost": 721_185.99,
                "electricity_cost": 9_999.0,
                "fuel_cost": 63_000.0,
                "demand_charge": 0.0,
                "vehicle_usage_cost": 640_000.0,
                "co2_cost": 0.0,
            },
        },
        accounting_summary_override={
            "accounting_total_cost_jpy": 715_823.25,
            "grid_purchase_cost_jpy": 10_015.66,
            "bess_total_flow_cost_jpy": 0.0,
            "fuel_cost_jpy": 63_291.84,
            "demand_charge_cost_jpy": 1_151.23,
            "vehicle_usage_cost_jpy": 640_000.0,
            "co2_cost_jpy": 1_364.52,
            "total_co2_kg": 1_364.52,
        },
    )

    assert payload["total_cost_jpy"] == 715_823.25
    assert payload["electricity_cost_jpy"] == 10_015.66
    assert payload["demand_charge_jpy"] == 1_151.23
    assert payload["vehicle_usage_cost_jpy"] == 640_000.0
    assert payload["vehicle_fixed_cost_jpy"] == 0.0
    assert payload["vehicle_acquisition_cost_jpy"] == 0.0
    assert payload["co2_cost_jpy"] == 1_364.52
    assert payload["cost_breakdown"]["total_cost"] == 715_823.25


def test_finalized_experiment_accounting_reads_canonical_cost_ledger(
    tmp_path,
) -> None:
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    (tmp_path / "summary.json").write_text(
        json.dumps(
            {
                "objective_value_jpy": None,
                "trip_count_served": 264,
                "trip_count_unserved": 0,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "kpi_summary.json").write_text(
        json.dumps({"served_trip_count": 264, "unserved_trip_count": 0}),
        encoding="utf-8",
    )
    (graph_dir / "canonical_cost_ledger.json").write_text(
        json.dumps(
            {
                "components": {
                    "electricity_cost_jpy": 100.0,
                    "fuel_cost_jpy": 20.0,
                    "demand_charge_cost_jpy": 5.0,
                    "vehicle_usage_cost_jpy": 200.0,
                    "co2_cost_jpy": 2.0,
                },
                "details": {
                    "grid_purchase_cost_jpy": 90.0,
                    "bess_total_flow_cost_jpy": 10.0,
                },
                "co2": {"total_co2_kg": 2.0},
                "accounting_total_cost_jpy": 327.0,
                "accounting_residual_jpy": 0.0,
                "accounting_residual_tolerance_jpy": 1.0e-6,
            }
        ),
        encoding="utf-8",
    )

    result = _finalized_accounting_summary_for_experiment_report(tmp_path)

    assert result["accounting_total_cost_jpy"] == 327.0
    assert result["grid_purchase_cost_jpy"] == 90.0
    assert result["bess_total_flow_cost_jpy"] == 10.0
    assert result["fuel_cost_jpy"] == 20.0
    assert result["demand_charge_cost_jpy"] == 5.0
    assert result["vehicle_usage_cost_jpy"] == 200.0
    assert result["co2_cost_jpy"] == 2.0
    assert result["experiment_report_accounting_reconciled"] is True
    assert (
        result["experiment_report_accounting_source"]
        == "graph/canonical_cost_ledger.json"
    )


def test_logger_scenario_payload_uses_vehicle_and_depot_asset_fallbacks() -> None:
    payload = _logger_scenario_payload(
        scenario_doc={
            "dispatch_scope": {"depotSelection": {"primaryDepotId": "dep1"}},
            "simulation_config": {
                "fleet_templates": [],
                "depot_energy_assets": [
                    {"depot_id": "dep1", "derived_pv_capacity_kw": 12.5},
                    {"depot_id": "dep2", "pv_capacity_kw": 7.5},
                ],
            },
            "vehicles": [
                {"id": "bev-1", "type": "BEV"},
                {"id": "bev-2", "type": "BEV"},
                {"id": "ice-1", "type": "ICE"},
            ],
            "routes": [{"id": "route-1"}],
        },
        objective="total_cost",
        method="MILP",
        mode="mode_milp_only",
    )

    fleet_counts = {item["vehicle_type"]: item["count"] for item in payload["fleet"]}
    assert fleet_counts == {"BEV": 2, "ICE": 1}
    assert payload["pv"]["capacity_kw"] == 20.0


def test_logger_scenario_payload_converts_gap_and_hashes_effective_date() -> None:
    payload = _logger_scenario_payload(
        scenario_doc={
            "dispatch_scope": {"depotId": "dep1"},
            "simulation_config": {
                "service_date": "2025-08-10",
                "vehicle_usage_cost_jpy_per_used_bus": 20_000,
                "depot_energy_assets": [{"depot_id": "dep1", "pv_capacity_kw": 10.0}],
            },
            "scenario_overlay": {"solver_config": {"mip_gap": 0.1}},
        },
        objective="total_cost",
        method="二段階MILP",
        mode="milp",
    )

    assert payload["solver"]["mip_gap_pct"] == 10.0
    assert payload["costs"]["vehicle_fixed_cost"] == 20_000
    assert payload["service_date"] == "2025-08-10"


def test_logger_scenario_payload_preserves_explicit_zero_vehicle_usage_cost() -> None:
    payload = _logger_scenario_payload(
        scenario_doc={
            "simulation_config": {"vehicle_usage_cost_jpy_per_used_bus": 0.0},
            "scenario_overlay": {
                "solver_config": {
                    "objective_weights": {"vehicle_fixed_cost": 99_999.0}
                }
            },
        },
        objective="total_cost",
        method="MILP",
        mode="milp",
    )

    assert payload["costs"]["vehicle_fixed_cost"] == 0.0
