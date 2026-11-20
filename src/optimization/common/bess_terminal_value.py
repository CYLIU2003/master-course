"""Value of the stationary-battery energy left at the end of a planning window.

The objective adds ``v * (E_start - E_end)`` per depot, where ``E_start`` is
the window's initial BESS inventory (the measured state in a rolling window)
and ``E_end`` the inventory after the last slot. A drawdown therefore costs
``v`` per kWh and a gain is credited at the same price. With ``v`` equal to the
grid energy price, discharging only pays when free PV that would otherwise be
curtailed refills the battery before the window ends.

The term is a planning price for inventory, not purchased energy. Solvers
remove it from the reported Stage 2 energy objective, and the canonical
ledger never contains it.
"""
from __future__ import annotations

import math
from typing import Any

from .bess_dispatch_policy import uses_auxiliary_bess
from .problem import DepotEnergyAsset

FIELD = "bess_terminal_energy_value_yen_per_kwh"


def terminal_energy_value(asset: DepotEnergyAsset) -> float:
    """Return the validated price; reject settings that would be ignored."""
    value = float(getattr(asset, FIELD, 0.0) or 0.0)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{FIELD} must be finite and nonnegative")
    if value > 0.0 and not asset.bess_enabled:
        raise ValueError(f"{FIELD} requires an enabled BESS")
    if value > 0.0 and uses_auxiliary_bess(asset):
        raise ValueError(f"{FIELD} applies to an optimized BESS, not the pv_self_consumption rule")
    return value


def terminal_value_term(asset: DepotEnergyAsset, terminal_soc_expr: Any) -> Any:
    """Objective term v * (E_start - E_end); 0.0 when the price is zero."""
    value = terminal_energy_value(asset)
    if value == 0.0:
        return 0.0
    return value * (float(asset.bess_initial_soc_kwh or 0.0) - terminal_soc_expr)
