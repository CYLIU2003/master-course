import math

import pytest

from scripts.build_monthly_interpretation import ratio_percent, report_status, seasonal_summary


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


def test_twelve_rows_do_not_replace_campaign_completion_gate():
    with pytest.raises(ValueError, match="Final campaign gate"):
        report_status("RUNNING_WEEK", 12)
