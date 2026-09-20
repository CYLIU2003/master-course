"""Explicit forecast-error protection for PV-only, cyclic stationary storage."""
from __future__ import annotations

import math
from typing import Mapping

from .problem import CanonicalOptimizationProblem

POLICY_KEY = "bess_forecast_reserve_policy"
PHYSICAL_FLOOR_ONLY = "physical_floor_only"
EVALUATION_TARGET_ZERO_PV = "evaluation_target_zero_pv"


def bess_reserve_policy(problem: CanonicalOptimizationProblem) -> str:
    """Reject conflicting declarations instead of silently dropping protection."""
    contract = problem.metadata.get("date_series_contract") or {}
    policy = problem.metadata.get(POLICY_KEY, contract.get(POLICY_KEY, PHYSICAL_FLOOR_ONLY))
    if policy not in (PHYSICAL_FLOOR_ONLY, EVALUATION_TARGET_ZERO_PV):
        raise ValueError(f"Unsupported {POLICY_KEY}: {policy}")
    if POLICY_KEY in contract and contract[POLICY_KEY] != policy:
        raise ValueError("BESS reserve policy differs from the date-series contract")
    return policy


def bess_reserve_targets(problem: CanonicalOptimizationProblem) -> dict[str, float]:
    """Read original evaluation targets, never the measured rolling initial SOC.

    This policy covers uncertain nonnegative PV, unrestricted paid grid supply
    to buses, and PV-only BESS charging. Intermediate windows return to the same
    evaluation target, so their feasible continuation does not depend on a
    day-ahead forecast BESS boundary. Hardware bounds remain separate.
    """
    if bess_reserve_policy(problem) == PHYSICAL_FLOOR_ONLY:
        return {}
    contract = problem.metadata.get("date_series_contract") or {}
    if contract.get("pv_information_mode") != "training_only_forecast_proxy":
        raise ValueError("BESS reserve requires the forecast/actual PV contract")
    if problem.metadata.get("enable_contract_overage_penalty") is not True:
        raise ValueError("BESS reserve requires declared paid grid overage for bus supply")
    frozen = problem.metadata.get("bess_terminal_soc_target_kwh_by_depot")
    if not isinstance(frozen, Mapping):
        raise ValueError("BESS reserve requires frozen evaluation targets before state updates")
    targets = {}
    for depot_id, asset in problem.depot_energy_assets.items():
        if not asset.bess_enabled:
            continue
        if (asset.bess_balance_period != "evaluation_period" or asset.allow_grid_to_bess
                or not asset.allow_bess_to_bus or not asset.allow_pv_to_bess):
            raise ValueError("BESS reserve supports PV-only evaluation-period storage")
        raw = frozen.get(str(depot_id))
        if isinstance(raw, bool) or raw is None:
            raise ValueError(f"Missing frozen BESS reserve target for {depot_id}")
        target = float(raw)
        if (not math.isfinite(target)
                or not asset.bess_soc_min_kwh <= target <= asset.bess_soc_max_kwh):
            raise ValueError(f"Invalid frozen BESS reserve target for {depot_id}")
        if any(float(value) != 0.0 for value in asset.depot_load_kwh_by_slot):
            raise ValueError("BESS reserve requires explicit zero nontraction depot load")
        targets[str(depot_id)] = target
    return targets
