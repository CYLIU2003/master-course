"""A service week may end before its explicitly paid charging horizon."""

from datetime import date, timedelta
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

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
        "next_day_actual_pv_capacity_factor": {
            **pv, "capacity_factor_by_slot": list(pv["capacity_factor_by_slot"])
        },
        "next_day_actual_pv_sha256": content_hash(pv),
        "next_day_actual_pv_source_sha256": ["a" * 64],
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
    assert len(result["next_day_actual_pv_factors"]) == 23


def test_one_day_next_morning_uses_the_same_verified_deadline_contract():
    config, rows = _case()
    next_row = rows[1]
    contract = config["terminal_overnight_contract"]
    config["service_dates"] = config["service_dates"][:1]
    contract["service_dates"] = config["service_dates"]
    contract["next_service_date"] = next_row["service_date"]
    contract["next_day_timetable_rows"] = [next_row]
    contract["next_day_timetable_rows_sha256"] = timetable_hash([next_row])
    contract["first_departure_minute_by_next_day"] = [347]
    for key in ("next_day_pv_capacity_factor", "next_day_actual_pv_capacity_factor"):
        contract[key]["date"] = next_row["service_date"]
    contract["next_day_pv_sha256"] = content_hash(contract["next_day_pv_capacity_factor"])
    contract["next_day_actual_pv_sha256"] = content_hash(contract["next_day_actual_pv_capacity_factor"])

    result = resolve_next_morning_contract(config, timestep_min=15, timetable_rows=rows[:1])
    assert result["target_slots"] == [118]
    assert result["extra_slots"] == 23
    assert result["next_service_date"] == next_row["service_date"]


def test_interactive_run_preserves_verified_paid_next_morning_soc_target():
    from bff.routers.optimization import _apply_interactive_bev_terminal_soc_policy

    config, rows = _case()
    config.update(timestep_min=15, soc_max=0.8,
                  bev_terminal_soc_policy="fixed_target",
                  final_soc_target_percent=80.0,
                  final_soc_target_tolerance_percent=0.0)
    scenario = {"simulation_config": config, "timetable_rows": rows,
                "scenario_overlay": {"charging_constraints": {
                    "bev_terminal_soc_policy": "fixed_target",
                    "final_soc_target_percent": 80.0}}}
    original = deepcopy(scenario)

    controls = _apply_interactive_bev_terminal_soc_policy(scenario)

    assert scenario == original
    assert controls["override_applied"] is False
    assert controls["effective"]["bev_terminal_soc_policy"] == "fixed_target"
    assert controls["effective"]["final_soc_target_percent"] == 80.0


def test_cluster_summary_counts_partial_final_overnight_window():
    from bff.services.cluster.weekly_inputs import horizon_summary

    config, _ = _case()
    config["planning_days"] = 7
    summary = horizon_summary({"simulation_config": config})
    assert summary["horizon_hours"] == 168
    assert summary["energy_horizon_minutes"] == 7 * 1440 + 23 * 15
    assert summary["expected_rolling_windows"] == 174


def test_rolling_execution_covers_every_paid_slot_with_short_last_step():
    from scripts.run_hourly_charging_reoptimization import rolling_step_minutes

    end = 7 * 1440 + 23 * 15
    current = 0
    windows = []
    while current < end:
        minutes = rolling_step_minutes(current, end, 60, 15)
        windows.append(minutes)
        current += minutes
    assert current == end
    assert len(windows) == 174
    assert windows[-1] == 45
    assert all(minutes == 60 for minutes in windows[:-1])


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


def test_historical_pv_replay_pays_for_final_overnight_slots(tmp_path):
    from bff.services.optimization_run.rolling_chain import _prepare_actual_pv_execution_file

    config, _ = _case()
    dates = config["service_dates"]
    actual_row = config["terminal_overnight_contract"]["next_day_actual_pv_capacity_factor"]
    actual_row["capacity_factor_by_slot"][0] = 0.5
    config["terminal_overnight_contract"]["next_day_actual_pv_sha256"] = content_hash(actual_row)
    document = {
        "schema_version": "historical_pv_capacity_factor_execution_v1",
        "service_dates": dates, "timestep_minutes": 15,
        "depot_id": "d1", "source_sha256": "b" * 64,
        "profiles": [{"date": day, "slot_minutes": 15,
                      "capacity_factor_by_slot": [0.0] * 96} for day in dates],
    }
    source = tmp_path / "seven.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    problem = SimpleNamespace(
        metadata={"service_dates": dates,
                  "bev_soc_deadline_mode": "next_morning_operational_max",
                  "terminal_overnight_contract": config["terminal_overnight_contract"],
                  "date_series_contract": {
                      "pv_information_mode": "training_only_forecast_proxy",
                      "pv_execution_input": {
                          "path": "seven.json",
                          "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      },
                  }},
        scenario=SimpleNamespace(timestep_min=15),
        depot_energy_assets={"d1": SimpleNamespace(
            pv_capacity_kw=10.0, pv_supply_scale=1.0, pv_enabled=True,
        )},
        price_slots=tuple(range(672 + 23)),
    )
    path = _prepare_actual_pv_execution_file(problem, tmp_path / "run", repo_root=tmp_path)
    payload = json.loads(open(path, encoding="utf-8").read())
    assert len(payload["depot_profiles"]["d1"]) == 695
    assert payload["depot_profiles"]["d1"][672] == pytest.approx(1.25)
    assert payload["overnight_actual_pv"]["slot_count"] == 23
    assert payload["source_sha256"] != document["source_sha256"]
