"""The authorized storage policy may consume inventory but keeps physical limits."""
from dataclasses import fields, replace
import json
from pathlib import Path

import pytest

from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import apply_seasonal_bess_policy
from scripts.benchmarks.seasonal_design_contract import seasonal_bess_controls
from src.gurobi_runtime import ensure_gurobi, is_gurobi_available
from src.optimization.common.bess_reserve_policy import (
    bess_reserve_targets, freeze_bess_terminal_soc_targets,
)
from src.optimization.common.bess_terminal_policy import resolve_bess_terminal_soc_target_kwh
from src.optimization.common.problem import DepotEnergyAsset, OptimizationConfig
from src.optimization.milp.solver_adapter import GurobiMILPAdapter
from src.optimization.rolling.pv_execution import IssuedEnergyCommand, execute_energy_slot
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.optimization.rolling.vehicle_execution import vehicle_positions_at
from test_monthly_bess_revision import _parent_asset
from test_rolling_bess_boundary_policy import _boundary_problem, _CaptureEngine
from test_rolling_pv_execution_reserve import _config
from test_weather_coupled_assignment import _problem as recourse_problem


DESIGN = Path(__file__).resolve().parents[1] / "config/shibu21_23_bess_operating_range_20260921.json"


def _design():
    return json.loads(DESIGN.read_text(encoding="utf-8"))


def test_prepared_policy_consumes_inventory_without_changing_equipment():
    parent = _parent_asset()
    configured = apply_seasonal_bess_policy(parent, design=_design())
    for key in ("bess_energy_kwh", "bess_power_kw", "bess_initial_soc_kwh",
                "bess_charge_efficiency", "bess_discharge_efficiency", "allow_grid_to_bess"):
        assert configured[key] == parent[key]
    assert (configured["bess_soc_min_kwh"], configured["bess_soc_max_kwh"]) == (1200, 4800)
    assert configured["bess_terminal_soc_min_kwh"] == 1200
    assert resolve_bess_terminal_soc_target_kwh(
        policy=configured["bess_terminal_soc_policy"], initial_soc_kwh=3000,
        configured_target_kwh=configured["bess_terminal_soc_target_kwh"],
        terminal_soc_floor_kwh=1200, maximum_soc_kwh=4800,
    ) is None
    controls = seasonal_bess_controls(_design())
    assert controls["rolling_bess_terminal_policy"] == "minimum_only"
    assert controls["bess_forecast_reserve_policy"] == "physical_floor_only"


@pytest.mark.parametrize("current_min", [0, 1440])
def test_rolling_has_no_storage_reference_or_restoration_but_keeps_bus_target(current_min):
    problem, plan, depot = _boundary_problem(physical_floor=1200)
    controls = seasonal_bess_controls(_design())
    configured = apply_seasonal_bess_policy(_parent_asset(), design=_design())
    asset_fields = {field.name for field in fields(DepotEnergyAsset)} - {"depot_id"}
    asset = replace(problem.depot_energy_assets[depot],
                    **{key: value for key, value in configured.items() if key in asset_fields})
    problem = replace(problem, depot_energy_assets={depot: asset},
                      metadata={**problem.metadata, **controls})
    plan = replace(plan, bess_soc_kwh_by_depot_slot={})
    frozen = freeze_bess_terminal_soc_targets(problem)
    assert bess_reserve_targets(frozen) == {}
    assert "bess_terminal_soc_target_kwh_by_depot" not in frozen.metadata
    rolling = RollingReoptimizer()
    capture = _CaptureEngine()
    rolling._engine = capture
    assert rolling.reoptimize_charging_hour(
        problem, plan, OptimizationConfig(), current_min, lookahead_hours=24,
        actual_bess_soc_kwh={depot: 1200},
        actual_soc={"bev-1": 80.0}, actual_vehicle_fuel_l={},
        actual_vehicle_positions=vehicle_positions_at(problem, plan, current_min),
        observed_on_peak_kw_by_depot={depot: 0.0},
        observed_off_peak_kw_by_depot={depot: 0.0},
        bess_terminal_policy=controls["rolling_bess_terminal_policy"],
    ) == {"ok": True}
    actual = capture.problem.depot_energy_assets[depot]
    assert actual.bess_initial_soc_kwh == 1200
    assert actual.bess_terminal_soc_policy == "minimum_only"
    assert actual.bess_terminal_soc_target_kwh == 0
    assert actual.bess_terminal_soc_min_kwh == 1200
    assert capture.problem.metadata["bev_terminal_soc_target_kwh_by_vehicle"]["bev-1"] > 0


