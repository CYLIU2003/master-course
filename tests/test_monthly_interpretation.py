import math

import pytest

from scripts.build_monthly_interpretation import (
    cost_difference, failure_reasons, observation_paragraphs, ratio_percent, report_status, seasonal_summary,
)


def _months():
    return [{"month": month, "total_cost": month * 1000,
             "non_vehicle_usage_cost_jpy": month * 100, "grid_import_kwh": month * 10,
             "peak_grid_kw": month * 10, "pv_generated_kwh": month * 100,
             "pv_used_total_kwh": month * 100 - 10, "pv_curtailed_kwh": 10,
             "bess_inventory_drawdown_kwh": 1800} for month in range(1, 13)]


def test_seasonal_pv_ratio_uses_energy_weights_instead_of_mean_percentages():
    winter = seasonal_summary(_months())[0]
    assert winter["months"] == [12, 1, 2]
    assert winter["pv_curtailment_pct"] == pytest.approx(30 / 1500 * 100)
    assert winter["pv_curtailment_pct"] != pytest.approx((10 / 1200 + 10 / 100 + 10 / 200) / 3 * 100)


def test_weekly_cost_mean_peak_extrema_and_separate_inventory_cases():
    winter = seasonal_summary(_months())[0]
    assert winter["mean_weekly_cost_jpy"] == 5000
    assert winter["maximum_peak_grid_kw"] == 120
    assert winter["minimum_peak_grid_kw"] == 10
    assert winter["min_weekly_grid_import_kwh"] == 10
    assert winter["max_weekly_grid_import_kwh"] == 120
    assert winter["three_case_inventory_drawdown_kwh"] == 5400
    assert winter["independent_week_count"] == 3


def test_missing_month_cannot_be_presented_as_a_complete_season():
    with pytest.raises(ValueError, match="missing monthly"):
        seasonal_summary(_months()[:-1])


def test_duplicate_month_is_rejected():
    rows = _months()
    with pytest.raises(ValueError, match="Duplicate monthly"):
        seasonal_summary(rows + [rows[0]])


@pytest.mark.parametrize("numerator,denominator", [(math.nan, 1), (1, math.inf), (0, -1)])
def test_invalid_ratio_inputs_are_rejected(numerator, denominator):
    with pytest.raises(ValueError):
        ratio_percent(numerator, denominator)


def test_zero_generation_ratio_is_unavailable_not_zero_percent():
    assert ratio_percent(0, 0) is None


@pytest.mark.parametrize("status", ["STOPPED_AFTER_FAILED_CASE", "BLOCKED_SOURCE_STATE_DRIFT"])
def test_partial_report_preserves_failure_instead_of_claiming_run_is_active(status):
    assert report_status(status, 3) == status


def test_day_ahead_failure_reason_is_visible_without_a_rolling_chain():
    reason = "[STAGE2_NO_INCUMBENT] Charging optimization returned time_limit"
    assert failure_reasons({"day_ahead_reasons": [reason]}) == [reason]
    assert failure_reasons({"hourly_reasons": [], "day_ahead_reasons": [reason]}) == [reason]
    assert failure_reasons({"hourly_reasons": ["hour failed"], "day_ahead_reasons": [reason]}) == ["hour failed"]
    assert failure_reasons({}) == ["停止理由の記録なし。原本を確認してください。"]


def test_twelve_rows_do_not_replace_campaign_completion_gate():
    with pytest.raises(ValueError, match="Final campaign gate"):
        report_status("RUNNING_WEEK", 12)


def test_cost_difference_preserves_opposing_cost_component_directions():
    rows = [
        {"month": 4, "total_cost": 1000, "vehicle_usage_cost": 600, "non_vehicle_usage_cost_jpy": 400},
        {"month": 8, "total_cost": 900, "vehicle_usage_cost": 800, "non_vehicle_usage_cost_jpy": 100},
    ]
    difference = cost_difference(rows)
    assert difference["highest_month"] == 4 and difference["lowest_month"] == 8
    assert difference["total_cost"] == 100
    assert difference["vehicle_usage_cost"] == -200
    assert difference["non_vehicle_usage_cost_jpy"] == 300
    rows[0]["total_cost"] += 1
    with pytest.raises(ValueError, match="monthly cost difference"):
        cost_difference(rows)


def test_observations_require_completed_results_and_render_separate_quantity_extrema():
    rows = _months()
    for row in rows:
        row["vehicle_usage_cost"] = row["total_cost"] - row["non_vehicle_usage_cost_jpy"]
        row["contract_overage_cost"] = 0
    # Different months lead each quantity, so the text cannot reuse one ranking.
    rows[0]["pv_generated_kwh"] = 5000
    rows[1]["grid_import_kwh"] = 800
    rows[2]["peak_grid_kw"] = 900
    rows[2]["contract_overage_cost"] = 17
    data = {"status": "COMPLETED", "weeks": rows, "seasons": seasonal_summary(rows)}
    paragraphs = observation_paragraphs(data)
    assert "1月の5,000.0 kWhが最多" in paragraphs[0]
    assert "2月の800.0 kWhが最多" in paragraphs[0]
    assert "3月の900.0 kW" in paragraphs[3]
    assert "17.00円" in paragraphs[3]
    assert "統計的な季節効果とは扱わない" in paragraphs[1]
    assert "PV単独の削減効果" in paragraphs[2]
    data["status"] = "IN_PROGRESS"
    with pytest.raises(ValueError, match="completed campaign"):
        observation_paragraphs(data)
