from __future__ import annotations

from scripts.benchmark_solver_modes import mark_prepare_snapshot_matches


def _row(**overrides):
    base = {
        "scenario_hash": "s1",
        "scope_hash": "scope1",
        "trip_count": 10,
        "vehicle_count": 3,
        "available_vehicle_count_total": 2,
        "objective_mode": "total_cost",
        "service_coverage_mode": "strict",
        "counts_for_comparison": True,
        "benchmark_tier": "main",
    }
    base.update(overrides)
    return base


def test_prepare_snapshot_match_true_for_identical_snapshot() -> None:
    rows = mark_prepare_snapshot_matches([_row(mode="a"), _row(mode="b")])

    assert [row["prepare_snapshot_match"] for row in rows] == [True, True]
    assert [row["prepare_mismatch_reason"] for row in rows] == ["", ""]


def test_prepare_snapshot_match_false_when_any_key_differs() -> None:
    rows = mark_prepare_snapshot_matches([_row(mode="a"), _row(mode="b", scope_hash="scope2")])

    assert rows[1]["prepare_snapshot_match"] is False
    assert "scope_hash" in rows[1]["prepare_mismatch_reason"]
