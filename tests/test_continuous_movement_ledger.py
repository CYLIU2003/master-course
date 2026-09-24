from datetime import date, datetime, timedelta

import pytest

from src.optimization.accounting.ledger_builder import _build_movement_event_ledger


@pytest.mark.parametrize(
    "event_type",
    ["startup_deadhead", "connection_deadhead", "daily_return", "daily_startup", "terminal_return"],
)
def test_continuous_timeline_movement_survives_accounting_with_physical_quantities(event_type):
    start = datetime(2025, 5, 12, 7, 0)
    source = {
        "event_id": f"bus-1:continuous_vehicle_path:1:{event_type}:a:b",
        "event_type": event_type,
        "vehicle_id": "bus-1",
        "vehicle_type": "ICE",
        "event_start": start.isoformat(),
        "event_end": (start + timedelta(minutes=10)).isoformat(),
        "duration_min": 10,
        "distance_km": 4.5,
        "ice_fuel_liter": 0.9,
        "ice_co2_kg": 2.322,
        "from_location_id": "a",
        "to_location_id": "b",
    }

    row, = _build_movement_event_ledger(
        scenario_id="scenario-1", run_id="run-1", service_date=date(2025, 5, 12),
        operator_id="odpt.Operator:TokyuBus", movement_event_rows=[source],
    )

    assert row.event_type == event_type
    assert row.distance_km == 4.5
    assert row.ice_fuel_liter == 0.9
    assert row.ice_co2_kg == 2.322
    assert row.operator_id == "odpt.Operator:TokyuBus"


def test_unknown_canonical_movement_type_is_still_rejected():
    with pytest.raises(ValueError, match="unsupported type"):
        _build_movement_event_ledger(
            scenario_id="scenario-1", run_id="run-1", service_date=date(2025, 5, 12),
            operator_id="odpt.Operator:TokyuBus",
            movement_event_rows=[{"event_id": "unknown-1", "event_type": "arbitrary"}],
        )
