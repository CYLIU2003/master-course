from __future__ import annotations

from src.dispatch.models import DeadheadRule, DispatchContext, DutyLeg, Trip, VehicleDuty, VehicleProfile
from src.optimization.alns.operators_repair import _with_recomputed_charging
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    ChargerDefinition,
    ChargingSlot,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
    CanonicalOptimizationProblem,
)


def _dispatch_context() -> DispatchContext:
    return DispatchContext(
        service_date="2026-04-24",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="Depot",
                destination="Terminal",
                departure_time="08:00",
                arrival_time="09:00",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="DEPOT",
                destination_stop_id="B",
            )
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "Depot"): DeadheadRule("DEPOT", "Depot", 0),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 60),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        location_aliases={"Depot": ("DEPOT",)},
    )


def test_builder_extends_single_day_target_horizon_to_24h() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="s_target_horizon",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
    )

    assert problem.scenario.horizon_start == "05:00"
    assert problem.scenario.horizon_end == "05:00"
    assert problem.scenario.planning_horizon_hours == 24.0
    assert problem.metadata["operation_end_time"] == "23:00"
    assert len(problem.price_slots) == 24
    assert len(problem.pv_slots) == 24


def test_builder_treats_zero_target_as_configured_hard_target() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="s_zero_target",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=0.0,
        final_soc_target_tolerance_percent=0.0,
    )

    assert problem.metadata["post_return_soc_target_enabled"] is True
    assert problem.scenario.horizon_end == "05:00"


def test_postsolve_adds_return_home_target_charge_and_costs_it() -> None:
    context = _dispatch_context()
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s_post_return",
            horizon_start="05:00",
            horizon_end="05:00",
            timestep_min=60,
            demand_charge_on_peak_yen_per_kw=3000.0,
            demand_charge_off_peak_yen_per_kw=3000.0,
        ),
        dispatch_context=context,
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="B",
                departure_min=480,
                arrival_min=540,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                initial_soc=80.0,
                battery_capacity_kwh=100.0,
                reserve_soc=20.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=100.0,
                reserve_soc=20.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="DEPOT", name="Depot", charger_ids=("chg-1",), import_limit_kw=100.0),),
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=idx, grid_buy_yen_per_kwh=10.0, demand_charge_weight=1.0)
            for idx in range(24)
        ),
        metadata={
            "final_soc_floor_percent": 20.0,
            "final_soc_target_percent": 80.0,
            "final_soc_target_tolerance_percent": 0.0,
            "operation_end_time": "23:00",
        },
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="bev-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=context.trips[0], deadhead_from_prev_min=0),),
            ),
        ),
        served_trip_ids=("t1",),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"bev-1": "bev-1"}},
    )

    repaired = _with_recomputed_charging(problem, plan)
    report = FeasibilityChecker().evaluate(problem, repaired)
    breakdown = CostEvaluator().evaluate(problem, repaired)

    assert repaired.charging_slots
    assert min(slot.slot_index for slot in repaired.charging_slots) >= 5
    assert report.feasible, report.errors
    assert breakdown.realized_ev_charge_cost > 0.0
    assert breakdown.grid_to_bus_kwh > 0.0
    assert breakdown.demand_cost > 0.0


def test_post_return_target_violation_is_reported_when_overnight_charge_is_blocked() -> None:
    context = _dispatch_context()
    late_trip = Trip(
        trip_id="late",
        route_id="r1",
        origin="Depot",
        destination="Terminal",
        departure_time="22:00",
        arrival_time="23:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="DEPOT",
        destination_stop_id="B",
    )
    context.trips = [late_trip]
    context.__post_init__()
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s_late_target",
            horizon_start="05:00",
            horizon_end="05:00",
            timestep_min=60,
        ),
        dispatch_context=context,
        trips=(
            ProblemTrip(
                trip_id="late",
                route_id="r1",
                origin="DEPOT",
                destination="B",
                departure_min=22 * 60,
                arrival_min=23 * 60,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                initial_soc=80.0,
                battery_capacity_kwh=100.0,
                reserve_soc=20.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=100.0,
                reserve_soc=20.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="DEPOT", name="Depot", charger_ids=("chg-1",), import_limit_kw=100.0),),
        chargers=(ChargerDefinition("chg-1", "DEPOT", 20.0),),
        price_slots=tuple(EnergyPriceSlot(slot_index=idx, grid_buy_yen_per_kwh=10.0) for idx in range(24)),
        metadata={
            "final_soc_floor_percent": 20.0,
            "final_soc_target_percent": 95.0,
            "final_soc_target_tolerance_percent": 0.0,
            "operation_end_time": "23:00",
        },
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="bev-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=late_trip, deadhead_from_prev_min=0),),
            ),
        ),
        served_trip_ids=("late",),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"bev-1": "bev-1"}},
    )

    repaired = _with_recomputed_charging(problem, plan)
    report = FeasibilityChecker().evaluate(problem, repaired)

    assert not report.feasible
    assert any("SOC_TARGET" in error for error in report.errors)


def test_feasibility_rejects_target_charge_before_return_deadhead_completion() -> None:
    context = _dispatch_context()
    context.deadhead_rules[("B", "DEPOT")] = DeadheadRule("B", "DEPOT", 90)
    context.__post_init__()
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s_return_completion",
            horizon_start="05:00",
            horizon_end="05:00",
            timestep_min=60,
        ),
        dispatch_context=context,
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="B",
                departure_min=480,
                arrival_min=540,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                initial_soc=100.0,
                battery_capacity_kwh=100.0,
                reserve_soc=20.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=100.0,
                reserve_soc=20.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="DEPOT", name="Depot", charger_ids=("chg-1",), import_limit_kw=100.0),),
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        price_slots=tuple(EnergyPriceSlot(slot_index=idx, grid_buy_yen_per_kwh=10.0) for idx in range(24)),
        metadata={
            "final_soc_floor_percent": 20.0,
            "final_soc_target_percent": 70.0,
            "final_soc_target_tolerance_percent": 0.0,
            "operation_end_time": "23:00",
        },
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="bev-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=context.trips[0], deadhead_from_prev_min=0),),
            ),
        ),
        charging_slots=(ChargingSlot(vehicle_id="bev-1", slot_index=5, charger_id="chg-1", charge_kw=60.0),),
        served_trip_ids=("t1",),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"bev-1": "bev-1"}},
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert not report.feasible
    assert any("charges before return deadhead completion" in error for error in report.errors)
