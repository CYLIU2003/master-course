from __future__ import annotations

import pytest

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
)


def _scenario() -> OptimizationScenario:
    return OptimizationScenario(scenario_id="s", timestep_min=60)


def test_depot_energy_asset_allows_empty_mapping() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=_scenario(),
        dispatch_context=None,
        trips=(),
        vehicles=(),
    )
    assert problem.depot_energy_assets == {}


def test_depot_energy_asset_rejects_pv_slot_length_mismatch() -> None:
    with pytest.raises(ValueError, match="pv_generation_kwh_by_slot length"):
        CanonicalOptimizationProblem(
            scenario=_scenario(),
            dispatch_context=None,
            trips=(),
            vehicles=(),
            price_slots=(
                EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),
                EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0),
            ),
            depot_energy_assets={
                "dep-1": DepotEnergyAsset(
                    depot_id="dep-1",
                    pv_enabled=True,
                    pv_generation_kwh_by_slot=(1.0,),
                )
            },
        )


def test_depot_energy_asset_rejects_invalid_initial_soc_bounds() -> None:
    with pytest.raises(ValueError, match="initial BESS SOC"):
        CanonicalOptimizationProblem(
            scenario=_scenario(),
            dispatch_context=None,
            trips=(),
            vehicles=(),
            depot_energy_assets={
                "dep-1": DepotEnergyAsset(
                    depot_id="dep-1",
                    bess_enabled=True,
                    bess_soc_min_kwh=20.0,
                    bess_soc_max_kwh=100.0,
                    bess_initial_soc_kwh=120.0,
                )
            },
        )
