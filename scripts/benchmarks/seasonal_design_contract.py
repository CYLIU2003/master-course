"""Pure validation of seasonal design controls; never prepares or solves a case."""

from __future__ import annotations

import math


def seasonal_bess_controls(design: dict | None = None) -> dict:
    """Resolve supported BESS controls without silently replacing declarations.

    Legacy designs keep their 20%-80%, evaluation-period, minimum-only policy.
    An inventory-neutral design must retain the scenario target in rolling.
    Other operating ranges require a separately reviewed experiment design.
    """
    source = design or {}
    controls = {
        "bess_balance_period": source.get("bess_balance_period", "evaluation_period"),
        "bess_terminal_soc_policy": source.get("bess_terminal_soc_policy", "minimum_only"),
        "bess_terminal_soc_floor_percent": float(source.get("bess_terminal_soc_floor_percent", 20.0)),
        "rolling_bess_terminal_policy": source.get("rolling_bess_terminal_policy", "minimum_only"),
        "bess_forecast_reserve_policy": source.get("bess_forecast_reserve_policy", "physical_floor_only"),
    }
    if controls["bess_balance_period"] != "evaluation_period":
        raise ValueError("Seasonal design requires bess_balance_period=evaluation_period")
    floor = controls["bess_terminal_soc_floor_percent"]
    if not math.isfinite(floor) or floor != 20.0:
        raise ValueError("Seasonal design supports only the declared 20%-80% BESS range")
    policy = controls["bess_terminal_soc_policy"]
    if policy not in ("minimum_only", "return_to_initial"):
        raise ValueError("Seasonal BESS terminal policy must be minimum_only or return_to_initial")
    rolling = controls["rolling_bess_terminal_policy"]
    if rolling not in ("scenario", "minimum_only"):
        raise ValueError("Seasonal rolling BESS policy must be scenario or minimum_only")
    if policy == "return_to_initial" and rolling != "scenario":
        raise ValueError("return_to_initial requires rolling BESS policy=scenario to retain its target")
    reserve = controls["bess_forecast_reserve_policy"]
    if reserve not in ("physical_floor_only", "evaluation_target_zero_pv", "evaluation_target_every_prefix"):
        raise ValueError("Unsupported seasonal BESS forecast reserve policy")
    if reserve != "physical_floor_only" and (policy != "return_to_initial" or rolling != "scenario"):
        raise ValueError("BESS forecast reserve requires the retained evaluation return_to_initial target")
    return controls


def require_execution_enabled(design: dict) -> None:
    """Enforce an explicit draft hold before any campaign/solve side effects."""
    enabled = design.get("execution_enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("execution_enabled must be a JSON boolean")
    if not enabled:
        raise RuntimeError("EXECUTION_DISABLED: this design is held for editing; simulation is not authorized")
