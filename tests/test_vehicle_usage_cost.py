from __future__ import annotations

from src.optimization.accounting.aggregators import build_accounting_summary


def test_vehicle_usage_cost_uses_vehicle_day_count() -> None:
    rows = [
        {"vehicle_id": f"veh-{idx}", "slot_start": "2026-01-01T08:00:00", "trip_id": f"t{idx}"}
        for idx in range(10)
    ]

    summary = build_accounting_summary(
        vehicle_rows=rows,
        vehicle_energy_rows=[],
        energy_rows=[],
        metadata={"vehicle_usage_cost_jpy_per_used_bus": 30000},
    )

    assert summary["used_vehicle_day_count"] == 10
    assert summary["vehicle_usage_cost_jpy"] == 300000
    assert summary["total_cost_jpy"] == 300000


def test_assignment_rows_are_source_of_truth_for_trip_and_vehicle_counts() -> None:
    vehicle_rows = [
        {
            "vehicle_id": "duty-fragment-a",
            "vehicle_type": "BEV",
            "slot_start": "2026-01-01T08:00:00",
            "trip_id": "trip-1",
            "soc_start_ratio": 0.8,
            "soc_end_ratio": 0.6,
        },
        {
            "vehicle_id": "duty-fragment-b",
            "vehicle_type": "ICE",
            "slot_start": "2026-01-01T08:00:00",
            "trip_id": "trip-3",
            "soc_start_ratio": 0.0,
            "soc_end_ratio": 0.0,
        },
    ]
    assignments = [
        {
            "trip_id": "trip-1",
            "assigned_vehicle_id": "bev-1",
            "assigned_vehicle_type": "BEV",
            "scheduled_departure": "2026-01-01T08:05:00",
            "served_flag": True,
        },
        {
            "trip_id": "trip-2",
            "assigned_vehicle_id": "bev-1",
            "assigned_vehicle_type": "BEV",
            "scheduled_departure": "2026-01-01T08:45:00",
            "served_flag": True,
        },
        {
            "trip_id": "trip-3",
            "assigned_vehicle_id": "ice-1",
            "assigned_vehicle_type": "ICE",
            "scheduled_departure": "2026-01-01T08:10:00",
            "served_flag": True,
        },
    ]

    summary = build_accounting_summary(
        vehicle_rows=vehicle_rows,
        vehicle_energy_rows=[],
        energy_rows=[],
        trip_assignment_rows=assignments,
        metadata={
            "service_date": "2026-01-01",
            "vehicle_usage_cost_jpy_per_used_bus": 20_000,
        },
    )

    assert summary["served_trip_count"] == 3
    assert summary["bev_trip_count"] == 2
    assert summary["ice_trip_count"] == 1
    assert summary["used_vehicle_count"] == 2
    assert summary["used_vehicle_day_count"] == 2
    assert summary["vehicle_usage_cost_jpy"] == 40_000
    assert summary["min_soc_ratio"] == 0.6


def test_unserved_assignment_does_not_fall_back_to_vehicle_slot_counts() -> None:
    summary = build_accounting_summary(
        vehicle_rows=[
            {
                "vehicle_id": "stale-vehicle",
                "vehicle_type": "ICE",
                "slot_start": "2026-01-01T08:00:00",
                "trip_id": "trip-1",
            }
        ],
        vehicle_energy_rows=[],
        energy_rows=[],
        trip_assignment_rows=[
            {
                "trip_id": "trip-1",
                "assigned_vehicle_id": "",
                "assigned_vehicle_type": "",
                "served_flag": False,
            }
        ],
        metadata={"vehicle_usage_cost_jpy_per_used_bus": 20_000},
    )

    assert summary["served_trip_count"] == 0
    assert summary["unserved_trip_count"] == 1
    assert summary["used_vehicle_count"] == 0
    assert summary["used_vehicle_day_count"] == 0
    assert summary["vehicle_usage_cost_jpy"] == 0.0
