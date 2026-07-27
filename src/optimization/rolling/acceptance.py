"""Shared, fail-closed acceptance contract for a complete rolling chain."""

from __future__ import annotations

from typing import Any, Mapping


ROLLING_CHAIN_REQUIRED_ACCEPTANCE_CHECKS = frozenset(
    {
        "full_energy_horizon_requested",
        "all_steps_feasible",
        "expected_step_count_observed",
        "executed_day_accounting_eligible",
        "day_ahead_git_clean",
        "rolling_runner_git_clean",
        "day_ahead_and_rolling_git_sha_match",
        "day_ahead_assignment_hash_constant",
        "gurobi_available",
        "no_chain_runtime_error",
    }
)


def rolling_chain_acceptance_audit(
    chain_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate persisted rolling evidence without trusting its status flag.

    ``chain_accepted`` is a runner claim, not sufficient evidence on its own.
    Consumers independently require every named invariant so a truncated or
    manually edited JSON cannot become a research-ready execution record.
    """

    checks = dict(chain_summary.get("acceptance_checks") or {})
    missing = sorted(ROLLING_CHAIN_REQUIRED_ACCEPTANCE_CHECKS.difference(checks))
    failing = sorted(
        str(name) for name, value in checks.items() if value is not True
    )
    claimed_accepted = bool(chain_summary.get("chain_accepted"))
    accepted = bool(claimed_accepted and not missing and not failing)
    return {
        "accepted": accepted,
        "claimed_accepted": claimed_accepted,
        "acceptance_checks": checks,
        "missing_required_checks": missing,
        "failing_checks": failing,
    }
