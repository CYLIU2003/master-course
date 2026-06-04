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
