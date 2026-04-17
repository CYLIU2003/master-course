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
    RefuelSlot,
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
    assert breakdown.provisional_ev_drive_cost == 240.0
    assert breakdown.realized_ev_charge_cost == 200.0
    assert breakdown.leftover_ev_provisional_cost == 120.0


def test_evaluator_keeps_ice_provisional_leftover_without_refuel() -> None:
    trip = Trip(
        trip_id="trip-ice-1",
        route_id="route-1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("ICE",),
    )
    duty = VehicleDuty(
        duty_id="milp_ice-1",
        vehicle_type="ICE",
        legs=(DutyLeg(trip=trip),),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-ice-1",
            horizon_start="08:00",
            timestep_min=60,
            objective_mode="total_cost",
            diesel_price_yen_per_l=160.0,
        ),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="trip-ice-1",
                route_id="route-1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=540,
                distance_km=10.0,
                allowed_vehicle_types=("ICE",),
                fuel_l=5.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="ice-1",
                vehicle_type="ICE",
                home_depot_id="dep-1",
                initial_fuel_l=100.0,
                fuel_tank_capacity_l=120.0,
                fuel_consumption_l_per_km=0.5,
            ),
        ),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        vehicle_types=(ProblemVehicleType(vehicle_type_id="ICE", powertrain_type="ICE"),),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        objective_weights=OptimizationObjectiveWeights(),
    )
    plan = AssignmentPlan(duties=(duty,), served_trip_ids=("trip-ice-1",))

    breakdown = CostEvaluator().evaluate(problem, plan)
    assert breakdown.provisional_ice_drive_cost == 800.0
    assert breakdown.realized_ice_refuel_cost == 0.0
    assert breakdown.leftover_ice_provisional_cost == 800.0


def test_evaluator_fallback_keeps_provisional_energy_without_fake_demand_charge() -> None:
    trip = Trip(
        trip_id="trip-fallback-1",
        route_id="route-1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    duty = VehicleDuty(
        duty_id="veh-1",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip),),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-fallback-1",
            horizon_start="08:00",
            timestep_min=60,
            objective_mode="total_cost",
            demand_charge_on_peak_yen_per_kw=1000.0,
            demand_charge_off_peak_yen_per_kw=1000.0,
        ),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="trip-fallback-1",
                route_id="route-1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=540,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=20.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=200.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=200.0,
            ),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=12.0),
        ),
        objective_weights=OptimizationObjectiveWeights(),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                pv_enabled=True,
                pv_generation_kwh_by_slot=(30.0,),
                provisional_energy_cost_yen_per_kwh=12.0,
            )
        },
    )
    plan = AssignmentPlan(duties=(duty,), served_trip_ids=("trip-fallback-1",))

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert breakdown.energy_cost == 240.0
    assert breakdown.demand_cost == 0.0
    assert breakdown.grid_purchase_cost == 0.0
    assert breakdown.realized_ev_charge_cost == 0.0
    assert breakdown.leftover_ev_provisional_cost == 240.0
    assert breakdown.grid_import_kwh == 0.0
    assert breakdown.peak_grid_kw == 0.0
    assert breakdown.pv_used_direct_kwh == 0.0
    assert breakdown.pv_curtailed_kwh == 30.0


def test_evaluator_overwrites_ice_provisional_with_refuel_event_cost() -> None:
    trip = Trip(
        trip_id="trip-ice-2",
        route_id="route-1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("ICE",),
    )
    duty = VehicleDuty(
        duty_id="milp_ice-2",
        vehicle_type="ICE",
        legs=(DutyLeg(trip=trip),),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-ice-2",
            horizon_start="08:00",
            timestep_min=60,
            objective_mode="total_cost",
            diesel_price_yen_per_l=170.0,
        ),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="trip-ice-2",
                route_id="route-1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=540,
                distance_km=10.0,
                allowed_vehicle_types=("ICE",),
                fuel_l=5.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="ice-2",
                vehicle_type="ICE",
                home_depot_id="dep-1",
                initial_fuel_l=100.0,
                fuel_tank_capacity_l=120.0,
                fuel_consumption_l_per_km=0.5,
            ),
        ),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        vehicle_types=(ProblemVehicleType(vehicle_type_id="ICE", powertrain_type="ICE"),),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        objective_weights=OptimizationObjectiveWeights(),
        metadata={
            "provisional_fuel_price_by_depot": {"dep-1": 160.0},
            "fuel_price_by_depot": {"dep-1": 200.0},
        },
    )
    plan = AssignmentPlan(
        duties=(duty,),
        refuel_slots=(
            # Refuel only 2L: partially overwrite 5L provisional debt.
            # final fuel = 5*160 - 2*160 + 2*200 = 880
            # leftover provisional = 3*160 = 480
            RefuelSlot(vehicle_id="ice-2", slot_index=0, refuel_liters=2.0, location_id="dep-1"),
        ),
        served_trip_ids=("trip-ice-2",),
    )

    breakdown = CostEvaluator().evaluate(problem, plan)
    assert breakdown.provisional_ice_drive_cost == 800.0
    assert breakdown.realized_ice_refuel_cost == 400.0
    assert breakdown.leftover_ice_provisional_cost == 480.0