def test_empty_storage_idles_and_full_storage_curtails_excess_pv():
    asset = DepotEnergyAsset(
        depot_id="DEPOT", pv_enabled=True, bess_enabled=True,
        bess_energy_kwh=100, bess_power_kw=100, bess_initial_soc_kwh=50,
        bess_soc_min_kwh=20, bess_soc_max_kwh=80,
        bess_charge_efficiency=.9, bess_discharge_efficiency=.8,
        allow_grid_to_bess=False, allow_bess_to_bus=True, allow_pv_to_bess=True,
        bess_terminal_soc_policy="minimum_only", bess_terminal_soc_min_kwh=20,
    )
    def execute(command, soc, pv):
        return execute_energy_slot(
            asset, command, actual_pv_kwh=pv, initial_bess_soc_kwh=soc,
            timestep_minutes=60, import_limit_kw=100, allow_contract_overage=False,
            slot_index=0, grid_price_yen_per_kwh=20,
        )
    depleted = execute(IssuedEnergyCommand(24, bess_to_bus_kwh=24), 50, 0)
    assert depleted.bess_soc_kwh == pytest.approx(20)
    idle = execute(IssuedEnergyCommand(10), depleted.bess_soc_kwh, 0)
    assert idle.bess_soc_kwh == pytest.approx(20)
    assert idle.bess_to_bus_kwh == 0 and idle.grid_to_bus_kwh == 10
    full = execute(IssuedEnergyCommand(10), 80, 50)
    assert full.bess_soc_kwh == 80
    assert full.pv_to_bess_kwh == 0 and full.pv_curtail_kwh == 40
    with pytest.raises(ValueError, match="SOC bounds"):
        execute(IssuedEnergyCommand(1, bess_to_bus_kwh=1), 20, 0)


@pytest.mark.skipif(not is_gurobi_available(), reason="Native Gurobi required")
def test_stage1_can_use_initial_inventory_without_later_pv_or_restoration():
    asset = DepotEnergyAsset(
        depot_id="tsurumaki", pv_enabled=True, pv_generation_kwh_by_slot=(0., 0.),
        bess_enabled=True, bess_energy_kwh=100, bess_power_kw=100,
        bess_initial_soc_kwh=50, bess_soc_min_kwh=20, bess_soc_max_kwh=80,
        bess_charge_efficiency=1, bess_discharge_efficiency=1,
        bess_balance_period="evaluation_period", bess_terminal_soc_min_kwh=20,
        bess_terminal_soc_policy="minimum_only", allow_grid_to_bess=False,
        allow_pv_to_bess=True, allow_bess_to_bus=True,
    )
    problem = recourse_problem(pv_kwh_by_slot=(0., 0.), grid_prices=(10., 10.),
                               asset=asset, enable_contract_overage_penalty=True)
    problem = replace(problem, metadata={**problem.metadata, **seasonal_bess_controls(_design())})
    problem = freeze_bess_terminal_soc_targets(problem)
    gp, grb = ensure_gurobi()
    model = gp.Model("bess_operating_range_regression")
    model.Params.OutputFlag = 0
    try:
        charges = {("bev", s): model.addVar(lb=value, ub=value)
                   for s, value in enumerate((10., 0.))}
        recourse = GurobiMILPAdapter()._add_stage1_time_indexed_energy_recourse_relaxation(
            model, gp=gp, grb=grb, problem=problem, component_flags={},
            config=_config(execution_minutes=60),
            recourse_state={"slot_indices": (0, 1), "timestep_h": 1.,
                            "charge_power_by_vehicle_slot": charges,
                            "electric_vehicle_by_id": {"bev": problem.vehicles[0]}},
        )
        model.setObjective(recourse.objective_expression, grb.MINIMIZE)
        model.optimize()
        assert model.Status == grb.OPTIMAL
        assert recourse.grid_to_bus_by_depot_slot[("tsurumaki", 0)].X == pytest.approx(0)
        assert not recourse.configuration["bess_planning_reserve"]["enabled"]
    finally:
        model.dispose()
