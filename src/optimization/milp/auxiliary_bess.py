"""Encode the declared causal storage rule in forecast charging optimization."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.optimization.common.bess_dispatch_policy import uses_auxiliary_bess, validate_auxiliary_bess
from src.optimization.common.problem import DepotEnergyAsset


def add_auxiliary_bess_constraints(model: Any, asset: DepotEnergyAsset, slots: Sequence[int], *,
        duration_hours: float, grid_bus: Mapping, pv_bus: Mapping, bess_bus: Mapping,
        pv_charge: Mapping, grid_charge: Mapping, soc_start: Mapping) -> None:
    """Pin source flows to bus-first/min rules while optimizing bus charge timing.

    Existing source balances and BESS state transitions stay authoritative.
    Stage1 keeps its continuous energy relaxation; these exact rules belong
    to fixed-dispatch charging and the integrated charging formulation.
    """
    if not uses_auxiliary_bess(asset):
        return
    validate_auxiliary_bess(asset)
    for slot in slots:
        key = (asset.depot_id, slot)
        prefix = f"aux_bess__{asset.depot_id}__{slot}"
        pv = (max(float(asset.pv_generation_kwh_by_slot[slot]), 0.0)
              if asset.pv_enabled and slot < len(asset.pv_generation_kwh_by_slot) else 0.0)
        demand = model.addVar(lb=0.0, name=prefix+"__demand")
        model.addConstr(demand == grid_bus[key]+pv_bus[key]+bess_bus[key])
        model.addGenConstrMin(pv_bus[key], [demand], constant=pv, name=prefix+"__pv_first")
        model.addConstr(grid_charge[key] == 0.0, name=prefix+"__no_grid_charge")
        if not asset.bess_enabled:
            continue
        residual = model.addVar(lb=0.0, name=prefix+"__residual")
        surplus = model.addVar(lb=0.0, name=prefix+"__surplus")
        available = model.addVar(lb=0.0, name=prefix+"__available")
        headroom = model.addVar(lb=0.0, name=prefix+"__headroom")
        model.addConstr(residual == demand-pv_bus[key])
        model.addConstr(surplus == pv-pv_bus[key])
        model.addConstr(available == (soc_start[key]-asset.bess_soc_min_kwh)*asset.bess_discharge_efficiency)
        model.addConstr(headroom == (asset.bess_soc_max_kwh-soc_start[key])/asset.bess_charge_efficiency)
        power = asset.bess_power_kw*duration_hours
        model.addGenConstrMin(bess_bus[key], [residual, available],
                              constant=power if asset.allow_bess_to_bus else 0.0,
                              name=prefix+"__bounded_discharge")
        model.addGenConstrMin(pv_charge[key], [surplus, headroom],
                              constant=power if asset.allow_pv_to_bess else 0.0,
                              name=prefix+"__surplus_charge")
