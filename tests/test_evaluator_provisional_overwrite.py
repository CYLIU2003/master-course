from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationObjectiveWeights,
    OptimizationScenario,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)


def test_evaluator_applies_provisional_then_overwrites_with_charge_source_cost() -> None:
    trip = Trip(
        trip_id="trip-1",
        route_id="route-1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="10:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    duty = VehicleDuty(
        duty_id="milp_bev-1",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip),),
    )

    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-1",
            horizon_start="08:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="trip-1",
                route_id="route-1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=600,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=20.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=200.0,
            ),
        ),
        depots=(
            ProblemDepot(
                depot_id="dep-1",
                name="Depot",
                import_limit_kw=9999.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=200.0,
                fixed_use_cost_jpy=0.0,
            ),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0),
        ),
        objective_weights=OptimizationObjectiveWeights(),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                provisional_energy_cost_yen_per_kwh=12.0,
                bess_cycle_cost_yen_per_kwh=5.0,
            )
        },
    )

    plan = AssignmentPlan(
        duties=(duty,),
        charging_slots=(
            ChargingSlot(vehicle_id="bev-1", slot_index=1, charger_id="grid:dep-1", charge_kw=10.0),
        ),
        grid_to_bus_kwh_by_depot_slot={"dep-1": {1: 10.0}},
        bess_to_bus_kwh_by_depot_slot={"dep-1": {1: 0.0}},
        pv_to_bess_kwh_by_depot_slot={"dep-1": {1: 0.0}},
        grid_to_bess_kwh_by_depot_slot={"dep-1": {1: 0.0}},
        pv_curtail_kwh_by_depot_slot={"dep-1": {1: 0.0}},
        served_trip_ids=("trip-1",),
    )

    breakdown = CostEvaluator().evaluate(problem, plan)

    # provisional: 20kWh * 12 = 240
    # overwrite matched 10kWh: rollback 120, apply actual grid 10kWh * 20 = 200
    # final electricity = 240 - 120 + 200 = 320
    assert breakdown.electricity_cost_final == 320.0
    assert breakdown.electricity_cost_provisional_leftover == 120.0
    assert breakdown.grid_purchase_cost == 200.0
    assert breakdown.grid_to_bus_kwh == 10.0
