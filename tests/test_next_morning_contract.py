"""A service week may end before its explicitly paid charging horizon."""

from datetime import date, timedelta

import pytest

from src.optimization.common.bev_terminal_policy import validate_bev_soc_timing_config
from src.optimization.common.date_series import content_hash, timetable_hash
from src.optimization.common.next_morning import PRICE_POLICY, SCHEMA, resolve_next_morning_contract


def _case():
    days = [(date(2025, 5, 12) + timedelta(days=index)).isoformat() for index in range(8)]
    rows = [
        {
            "trip_id": f"{day}::trip", "template_trip_id": "trip", "route_id": "route",
            "operator_id": "tokyu", "service_id": "WEEKDAY", "service_date": day,
            "day_index": index, "origin": "A", "destination": "B",
            "departure": f"{index * 24 + 5:02d}:47", "arrival": f"{index * 24 + 6:02d}:00",
            "source_departure": "05:47", "source_arrival": "06:00",
            "distance_km": 1.0, "distance_source": "measured",
            "allowed_vehicle_types": ["BEV"], "source_provenance": {"id": "verified"},
        }
        for index, day in enumerate(days)
    ]
    pv = {"date": days[-1], "slot_minutes": 15,
          "capacity_factor_by_slot": [0.0] * 96}
    contract = {
        "schema_version": SCHEMA, "service_dates": days[:7],
        "next_service_date": days[-1],
        "next_day_timetable_rows": [rows[-1]],
        "next_day_timetable_rows_sha256": timetable_hash([rows[-1]]),
        "first_departure_minute_by_next_day": [347] * 7,
        "next_day_pv_capacity_factor": pv,
        "next_day_pv_sha256": content_hash(pv),
        "price_calendar_policy": PRICE_POLICY,
    }
    config = {
        "bev_soc_deadline_mode": "next_morning_operational_max",
        "final_overnight_mode": "include", "timestep_min": 15,
        "service_dates": days[:7], "terminal_overnight_contract": contract,
    }
    return config, rows[:7]


def test_next_morning_extends_energy_slots_only_until_departure():
    config, rows = _case()
    assert validate_bev_soc_timing_config(config) == (
        "next_morning_operational_max", "include"
    )
    result = resolve_next_morning_contract(config, timestep_min=15, timetable_rows=rows)
    assert result["extra_slots"] == 23  # 05:45 is the last completed slot before 05:47.
    assert result["target_slots"] == [118, 214, 310, 406, 502, 598, 694]
    assert len(result["next_day_pv_factors"]) == 23


def test_next_morning_rejects_changed_timetable_or_pv():
    config, rows = _case()
    config["terminal_overnight_contract"]["next_day_timetable_rows"][0]["source_departure"] = "05:30"
    with pytest.raises(ValueError, match="TIMETABLE_HASH_MISMATCH"):
        resolve_next_morning_contract(config, timestep_min=15, timetable_rows=rows)
    config, rows = _case()
    config["terminal_overnight_contract"]["next_day_pv_capacity_factor"]["capacity_factor_by_slot"][0] = 0.5
    with pytest.raises(ValueError, match="PV_HASH_MISMATCH"):
        resolve_next_morning_contract(config, timestep_min=15, timetable_rows=rows)


def test_next_morning_rejects_unpaid_final_night():
    config, _ = _case()
    config["final_overnight_mode"] = "exclude"
    with pytest.raises(ValueError, match="NEXT_MORNING_SOC_NOT_READY"):
        validate_bev_soc_timing_config(config)
