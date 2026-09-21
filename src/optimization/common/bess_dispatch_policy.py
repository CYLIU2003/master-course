"""Optional storage operated after direct PV supply to buses."""
from __future__ import annotations

import math

from src.optimization.common.problem import DepotEnergyAsset

PV_BUS_FIRST_MODE = "pv_self_consumption"
PV_BUS_FIRST_POLICY = "pv_bus_first_surplus_storage_v1"


def uses_auxiliary_bess(asset: DepotEnergyAsset) -> bool:
    return asset.bess_priority_mode == PV_BUS_FIRST_MODE


def validate_auxiliary_bess(asset: DepotEnergyAsset) -> None:
    """Reject conflicting restoration/source controls instead of ignoring them."""
    if not uses_auxiliary_bess(asset) or not asset.bess_enabled:
        return
    values = (asset.bess_energy_kwh, asset.bess_power_kw, asset.bess_soc_min_kwh,
              asset.bess_soc_max_kwh, asset.bess_initial_soc_kwh,
              asset.bess_charge_efficiency, asset.bess_discharge_efficiency,
              asset.bess_terminal_soc_min_kwh, asset.bess_terminal_soc_target_kwh)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Auxiliary BESS parameters must be finite")
    if not (0 <= asset.bess_soc_min_kwh <= asset.bess_initial_soc_kwh
            <= asset.bess_soc_max_kwh <= asset.bess_energy_kwh
            and asset.bess_power_kw >= 0
            and 0 < asset.bess_charge_efficiency <= 1
            and 0 < asset.bess_discharge_efficiency <= 1):
        raise ValueError("Auxiliary BESS requires consistent SOC, power and efficiency")
    if (asset.allow_grid_to_bess or asset.bess_terminal_soc_target_kwh != 0
            or asset.bess_terminal_soc_policy not in ("", "minimum_only")
            or asset.bess_terminal_soc_min_kwh > asset.bess_soc_min_kwh):
        raise ValueError("Auxiliary BESS uses surplus PV only and no added reserve/restoration")


def auxiliary_bess_flows(asset: DepotEnergyAsset, *, demand_kwh: float,
                         pv_kwh: float, soc_kwh: float, duration_hours: float) -> dict[str, float]:
    """Use current observations only; saturate actions before a bound is crossed."""
    validate_auxiliary_bess(asset)
    if not all(math.isfinite(v) and v >= 0 for v in (demand_kwh, pv_kwh, soc_kwh)):
        raise ValueError("Auxiliary BESS observations must be finite and nonnegative")
    if not math.isfinite(duration_hours) or duration_hours <= 0:
        raise ValueError("Auxiliary BESS duration must be positive")
    direct = min(pv_kwh, demand_kwh)
    remaining, surplus = demand_kwh-direct, pv_kwh-direct
    charge = discharge = 0.0
    if asset.bess_enabled:
        lower, upper = asset.bess_soc_min_kwh, asset.bess_soc_max_kwh
        if not lower-1e-6 <= soc_kwh <= upper+1e-6:
            raise ValueError("Observed auxiliary BESS SOC is outside configured bounds")
        power = asset.bess_power_kw*duration_hours
        if asset.allow_bess_to_bus:
            discharge = min(remaining, power, max(soc_kwh-lower, 0)*asset.bess_discharge_efficiency)
        if asset.allow_pv_to_bess:
            charge = min(surplus, power, max(upper-soc_kwh, 0)/asset.bess_charge_efficiency)
        soc_kwh += charge*asset.bess_charge_efficiency-discharge/asset.bess_discharge_efficiency
    return {"grid_to_bus_kwh":remaining-discharge, "pv_to_bus_kwh":direct,
            "bess_to_bus_kwh":discharge, "pv_to_bess_kwh":charge, "grid_to_bess_kwh":0.0,
            "pv_curtail_kwh":surplus-charge, "bess_soc_kwh":soc_kwh}
