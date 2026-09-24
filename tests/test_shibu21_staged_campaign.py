"""Shibu21's staged campaign must keep one transition contract."""

from tools.research.shibu21_monthly import monthly_request
from tools.research.shibu21_staged_campaign import day_request


def test_day_and_month_requests_share_corrected_lazy_reset_separation():
    day = day_request("prepared-day")
    month = monthly_request("prepared-week")
    assert day["stage1_fragment_transition_cut_mode"] == "lazy"
    assert month["stage1_fragment_transition_cut_mode"] == "lazy"
    assert day["gurobi_threads"] == month["gurobi_threads"] == 4
    assert day["research_run"] is month["research_run"] is False
    assert day["prepared_input_id"] != month["prepared_input_id"]
