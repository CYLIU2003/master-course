from __future__ import annotations

from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargerDefinition,
    ChargingSlot,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
    ProblemVehicle,
)


def test_feasible_requires_energy_contract_and_charger_metrics_clean() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(vehicle_id="v1", vehicle_type="BEV", home_depot_id="dep", battery_capacity_kwh=100.0),
            ProblemVehicle(vehicle_id="v2", vehicle_type="BEV", home_depot_id="dep", battery_capacity_kwh=100.0),
        ),
        depots=(ProblemDepot(depot_id="dep", name="Depot", import_limit_kw=1.0),),
        chargers=(ChargerDefinition(charger_id="c1", depot_id="dep", power_kw=50.0, simultaneous_ports=1),),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        depot_energy_assets={
            "dep": DepotEnergyAsset(
                depot_id="dep",
                bess_enabled=True,
                bess_energy_kwh=10.0,
                bess_power_kw=10.0,
                bess_initial_soc_kwh=0.0,
                bess_soc_min_kwh=0.0,
                bess_soc_max_kwh=10.0,
                bess_discharge_efficiency=1.0,
                bess_terminal_soc_min_kwh=1.0,
            )
        },
    )
    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(vehicle_id="v1", slot_index=0, charger_id="grid:dep", charge_kw=10.0, charging_depot_id="dep"),
            ChargingSlot(vehicle_id="v2", slot_index=0, charger_id="grid:dep", charge_kw=10.0, charging_depot_id="dep"),
        ),
        grid_to_bus_kwh_by_depot_slot={"dep": {0: 10.0}},
        bess_to_bus_kwh_by_depot_slot={"dep": {0: 2.0}},
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert report.feasible is False
    assert report.metrics["contract_power_violation_count"] == 1
    assert report.metrics["charger_concurrency_violation_count"] == 1
    assert report.metrics["bess_soc_violation_count"] > 0
    assert report.metrics["bess_terminal_soc_deviation_kwh"] > 0.0
