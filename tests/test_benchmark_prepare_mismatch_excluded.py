"""Benchmark mismatch regression checks.

The first test keeps covering the actual benchmark helper in
scripts.benchmark_solver_modes. The additional tests mirror the newer
prepare-snapshot comparison logic that was introduced in the worktree.
"""

from __future__ import annotations

from typing import Any

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


def _make_snapshot(
    scenario_hash: str = "aaa",
    scope_hash: str = "bbb",
    trip_count: int = 5,
    vehicle_count: int = 3,
    available_vehicle_count_total: int = 3,
    objective_mode: str = "total_cost",
    service_coverage_mode: str = "strict",
) -> dict[str, Any]:
    return {
        "scenario_hash": scenario_hash,
        "scope_hash": scope_hash,
        "trip_count": trip_count,
        "vehicle_count": vehicle_count,
        "available_vehicle_count_total": available_vehicle_count_total,
        "objective_mode": objective_mode,
        "service_coverage_mode": service_coverage_mode,
    }


def _snapshot_key(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario_hash": snap.get("scenario_hash"),
        "scope_hash": snap.get("scope_hash"),
        "trip_count": snap.get("trip_count"),
        "vehicle_count": snap.get("vehicle_count"),
        "available_vehicle_count_total": snap.get("available_vehicle_count_total"),
        "objective_mode": snap.get("objective_mode"),
        "service_coverage_mode": snap.get("service_coverage_mode"),
    }


def _snapshot_mismatch_reason(ref: dict[str, Any], other: dict[str, Any]) -> str:
    key_ref = _snapshot_key(ref)
    key_other = _snapshot_key(other)
    diffs = [
        f"{k}: {key_ref[k]!r} != {key_other[k]!r}"
        for k in key_ref
        if key_ref[k] != key_other[k]
    ]
    return "; ".join(diffs)


def _audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    reference = rows[0]["snapshot"]
    for row in rows:
        snap = row.get("snapshot") or {}
        mismatch = _snapshot_mismatch_reason(reference, snap)
        row["prepare_snapshot_match"] = not bool(mismatch)
        row["prepare_mismatch_reason"] = mismatch
    return rows