def test_evaluator_separates_accounting_total_cost_from_return_leg_bonus() -> None:
    trips = (
        ProblemTrip(
            trip_id="trip-1",
            route_id="route-1",
            route_family_code="FAM-1",
            origin="Depot",
            destination="Terminal",
            departure_min=480,
            arrival_min=485,
            distance_km=0.0,
            allowed_vehicle_types=("BEV",),
            energy_kwh=0.0,
        ),
        ProblemTrip(
            trip_id="trip-2",
            route_id="route-1",
            route_family_code="FAM-1",
            origin="Terminal",
            destination="Depot",
            departure_min=486,
            arrival_min=491,
            distance_km=0.0,
            allowed_vehicle_types=("BEV",),
            energy_kwh=0.0,
        ),
        ProblemTrip(
            trip_id="trip-3",
            route_id="route-1",
            route_family_code="FAM-1",
            origin="Depot",
            destination="Terminal",
            departure_min=492,
            arrival_min=497,
            distance_km=0.0,
            allowed_vehicle_types=("BEV",),
            energy_kwh=0.0,
        ),
    )
    dispatch_trips = (
        Trip(
            trip_id="trip-1",
            route_id="route-1",
            route_family_code="FAM-1",
            origin="Depot",
            destination="Terminal",
            departure_time="08:00",
            arrival_time="08:05",
            distance_km=0.0,
            allowed_vehicle_types=("BEV",),
        ),
        Trip(
            trip_id="trip-2",
            route_id="route-1",
            route_family_code="FAM-1",
            origin="Terminal",
            destination="Depot",
            departure_time="08:06",
            arrival_time="08:11",
            distance_km=0.0,
            allowed_vehicle_types=("BEV",),
        ),
        Trip(
            trip_id="trip-3",
            route_id="route-1",
            route_family_code="FAM-1",
            origin="Depot",
            destination="Terminal",
            departure_time="08:12",
            arrival_time="08:17",
            distance_km=0.0,
            allowed_vehicle_types=("BEV",),
        ),
    )
    duty = VehicleDuty(
        duty_id="veh-1",
        vehicle_type="BEV",
        legs=tuple(DutyLeg(trip=trip) for trip in dispatch_trips),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-bonus-1",
            horizon_start="08:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=None,
        trips=trips,
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=200.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=200.0,
            ),
        ),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        objective_weights=OptimizationObjectiveWeights(return_leg_bonus=10.0),
    )
    plan = AssignmentPlan(duties=(duty,), served_trip_ids=("trip-1", "trip-2", "trip-3"))

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert breakdown.total_cost > 0.0
    assert breakdown.return_leg_bonus == 10000.0
    assert breakdown.objective_value < 0.0


def test_evaluator_total_cost_matches_objective_when_return_leg_bonus_disabled() -> None:
    trip = Trip(
        trip_id="trip-no-bonus-1",
        route_id="route-1",
        route_family_code="FAM-1",
        origin="Depot",
        destination="Terminal",
        departure_time="08:00",
        arrival_time="08:10",
        distance_km=0.0,
        allowed_vehicle_types=("BEV",),
    )
    duty = VehicleDuty(
        duty_id="veh-1",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip),),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-bonus-2",
            horizon_start="08:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="trip-no-bonus-1",
                route_id="route-1",
                route_family_code="FAM-1",
                origin="Depot",
                destination="Terminal",
                departure_min=480,
                arrival_min=490,
                distance_km=0.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=0.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=200.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=200.0,
            ),
        ),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        objective_weights=OptimizationObjectiveWeights(return_leg_bonus=0.0),
    )
    plan = AssignmentPlan(duties=(duty,), served_trip_ids=("trip-no-bonus-1",))

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert breakdown.return_leg_bonus == 0.0
    assert breakdown.total_cost == breakdown.objective_value
