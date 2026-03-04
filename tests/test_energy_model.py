"""
tests/test_energy_model.py

Regression tests for preprocess energy model helpers.
"""

from src.preprocess.energy_model import estimate_trip_energy_bev
from src.schemas.fleet_entities import VehicleType
from src.schemas.route_entities import Segment


def test_level1_hvac_handles_none_heating_power():
    vehicle_type = VehicleType(
        vehicle_type_id="bev_test",
        powertrain="BEV",
        base_energy_rate_kwh_per_km=1.2,
        hvac_power_kw_cooling=3.0,
        hvac_power_kw_heating=None,
    )
    segments = [
        Segment(
            segment_id="seg_1",
            route_id="R1",
            direction_id="outbound",
            from_stop_id="S1",
            to_stop_id="S2",
            sequence=1,
            distance_km=10.0,
            scheduled_run_time_min=30.0,
        )
    ]

    energy_kwh, breakdown = estimate_trip_energy_bev(
        segments=segments,
        vehicle_type=vehicle_type,
        level=1,
    )

    assert energy_kwh > 0.0
    assert breakdown["hvac"] == 0.75
