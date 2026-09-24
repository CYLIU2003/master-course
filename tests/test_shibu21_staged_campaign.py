"""Shibu21's staged campaign must keep one transition contract."""

from tools.research.shibu21_monthly import monthly_request
import json

import pytest

from tools.research.shibu21_staged_campaign import (
    WEEK_MINIMUM_FREE_RAM_GB, day_request, require_week_capacity,
)


def test_day_and_month_requests_share_corrected_lazy_reset_separation():
    day = day_request("prepared-day")
    month = monthly_request("prepared-week")
    assert day["stage1_fragment_transition_cut_mode"] == "lazy"
    assert month["stage1_fragment_transition_cut_mode"] == "lazy"
    assert day["gurobi_threads"] == month["gurobi_threads"] == 4
    assert day["research_run"] is month["research_run"] is False
    assert day["prepared_input_id"] != month["prepared_input_id"]


def test_week_admission_preserves_system_reserve(tmp_path, monkeypatch):
    config = tmp_path / "workers.json"
    config.write_text(json.dumps({"workers": [{"id": "local", "enabled": True,
                                                "transport": "local",
                                                "reserved_system_ram_gb": 1}]}),
                      encoding="utf-8")
    assert WEEK_MINIMUM_FREE_RAM_GB == 18.0
    monkeypatch.setattr("tools.research.shibu21_staged_campaign.memory_metrics",
                        lambda: {"ram_free_gb": 18.9})
    with pytest.raises(ValueError, match="No job was submitted"):
        require_week_capacity({"config": str(config)}, WEEK_MINIMUM_FREE_RAM_GB)
    monkeypatch.setattr("tools.research.shibu21_staged_campaign.memory_metrics",
                        lambda: {"ram_free_gb": 19.1})
    require_week_capacity({"config": str(config)}, WEEK_MINIMUM_FREE_RAM_GB)
