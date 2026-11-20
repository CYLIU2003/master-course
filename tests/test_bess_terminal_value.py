"""Pillar B: the BESS energy left at the window end is priced (2026-11-20)."""
from dataclasses import replace

import pytest

from src.optimization.common.bess_terminal_value import terminal_energy_value
from src.optimization.common.problem import DepotEnergyAsset, OptimizationConfig, OptimizationMode


def _solve(*, value: float, extra_pv_kwh: float, initial_kwh: float = 50.0):
    pytest.importorskip("gurobipy")
    from scripts.benchmarks.run_daily_assignment_reference import assignment_plan, build_example
    from src.optimization.engine import OptimizationEngine

    problem = build_example(extra_pv_kwh=extra_pv_kwh)
    storage = replace(problem.depot_energy_assets["DEPOT"], bess_priority_mode="cost_driven",
                      bess_terminal_energy_value_yen_per_kwh=value,
                      bess_initial_soc_kwh=initial_kwh)
    problem = replace(problem, depot_energy_assets={"DEPOT": storage})
    result = OptimizationEngine().solve(problem, OptimizationConfig(
        mode=OptimizationMode.MILP, phase="phase1_charging_only",
        fixed_assignment=assignment_plan(problem, ("bev-0", "bev-0")),
        time_limit_sec=20, stage2_time_limit_sec=15, mip_gap=0, gurobi_threads=1,
        allow_postsolve_repair=False))
    assert result.feasible, result.infeasibility_reasons
    soc = result.plan.bess_soc_kwh_by_depot_slot["DEPOT"]
    flows = {name: sum(getattr(result.plan, f"{name}_kwh_by_depot_slot").get("DEPOT", {}).values())
             for name in ("bess_to_bus", "pv_to_bess")}
    end_kwh = None
    audit = result.plan.metadata["stage2_bess_terminal_value_by_depot"].get("DEPOT")
    if audit is not None:
        end_kwh = audit["end_kwh"]
    else:  # unpriced: inventory after the last slot from the plan flows
        last = max(soc)
        end_kwh = (soc[last] + 0.95 * result.plan.pv_to_bess_kwh_by_depot_slot.get("DEPOT", {}).get(last, 0.0)
                   - result.plan.bess_to_bus_kwh_by_depot_slot.get("DEPOT", {}).get(last, 0.0) / 0.95)
    return result, end_kwh, flows, audit


def test_unpriced_storage_is_drawn_down_as_free_energy():
    _, end_kwh, flows, audit = _solve(value=0.0, extra_pv_kwh=0.0)
    assert audit is None
    assert flows["bess_to_bus"] > 1.0
    assert end_kwh < 50.0 - 1.0


def test_priced_storage_is_not_drawn_down_without_a_refill():
    result, end_kwh, flows, audit = _solve(value=30.0, extra_pv_kwh=0.0)
    assert flows["bess_to_bus"] == pytest.approx(0.0, abs=1e-6)
    assert end_kwh == pytest.approx(50.0, abs=1e-6)
    assert result.plan.metadata["stage2_bess_terminal_value_jpy"] == pytest.approx(0.0, abs=1e-6)


def test_priced_storage_discharges_when_surplus_pv_refills_it():
    # Full at the start: the noon PV could not be stored, so the battery first
    # serves the buses at night and is refilled by that PV (verified flows:
    # 5.4 kWh out at slots 2 and 27, 6 kWh in at slots 10 and 34).
    result, end_kwh, flows, audit = _solve(value=30.0, extra_pv_kwh=6.0, initial_kwh=80.0)
    assert flows["bess_to_bus"] > 1.0
    assert flows["pv_to_bess"] > 1.0
    assert end_kwh >= 80.0 - 1e-6
    # The inventory price is removed from the reported Stage 2 energy objective.
    assert audit["value_jpy"] == pytest.approx(30.0 * (80.0 - end_kwh), abs=1e-6)
    assert result.plan.metadata["stage2_bess_terminal_value_jpy"] == pytest.approx(audit["value_jpy"])


