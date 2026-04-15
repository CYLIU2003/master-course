from __future__ import annotations

from bff.routers.optimization import _solution_validity_payload


def test_baseline_fallback_with_zero_unserved_is_not_validated_no_cancellation() -> None:
    payload = _solution_validity_payload(
        solver_status="BASELINE_FALLBACK",
        feasible=False,
        trip_count_unserved=0,
        infeasibility_reasons=[],
    )

    assert payload["validated_no_cancellation"] is False
    assert payload["validated_feasible"] is False
    assert payload["status_reason"] == "baseline_fallback_or_postsolve_infeasible"
    assert "baseline_fallback" in payload["blocking_reasons"]
    assert "postsolve_infeasible" in payload["blocking_reasons"]


def test_partial_baseline_fallback_is_marked_explicitly() -> None:
    payload = _solution_validity_payload(
        solver_status="PARTIAL_BASELINE_FALLBACK",
        feasible=False,
        trip_count_unserved=3,
        infeasibility_reasons=[],
    )

    assert payload["validated_no_cancellation"] is False
    assert payload["validated_feasible"] is False
    assert payload["status_reason"] == "partial_baseline_fallback"
    assert "baseline_fallback" in payload["blocking_reasons"]
    assert "partial_baseline_fallback" in payload["blocking_reasons"]
    assert "postsolve_infeasible" in payload["blocking_reasons"]


def test_solved_feasible_with_zero_unserved_is_validated_no_cancellation() -> None:
    payload = _solution_validity_payload(
        solver_status="SOLVED_FEASIBLE",
        feasible=True,
        trip_count_unserved=0,
        infeasibility_reasons=[],
    )

    assert payload["validated_no_cancellation"] is True
    assert payload["validated_feasible"] is True
    assert payload["blocking_reasons"] == []
