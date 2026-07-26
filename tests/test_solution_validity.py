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
    assert payload["research_kpi_eligible"] is False


def test_gurobi_unavailable_baseline_is_classified_as_fallback() -> None:
    payload = _solution_validity_payload(
        solver_status="gurobi_unavailable_baseline",
        feasible=True,
        trip_count_unserved=0,
        infeasibility_reasons=[],
    )

    assert payload["validated_no_cancellation"] is False
    assert payload["validated_feasible"] is False
    assert payload["result_class"] == "baseline_fallback"
    assert "baseline_fallback" in payload["blocking_reasons"]


def test_postsolve_repair_detected_via_solver_metadata() -> None:
    payload = _solution_validity_payload(
        solver_status="OPTIMAL",
        feasible=True,
        trip_count_unserved=0,
        infeasibility_reasons=[],
        solver_metadata={"postsolve_soc_repair_applied": True},
    )

    assert payload["validated_no_cancellation"] is False
    assert payload["result_class"] == "repaired_heuristic"
    assert "repaired_heuristic" in payload["blocking_reasons"]
    assert payload["research_kpi_eligible"] is False


def test_debug_result_is_not_research_kpi_eligible() -> None:
    payload = _solution_validity_payload(
        solver_status="debug_result",
        feasible=True,
        trip_count_unserved=0,
        infeasibility_reasons=[],
        solver_metadata={"debug_mode": True, "result_class": "debug_result"},
    )

    assert payload["validated_no_cancellation"] is False
    assert payload["validated_feasible"] is False
    assert payload["result_class"] == "debug_result"
    assert payload["research_kpi_eligible"] is False
    assert "debug_result" in payload["blocking_reasons"]


def test_terminal_soc_failure_blocks_validated_feasible_label() -> None:
    payload = _solution_validity_payload(
        solver_status="FEASIBLE",
        feasible=True,
        trip_count_unserved=0,
        infeasibility_reasons=[],
        solver_metadata={
            "bev_terminal_soc_policy": "return_to_initial",
            "bev_terminal_soc_balance_satisfied": False,
            "bess_terminal_soc_deviation_kwh": 2.0e-6,
            "bess_terminal_soc_tolerance_kwh": 1.0e-6,
        },
    )

    assert payload["validated_feasible"] is False
    assert payload["status_reason"] == "terminal_soc_balance_failed"
    assert payload["blocking_reasons"] == [
        "bess_terminal_soc_balance_failed",
        "bev_terminal_soc_balance_failed",
    ]


def test_phase2_assignment_only_is_not_full_research_kpi() -> None:
    payload = _solution_validity_payload(
        solver_status="phase2_assignment_feasible",
        feasible=True,
        trip_count_unserved=0,
        infeasibility_reasons=[],
        solver_metadata={"phase": "phase2_assignment_only", "result_class": "assignment_only_result"},
    )

    assert payload["validated_no_cancellation"] is False
    assert payload["result_class"] == "assignment_only_result"
    assert payload["research_kpi_eligible"] is False
    assert "assignment_only_result" in payload["blocking_reasons"]


def test_phase2_research_assignment_eligibility_is_explicitly_separate_from_soc_feasibility() -> None:
    payload = _solution_validity_payload(
        solver_status="phase2_assignment_feasible",
        feasible=True,
        trip_count_unserved=0,
        infeasibility_reasons=[],
        solver_metadata={
            "phase": "phase2_assignment_only",
            "result_class": "assignment_only_result",
            "research_run": True,
            "research_run_accepted": True,
            "research_feasibility_eligible": True,
        },
    )

    assert payload["validated_feasible"] is False
    assert payload["research_feasibility_eligible"] is False
    assert payload["research_assignment_eligible"] is True
    assert payload["research_kpi_eligible"] is False


def test_research_run_rejection_is_explicitly_not_a_valid_optimization_result() -> None:
    payload = _solution_validity_payload(
        solver_status="NO_VALID_INCUMBENT",
        feasible=False,
        trip_count_unserved=2,
        infeasibility_reasons=["strict coverage could not be satisfied"],
        solver_metadata={
            "research_run": True,
            "research_run_accepted": False,
            "research_acceptance_checks": {"all_trips_served": False},
        },
    )

    assert payload["result_class"] == "research_invalid"
    assert "research_acceptance_failed" in payload["blocking_reasons"]
    assert payload["research_kpi_eligible"] is False


def test_phase3_research_run_is_feasibility_valid_but_not_cost_kpi_eligible() -> None:
    payload = _solution_validity_payload(
        solver_status="OPTIMAL",
        feasible=True,
        trip_count_unserved=0,
        infeasibility_reasons=[],
        solver_metadata={
            "research_run": True,
            "research_run_accepted": True,
            "research_feasibility_eligible": True,
            "research_cost_kpi_eligible": False,
            "phase": "phase3_two_stage",
        },
    )

    assert payload["validated_feasible"] is True
    assert payload["research_feasibility_eligible"] is True
    assert payload["research_kpi_eligible"] is False
