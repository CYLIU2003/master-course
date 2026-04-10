from __future__ import annotations

from scripts.benchmark_solver_modes import mark_prepare_snapshot_matches


def test_prepare_mismatch_is_excluded_from_main_comparison() -> None:
    rows = mark_prepare_snapshot_matches(
        [
            {
                "scenario_hash": "s1",
                "scope_hash": "scope1",
                "trip_count": 10,
                "vehicle_count": 3,
                "available_vehicle_count_total": 2,
                "objective_mode": "total_cost",
                "service_coverage_mode": "strict",
                "counts_for_comparison": True,
                "benchmark_tier": "main",
            },
            {
                "scenario_hash": "s1",
                "scope_hash": "scope2",
                "trip_count": 10,
                "vehicle_count": 3,
                "available_vehicle_count_total": 2,
                "objective_mode": "total_cost",
                "service_coverage_mode": "strict",
                "counts_for_comparison": True,
                "benchmark_tier": "main",
            },
        ]
    )

    assert rows[1]["counts_for_comparison"] is False
    assert rows[1]["benchmark_tier"] == "appendix_prepare_mismatch"
