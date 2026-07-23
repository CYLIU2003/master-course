from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.audit_phase3_weather_energy_balance import (
    _advisor_case_acceptance,
    _canonical_hash,
    _interval_overlaps_slot,
    _load_effective_scenario,
    _operation_and_fuel,
    _service_minute,
)


class _ProblemStub:
    def __init__(self) -> None:
        self._trips = {
            "trip-1": SimpleNamespace(
                trip_id="trip-1",
                departure_min=330,
                arrival_min=390,
                distance_km=10.0,
                fuel_l=2.0,
            )
        }
        self.vehicles = []
        self.vehicle_types = [
            SimpleNamespace(
                vehicle_type_id="ICE",
                fuel_consumption_l_per_km=0.2,
            )
        ]
        self.metadata = {"deadhead_speed_kmh": 18.0}

    def trip_by_id(self):
        return self._trips


def test_effective_scenario_is_loaded_from_run_artifact(tmp_path) -> None:
    scenario = {"meta": {"id": "scenario-1"}, "timetable_rows": []}
    (tmp_path / "effective_scenario.json").write_text(
        json.dumps(scenario),
        encoding="utf-8",
    )

    loaded = _load_effective_scenario(
        tmp_path,
        {
            "effective_scenario_artifact": "effective_scenario.json",
            "effective_scenario_sha256": _canonical_hash(scenario),
        },
    )

    assert loaded == scenario


def test_effective_scenario_rejects_hash_mismatch(tmp_path) -> None:
    (tmp_path / "effective_scenario.json").write_text(
        json.dumps({"meta": {"id": "changed"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match"):
        _load_effective_scenario(
            tmp_path,
            {
                "effective_scenario_artifact": "effective_scenario.json",
                "effective_scenario_sha256": "0" * 64,
            },
        )


def test_effective_scenario_rejects_path_escape(tmp_path) -> None:
    with pytest.raises(ValueError, match="directly inside"):
        _load_effective_scenario(
            tmp_path,
            {
                "effective_scenario_artifact": "../effective_scenario.json",
                "effective_scenario_sha256": "0" * 64,
            },
        )


def test_advisor_acceptance_requires_terminal_energy_and_formal_fleet() -> None:
    case = {
        "git_dirty": False,
        "scenario_parameters": {
            "fleet": {"BEV": 35, "ICE": 26},
            "expected_fleet": {"BEV": 35, "ICE": 26},
            "trip_count": 264,
            "charger_configuration": [
                {"power_kw": 90.0, "simultaneous_ports": 5},
                {"power_kw": 50.0, "simultaneous_ports": 5},
            ],
        },
        "solver": {
            "bev_terminal_soc_balance_satisfied": True,
            "physical_charger_assignment_semantics": (
                "one_physical_charger_definition_per_active_vehicle_slot; "
                "simultaneous_ports_are_identical_ports"
            ),
        },
        "operation": {"assigned_trip_count": {"BEV": 78, "ICE": 186}},
        "balances": {"all_balances_passed": True},
        "bess": {
            "terminal_target_kwh": 300.0,
            "terminal_target_deviation_kwh": 0.0,
        },
        "fuel": {"cost_residual_jpy": 0.0},
        "validation_metrics": {
            "all_required_validation_checks_passed": True
        },
    }

    accepted = _advisor_case_acceptance(case)
    assert accepted["accepted"] is True

    case["bess"]["terminal_target_deviation_kwh"] = 1.0
    rejected = _advisor_case_acceptance(case)
    assert rejected["accepted"] is False
    assert rejected["failed_checks"] == ["bess_terminal_soc_balanced"]


def test_service_minute_wraps_clock_time_before_horizon() -> None:
    assert _service_minute(120, 300) == 1560
    assert _service_minute(330, 300) == 330


def test_interval_overlap_uses_half_open_hour_slots() -> None:
    assert _interval_overlaps_slot(
        330,
        390,
        slot_index=0,
        horizon_start_min=300,
        timestep_min=60,
    )
    assert _interval_overlaps_slot(
        330,
        390,
        slot_index=1,
        horizon_start_min=300,
        timestep_min=60,
    )
    assert not _interval_overlaps_slot(
        330,
        390,
        slot_index=2,
        horizon_start_min=300,
        timestep_min=60,
    )


def test_operation_fuel_matches_service_and_intertrip_distance_accounting() -> None:
    result = {
        "metadata": {"duty_vehicle_map": {"duty-1": "ice-1"}},
        "duties": [
            {
                "duty_id": "duty-1",
                "vehicle_type": "ICE",
                "legs": [
                    {
                        "trip_id": "trip-1",
                        "deadhead_from_prev_min": 10,
                    }
                ],
            }
        ],
    }

    operation = _operation_and_fuel(
        _ProblemStub(),
        result,
        horizon_start_min=300,
        timestep_min=60,
        slot_count=24,
    )

    assert operation["used_vehicle_count"] == {"BEV": 0, "ICE": 1}
    assert operation["assigned_trip_count"] == {"BEV": 0, "ICE": 1}
    assert operation["service_distance_km"]["ICE"] == 10.0
    assert operation["intertrip_deadhead_distance_km"]["ICE"] == 3.0
    assert operation["fuel_service_l"] == 2.0
    assert operation["fuel_intertrip_deadhead_l"] == pytest.approx(0.6)
    assert operation["fuel_total_l"] == pytest.approx(2.6)
    assert operation["active_vehicle_count_by_slot"]["ICE"][:3] == [1, 1, 0]
