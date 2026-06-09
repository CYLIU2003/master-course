from __future__ import annotations

import pytest

from tests._reporting_finalizer_utils import RUN_EXPECTATIONS, finalized_run, key_values, load_json


@pytest.mark.parametrize("run_id", sorted(RUN_EXPECTATIONS))
def test_reporting_finalizer_summary_definition(tmp_path, run_id):
    run_dir = finalized_run(tmp_path, run_id)
    expected = RUN_EXPECTATIONS[run_id]
    summary = load_json(run_dir / "summary.json")
    cost = key_values(run_dir / "cost_breakdown_detail.csv")
    objective = key_values(run_dir / "objective_breakdown.csv")

    assert summary["total_cost_jpy"] == pytest.approx(cost["total_cost"])
    assert summary["gross_operating_cost_jpy"] == pytest.approx(cost["total_cost"])
    assert summary["reported_total_cost_jpy"] == pytest.approx(cost["total_cost"])
    assert summary["gross_operating_cost_jpy"] == pytest.approx(expected["gross_operating_cost_jpy"])
    assert summary["objective_value_jpy"] == pytest.approx(objective["objective_value"])
    assert summary["objective_value_jpy"] == pytest.approx(expected["objective_value_jpy"])
    assert summary["objective_is_actual_cost"] is False
    assert summary["cost_definition"]["objective_is_actual_cost"] is False
