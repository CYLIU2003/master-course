from __future__ import annotations

from src.data_schema import ElectricityPrice, ProblemData, Site, Task, Vehicle
from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.milp_model import MILPResult
from src.model_sets import build_model_sets
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    EnergyPriceSlot,
    OptimizationObjectiveWeights,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.parameter_builder import build_derived_params
from src.simulator import simulate


def test_simulator_counts_bev_operating_energy_without_charge_costing() -> None:
    data = ProblemData(
        vehicles=[
            Vehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot="dep-1",
                battery_capacity=200.0,
                soc_init=100.0,
                soc_min=20.0,
            )
        ],
        tasks=[
            Task(
                task_id="trip-1",
                start_time_idx=0,
                end_time_idx=1,
                origin="A",
                destination="B",
                energy_required_kwh_bev=20.0,
                required_vehicle_type="BEV",
            )
        ],
        sites=[Site(site_id="dep-1", site_type="depot", grid_import_limit_kw=9999.0)],
        electricity_prices=[
            ElectricityPrice(site_id="dep-1", time_idx=0, grid_energy_price=10.0, co2_factor=0.5),
            ElectricityPrice(site_id="dep-1", time_idx=1, grid_energy_price=20.0, co2_factor=0.5),
        ],
        num_periods=2,
        delta_t_hour=1.0,
        enable_demand_charge=True,
        demand_charge_rate_per_kw=100.0,
    )
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)
    result = MILPResult(
        status="OPTIMAL",
        assignment={"bev-1": ["trip-1"]},
        soc_series={"bev-1": [100.0, 90.0, 80.0]},
        # Charging-related series should not drive electricity cost anymore.
        grid_import_kw={"dep-1": [50.0, 50.0]},
        peak_demand_kw={"dep-1": 50.0},
    )

    sim = simulate(data, ms, dp, result)

    assert sim.total_energy_cost == 300.0
    assert sim.total_demand_charge == 1000.0
    assert sim.total_grid_kwh == 20.0
    assert sim.peak_demand_kw == 10.0
    assert sim.grid_import_kw_series["dep-1"] == [10.0, 10.0]
    assert sim.total_co2_kg == 10.0


def test_cost_evaluator_counts_bev_trip_energy_without_charging_slots() -> None:
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
        duty_id="duty-1",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip),),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-1",
            horizon_start="08:00",
            timestep_min=60,
            objective_mode="total_cost",
            demand_charge_on_peak_yen_per_kw=100.0,
            demand_charge_off_peak_yen_per_kw=0.0,
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
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=200.0,
                fixed_use_cost_jpy=500.0,
            ),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0, demand_charge_weight=1.0, co2_factor=0.5),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0, demand_charge_weight=0.0, co2_factor=0.5),
        ),
        objective_weights=OptimizationObjectiveWeights(
            energy=1.0,
            demand=1.0,
            vehicle=1.0,
            unserved=10000.0,
        ),
    )
    plan = AssignmentPlan(
        duties=(duty,),
        served_trip_ids=("trip-1",),
    )

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert breakdown.energy_cost == 300.0
    assert breakdown.demand_cost == 1000.0
    assert breakdown.total_co2_kg == 10.0
    assert breakdown.total_cost >= 1800.0
