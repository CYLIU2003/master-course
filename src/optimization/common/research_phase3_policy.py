"""Explicit research-only Phase 3 scheduling guards.

Phase 3 fixes the Stage 1 vehicle-duty decision before Stage 2 evaluates its
charging and SOC feasibility.  A disconnected second duty fragment would need
an explicitly modelled return/departure movement and SOC transition between the
two fragments.  Until that extension exists, a research result must use one
continuous duty per vehicle rather than silently treating a reset as free.
"""

from __future__ import annotations

from typing import Any


RESEARCH_PHASE3_FRAGMENT_POLICY = "single_continuous_duty"

_EFFECTIVE_FRAGMENT_SETTINGS: dict[str, Any] = {
    "allow_same_day_depot_cycles": False,
    "max_depot_cycles_per_vehicle_per_day": 1,
    "max_start_fragments_per_vehicle": 1,
    "max_end_fragments_per_vehicle": 1,
}


def enforce_research_phase3_single_continuous_duty(
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Apply a disclosed, in-memory-only single-duty policy.

    The source scenario is already materialized by the research runners.  This
    function intentionally mutates only that ephemeral mapping; it never
    writes a scenario document back to the BFF store.
    """
    simulation_config = scenario.get("simulation_config")
    if not isinstance(simulation_config, dict):
        simulation_config = {}
        scenario["simulation_config"] = simulation_config

    scenario_overlay = scenario.get("scenario_overlay")
    if not isinstance(scenario_overlay, dict):
        scenario_overlay = {}
        scenario["scenario_overlay"] = scenario_overlay
    solver_config = scenario_overlay.get("solver_config")
    if not isinstance(solver_config, dict):
        solver_config = {}
        scenario_overlay["solver_config"] = solver_config

    requested_simulation_config = {
        key: simulation_config.get(key) for key in _EFFECTIVE_FRAGMENT_SETTINGS
    }
    requested_solver_config = {
        key: solver_config.get(key) for key in _EFFECTIVE_FRAGMENT_SETTINGS
    }
    simulation_config.update(_EFFECTIVE_FRAGMENT_SETTINGS)
    solver_config.update(_EFFECTIVE_FRAGMENT_SETTINGS)
    simulation_config["research_phase3_fragment_policy"] = (
        RESEARCH_PHASE3_FRAGMENT_POLICY
    )

    return {
        "policy": RESEARCH_PHASE3_FRAGMENT_POLICY,
        "reason": (
            "Stage 2 does not yet model SOC and repositioning across "
            "disconnected duty fragments."
        ),
        "persisted_to_scenario_store": False,
        "requested_simulation_config": requested_simulation_config,
        "requested_solver_config": requested_solver_config,
        "effective": {
            **_EFFECTIVE_FRAGMENT_SETTINGS,
            "daily_fragment_limit": 1,
        },
    }
