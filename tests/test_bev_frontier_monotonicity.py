from src.optimization.milp.solver_adapter import (
    audit_bev_frontier_monotonicity,
    classify_bev_frontier_status,
)


def test_bev_frontier_status_distinguishes_time_limit_incumbent() -> None:
    assert classify_bev_frontier_status("time_limit", 1) == (
        "TIME_LIMIT_WITH_INCUMBENT"
    )
    assert classify_bev_frontier_status("time_limit", 0) == (
        "TIME_LIMIT_NO_INCUMBENT"
    )
    assert classify_bev_frontier_status(
        "infeasible", 0, certificate_accepted=True
    ) == "CERTIFIED_INFEASIBLE"


def test_bev_frontier_monotonicity_reports_but_does_not_rewrite_costs() -> None:
    rows = [
        {
            "minimum_used_bev_count": 15,
            "stage2_actual_canonical_cost_jpy": 110.0,
            "physical_validation_feasible": True,
        },
        {
            "minimum_used_bev_count": 16,
            "stage2_actual_canonical_cost_jpy": 100.0,
            "physical_validation_feasible": True,
        },
    ]

    violations = audit_bev_frontier_monotonicity(rows)

    assert len(violations) == 1
    assert rows[0]["stage2_actual_canonical_cost_jpy"] == 110.0
    assert rows[1]["stage2_actual_canonical_cost_jpy"] == 100.0
