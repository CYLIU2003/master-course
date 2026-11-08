"""Planning-only PV forecast margin (pillar A, 2026-11-08).

The day-ahead plan and every rolling step plan against a PV forecast; the
executed hours always use the measured PV (``pv_actuals_json`` in the rolling
chain), which this module never touches. A planning scale ``s`` in (0, 1]
multiplies the forecast PV the optimizer sees, so a plan that depends on sunny
weather is priced as if only ``s`` of the forecast arrives. The day-ahead
problem carries the scaled profile into ``effective_pv_profiles.json``, which
the rolling chain loads, so day-ahead and rolling plan with the same forecast.

Why: in rc33 90 kW winter the forecast was a near-flat ~3,400 kWh/day while the
measured PV was 41 % of it on the first day; the day-ahead plan expected no
contract overage and the executed week had 1,291 kWh of it.
"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

PLANNING_PV_FORECAST_SCALE_KEY = "planning_pv_forecast_scale"


def validate_planning_pv_forecast_scale(scale: Any) -> float:
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise ValueError("planning_pv_forecast_scale must be a number in (0, 1]")
    value = float(scale)
    if not math.isfinite(value) or not 0.0 < value <= 1.0:
        raise ValueError("planning_pv_forecast_scale must be a number in (0, 1]")
    return value


def apply_planning_pv_forecast_scale(problem: Any, scale: Any) -> Any:
    """Return the problem with its forecast PV multiplied by ``scale``.

    Only the forecast fields the optimizer reads are scaled (per-depot
    ``pv_generation_kwh_by_slot`` and ``available_pv_surplus_kwh_by_slot`` and the
    aggregate ``pv_slots``); capacities, assets and the measured PV are unchanged.
    The scale is recorded in the problem metadata in every case.
    """
    value = validate_planning_pv_forecast_scale(scale)
    metadata = dict(getattr(problem, "metadata", {}) or {})
    metadata[PLANNING_PV_FORECAST_SCALE_KEY] = value
    metadata["planning_pv_forecast_scale_semantics"] = (
        "planning_only_forecast_multiplier; executed hours use measured PV"
    )
    if value == 1.0:
        return replace(problem, metadata=metadata)
    assets = {
        depot_id: replace(
            asset,
            pv_generation_kwh_by_slot=tuple(
                float(v or 0.0) * value for v in tuple(asset.pv_generation_kwh_by_slot or ())
            ),
            available_pv_surplus_kwh_by_slot=tuple(
                float(v or 0.0) * value for v in tuple(asset.available_pv_surplus_kwh_by_slot or ())
            ),
        )
        for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
    }
    pv_slots = tuple(
        replace(slot, pv_available_kw=float(slot.pv_available_kw or 0.0) * value)
        for slot in tuple(problem.pv_slots or ())
    )
    return replace(problem, depot_energy_assets=assets, pv_slots=pv_slots, metadata=metadata)
