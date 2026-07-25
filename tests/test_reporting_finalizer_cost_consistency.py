from __future__ import annotations

import csv
import json

import pytest

from src.reporting.canonical_reporting import update_cost_breakdown
from tests._reporting_finalizer_utils import RUN_EXPECTATIONS, finalized_run, key_values, load_json, sum_column


@pytest.mark.parametrize("run_id", sorted(RUN_EXPECTATIONS))
def test_reporting_finalizer_cost_consistency(tmp_path, run_id):
    run_dir = finalized_run(tmp_path, run_id)
    expected = RUN_EXPECTATIONS[run_id]
    kpi = load_json(run_dir / "graph" / "kpi_summary.json")
    cost = key_values(run_dir / "cost_breakdown_detail.csv")

    # These fixtures are baseline fallbacks, not validated feasible solutions.
    # Preserve their raw diagnostic ledgers while preventing reader-facing KPI
    # files from presenting those values as research-eligible results.
    assert sum_column(
        run_dir / "graph" / "cost_timeseries.csv", "grid_purchase_cost_jpy"
    ) == pytest.approx(expected["grid_purchase_cost_jpy"])
    assert cost["demand_charge"] == pytest.approx(expected["demand_charge_cost_jpy"])
    assert kpi["grid_purchase_cost_jpy"] is None
    assert kpi["demand_charge_cost_jpy"] is None
    assert kpi["result_status"] == "INVALID"
    assert kpi["research_kpi_eligible"] is False
    solver_cost = load_json(run_dir / "graph" / "cost_breakdown.json")
    assert cost["fuel_cost"] == pytest.approx(
        solver_cost["components"]["fuel_cost_final"]
    )
    assert cost["total_co2_kg"] == pytest.approx(
        sum_column(run_dir / "graph" / "co2_timeseries.csv", "total_co2_kg")
    )


def test_reporting_finalizer_counts_bess_flow_cost_once(tmp_path) -> None:
    path = tmp_path / "cost_breakdown_detail.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["key", "value", "unit"])
        writer.writeheader()
        writer.writerows(
            [
                {"key": "demand_charge", "value": 5.0, "unit": "JPY"},
                {"key": "vehicle_cost", "value": 0.0, "unit": "JPY"},
                {"key": "vehicle_usage_cost", "value": 0.0, "unit": "JPY"},
                {"key": "total_co2_kg", "value": 0.0, "unit": "kg-CO2"},
                {"key": "co2_cost", "value": 0.0, "unit": "JPY"},
                {"key": "pv_self_consumption_cost_jpy", "value": 999.0, "unit": "JPY"},
                {"key": "bess_discharge_cost", "value": 999.0, "unit": "JPY"},
            ]
        )
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    (graph_dir / "canonical_cost_ledger.json").write_text(
        json.dumps(
            {
                "schema_version": "canonical_cost_ledger_v1",
                "components": {
                    "electricity_cost_jpy": 130.0,
                    "fuel_cost_jpy": 20.0,
                    "demand_charge_cost_jpy": 5.0,
                    "contract_overage_cost_jpy": 0.0,
                    "vehicle_fixed_cost_jpy": 0.0,
                    "vehicle_usage_cost_jpy": 0.0,
                    "driver_cost_jpy": 0.0,
                    "unserved_penalty_jpy": 0.0,
                    "switch_cost_jpy": 0.0,
                    "battery_degradation_cost_jpy": 0.0,
                    "deviation_cost_jpy": 0.0,
                    "co2_cost_jpy": 0.0,
                },
                "details": {
                    "grid_purchase_cost_jpy": 100.0,
                    "bess_total_flow_cost_jpy": 30.0,
                },
                "usage": {},
                "co2": {"carbon_price_jpy_per_kg": 0.0},
                "accounting_total_cost_jpy": 155.0,
                "accounting_residual_jpy": 0.0,
            }
        ),
        encoding="utf-8",
    )

    cost = update_cost_breakdown(
        tmp_path,
        {
            "grid_purchase_cost_jpy": 100.0,
            "bess_total_flow_cost_jpy": 30.0,
            "pv_to_bus_cost_jpy": 10.0,
            "pv_to_bess_cost_jpy": 5.0,
            "bess_to_bus_cost_jpy": 15.0,
            "fuel_cost_jpy": 20.0,
            "grid_co2_kg": 0.0,
            "ice_co2_kg": 0.0,
            "total_co2_kg": 0.0,
        },
        {},
    )

    persisted = key_values(path)
    assert cost["electricity_cost"] == pytest.approx(130.0)
    assert cost["total_cost"] == pytest.approx(155.0)
    assert persisted["grid_purchase_cost"] == pytest.approx(100.0)
    assert persisted["pv_self_consumption_cost_jpy"] == pytest.approx(15.0)
    assert persisted["bess_discharge_cost"] == pytest.approx(15.0)