def test_price_is_rejected_where_it_would_be_ignored():
    base = dict(depot_id="DEPOT", pv_enabled=True, bess_enabled=True, bess_energy_kwh=100,
                bess_power_kw=60, bess_initial_soc_kwh=50, bess_soc_min_kwh=20, bess_soc_max_kwh=80,
                bess_terminal_soc_policy="minimum_only", bess_terminal_soc_min_kwh=20)
    assert terminal_energy_value(DepotEnergyAsset(**base, bess_terminal_energy_value_yen_per_kwh=17.43)) == 17.43
    with pytest.raises(ValueError):
        terminal_energy_value(DepotEnergyAsset(**base, bess_priority_mode="pv_self_consumption",
                                               bess_terminal_energy_value_yen_per_kwh=17.43))
    with pytest.raises(ValueError):
        terminal_energy_value(DepotEnergyAsset(**{**base, "bess_enabled": False},
                                               bess_terminal_energy_value_yen_per_kwh=17.43))
    with pytest.raises(ValueError):
        terminal_energy_value(DepotEnergyAsset(**base, bess_terminal_energy_value_yen_per_kwh=-1.0))


def test_optimized_design_reaches_the_prepared_asset_and_is_checked():
    from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import apply_seasonal_bess_policy
    from scripts.benchmarks.seasonal_design_contract import seasonal_bess_controls
    from tools.research.weekly_campaign import BESS_MODES

    parent = {"bess_energy_kwh": 6000.0, "bess_initial_soc_kwh": 3000.0, "allow_grid_to_bess": True,
              "bess_priority_mode": "pv_self_consumption"}
    design = {"bess_terminal_soc_policy": "minimum_only", "rolling_bess_terminal_policy": "minimum_only",
              "bess_forecast_reserve_policy": "physical_floor_only", **BESS_MODES["optimized"]}
    configured = apply_seasonal_bess_policy(parent, design=design)
    assert configured["bess_priority_mode"] == "cost_driven"
    assert configured["allow_grid_to_bess"] is False
    assert configured["bess_terminal_energy_value_yen_per_kwh"] == 17.43
    assert configured["bess_terminal_soc_policy"] == "minimum_only"
    assert parent["allow_grid_to_bess"] is True  # the parent asset is not modified
    assert apply_seasonal_bess_policy(parent, design={**design, **BESS_MODES["rule"],
                                                      "bess_priority_mode": "pv_self_consumption",
                                                      "bess_terminal_energy_value_yen_per_kwh": 0.0}
                                      )["allow_grid_to_bess"] is False
    with pytest.raises(ValueError):
        seasonal_bess_controls({**design, "bess_priority_mode": "pv_self_consumption"})
    with pytest.raises(ValueError):
        seasonal_bess_controls({**design, "bess_terminal_soc_policy": "return_to_initial",
                                "rolling_bess_terminal_policy": "scenario"})


def test_pv_cost_mode_prices_storage_at_the_pv_unit_cost():
    from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import apply_seasonal_bess_policy
    from scripts.benchmarks.seasonal_design_contract import seasonal_bess_controls
    from tools.research.weekly_campaign import BESS_MODES

    parent = {"bess_energy_kwh": 6000.0, "bess_initial_soc_kwh": 3000.0, "allow_grid_to_bess": True,
              "bess_priority_mode": "pv_self_consumption"}
    design = {"bess_terminal_soc_policy": "minimum_only", "rolling_bess_terminal_policy": "minimum_only",
              "bess_forecast_reserve_policy": "physical_floor_only", **BESS_MODES["optimized_pv_cost"]}
    seasonal_bess_controls(design)
    configured = apply_seasonal_bess_policy(parent, design=design)
    assert configured["bess_priority_mode"] == "cost_driven"
    assert configured["allow_grid_to_bess"] is False
    assert configured["bess_terminal_energy_value_yen_per_kwh"] == 0.0
