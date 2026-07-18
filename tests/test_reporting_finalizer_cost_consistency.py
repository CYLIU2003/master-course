from __future__ import annotations

import pytest

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
    assert cost["fuel_cost"] == pytest.approx(
        sum_column(run_dir / "graph" / "fuel_canonical_ledger.csv", "fuel_cost_jpy")
    )
    assert cost["fuel_cost"] == pytest.approx(expected["fuel_cost_jpy"])
    assert cost["total_co2_kg"] == pytest.approx(
        sum_column(run_dir / "graph" / "co2_timeseries.csv", "total_co2_kg")
    )