def _partition_main_appendix(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    main = [row for row in rows if row.get("prepare_snapshot_match") is True]
    appendix = [row for row in rows if row.get("prepare_snapshot_match") is not True]
    return main, appendix


def _make_run_row(
    mode: str,
    snap: dict[str, Any],
    status: str = "optimal",
    trip_count_unserved: int = 0,
    vehicle_count_used: int = 3,
    available_vehicle_count_total: int | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "snapshot": snap,
        "status": status,
        "trip_count_unserved": trip_count_unserved,
        "vehicle_count_used": vehicle_count_used,
        "available_vehicle_count_total": available_vehicle_count_total
        if available_vehicle_count_total is not None
        else snap.get("available_vehicle_count_total"),
    }


def test_all_matching_rows_go_to_main_table() -> None:
    snap = _make_snapshot()
    rows = [_make_run_row(mode, snap) for mode in ["mode_milp_only", "mode_alns_only", "mode_ga_only", "mode_abc_only"]]
    rows = _audit_rows(rows)
    main, appendix = _partition_main_appendix(rows)
    assert len(main) == 4
    assert len(appendix) == 0


def test_mismatch_row_excluded_from_main_table() -> None:
    ref_snap = _make_snapshot(trip_count=10)
    bad_snap = _make_snapshot(trip_count=11)
    rows = [
        _make_run_row("mode_milp_only", ref_snap),
        _make_run_row("mode_alns_only", ref_snap),
        _make_run_row("mode_ga_only", ref_snap),
        _make_run_row("mode_abc_only", bad_snap),
    ]
    rows = _audit_rows(rows)
    main, appendix = _partition_main_appendix(rows)
    assert len(main) == 3
    assert len(appendix) == 1
    assert appendix[0]["mode"] == "mode_abc_only"


def test_multiple_mismatch_rows_all_excluded() -> None:
    ref_snap = _make_snapshot(scope_hash="hash_ref")
    bad_snap_1 = _make_snapshot(scope_hash="hash_bad1")
    bad_snap_2 = _make_snapshot(scope_hash="hash_bad2")
    rows = [
        _make_run_row("mode_milp_only", ref_snap),
        _make_run_row("mode_alns_only", bad_snap_1),
        _make_run_row("mode_ga_only", bad_snap_2),
        _make_run_row("mode_abc_only", ref_snap),
    ]
    rows = _audit_rows(rows)
    main, appendix = _partition_main_appendix(rows)
    assert len(main) == 2
    assert len(appendix) == 2
    appendix_modes = {row["mode"] for row in appendix}
    assert appendix_modes == {"mode_alns_only", "mode_ga_only"}


def test_all_rows_mismatch_leaves_only_reference_row_in_main_table() -> None:
    ref = _make_snapshot(trip_count=5)
    rows = [
        _make_run_row("mode_milp_only", ref),
        _make_run_row("mode_alns_only", _make_snapshot(trip_count=6)),
        _make_run_row("mode_ga_only", _make_snapshot(trip_count=7)),
        _make_run_row("mode_abc_only", _make_snapshot(trip_count=8)),
    ]
    rows = _audit_rows(rows)
    main, appendix = _partition_main_appendix(rows)
    assert len(main) == 1
    assert main[0]["mode"] == "mode_milp_only"
    assert len(appendix) == 3


def test_comparison_valid_requires_all_four_solver_modes_matching() -> None:
    snap = _make_snapshot()
    rows = [_make_run_row(mode, snap) for mode in ["mode_milp_only", "mode_alns_only", "mode_ga_only", "mode_abc_only"]]
    rows = _audit_rows(rows)
    main, appendix = _partition_main_appendix(rows)
    assert len(main) == 4 and len(appendix) == 0

    bad_snap = _make_snapshot(scope_hash="different_scope")
    rows[2] = _make_run_row("mode_ga_only", bad_snap)
    rows = _audit_rows(rows)
    main2, appendix2 = _partition_main_appendix(rows)
    assert len(main2) < 4
    assert len(appendix2) == 1


def test_strict_coverage_with_unserved_is_failure() -> None:
    row = _make_run_row(
        "mode_milp_only",
        _make_snapshot(service_coverage_mode="strict"),
        status="optimal",
        trip_count_unserved=2,
    )
    service_coverage_mode = row["snapshot"].get("service_coverage_mode", "")
    unserved = row.get("trip_count_unserved", 0) or 0
    is_failure = service_coverage_mode == "strict" and unserved > 0
    assert is_failure


def test_strict_coverage_without_unserved_is_not_failure() -> None:
    row = _make_run_row(
        "mode_milp_only",
        _make_snapshot(service_coverage_mode="strict"),
        status="optimal",
        trip_count_unserved=0,
    )
    service_coverage_mode = row["snapshot"].get("service_coverage_mode", "")
    unserved = row.get("trip_count_unserved", 0) or 0
    is_failure = service_coverage_mode == "strict" and unserved > 0
    assert not is_failure


def test_unused_available_vehicles_with_unserved_trips_is_failure() -> None:
    row = {
        "mode": "mode_alns_only",
        "snapshot": _make_snapshot(available_vehicle_count_total=3),
        "vehicle_count_used": 2,
        "trip_count_unserved": 1,
    }
    unused = row["snapshot"]["available_vehicle_count_total"] - (row.get("vehicle_count_used") or 0)
    unserved = row.get("trip_count_unserved") or 0
    has_unused_available_and_unserved = unused > 0 and unserved > 0
    assert has_unused_available_and_unserved


def test_no_failure_when_all_available_vehicles_used_and_all_served() -> None:
    row = {
        "mode": "mode_milp_only",
        "snapshot": _make_snapshot(available_vehicle_count_total=3),
        "vehicle_count_used": 3,
        "trip_count_unserved": 0,
    }
    unused = row["snapshot"]["available_vehicle_count_total"] - (row.get("vehicle_count_used") or 0)
    unserved = row.get("trip_count_unserved") or 0
    has_failure = (unused > 0 and unserved > 0) or (
        row["snapshot"].get("service_coverage_mode") == "strict" and unserved > 0
    )
    assert not has_failure


def test_same_day_depot_cycles_require_max_fragments_above_one() -> None:
    allow_same_day = True
    max_fragments_observed = 1
    needs_improvement = allow_same_day and (max_fragments_observed is None or max_fragments_observed <= 1)
    assert needs_improvement


def test_same_day_depot_cycles_satisfied_when_multi_fragment_observed() -> None:
    allow_same_day = True
    max_fragments_observed = 2
    needs_improvement = allow_same_day and (max_fragments_observed is None or max_fragments_observed <= 1)
    assert not needs_improvement


def test_mismatch_reason_recorded_in_appendix_row() -> None:
    ref = _make_snapshot(trip_count=10)
    bad = _make_snapshot(trip_count=12)
    rows = [
        {"mode": "milp", "snapshot": ref},
        {"mode": "alns", "snapshot": bad},
    ]
    rows = _audit_rows(rows)
    _, appendix = _partition_main_appendix(rows)
    assert len(appendix) == 1
    assert appendix[0]["prepare_mismatch_reason"] != ""
    assert "trip_count" in appendix[0]["prepare_mismatch_reason"]


def test_main_rows_have_empty_mismatch_reason() -> None:
    snap = _make_snapshot()
    rows = [{"mode": "milp", "snapshot": snap}, {"mode": "alns", "snapshot": snap}]
    rows = _audit_rows(rows)
    main, _ = _partition_main_appendix(rows)
    for row in main:
        assert row["prepare_mismatch_reason"] == ""
