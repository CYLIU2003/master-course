from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.audit_phase3_weather_energy_balance import (
    _interval_overlaps_slot,
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
