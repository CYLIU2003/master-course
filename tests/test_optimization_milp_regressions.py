from __future__ import annotations

from dataclasses import replace

import pytest

from src.dispatch.models import DeadheadRule, DispatchContext, Trip, TurnaroundRule, VehicleProfile
from src.optimization import OptimizationConfig, OptimizationMode, ProblemBuilder
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import EnergyPriceSlot, PVSlot
from src.optimization.milp.engine import MILPOptimizer


def _trip(
    trip_id: str,
    origin: str,
    destination: str,
    departure: str,
    arrival: str,
    distance_km: float = 10.0,
    allowed: tuple[str, ...] = ("BEV",),
) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="R1",
        origin=origin,
        destination=destination,
        departure_time=departure,
        arrival_time=arrival,
        distance_km=distance_km,
        allowed_vehicle_types=allowed,
    )


def _context_chain() -> DispatchContext:
    # T1->T2->T3 is feasible; T1->T3 is infeasible because B->A deadhead is undefined.
    trips = [
        _trip("T1", "A", "B", "08:00", "08:30", distance_km=0.0),
        _trip("T2", "B", "C", "08:40", "09:10", distance_km=0.0),
        _trip("T3", "C", "A", "09:20", "09:50", distance_km=0.0),
    ]
    return DispatchContext(
        service_date="2026-03-16",
        trips=trips,
        turnaround_rules={
            "A": TurnaroundRule(stop_id="A", min_turnaround_min=5),
            "B": TurnaroundRule(stop_id="B", min_turnaround_min=5),
            "C": TurnaroundRule(stop_id="C", min_turnaround_min=5),
        },
        deadhead_rules={
            ("C", "A"): DeadheadRule(from_stop="C", to_stop="A", travel_time_min=0),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
                fixed_use_cost_jpy=1000.0,
            )
        },
        default_turnaround_min=5,
    )


def _build_problem() -> object:
    return ProblemBuilder().build_from_dispatch(
        _context_chain(),
        scenario_id="sc-regression",
        vehicle_counts={"BEV": 1},
    )


def _build_single_trip_problem() -> object:
    ctx = DispatchContext(
        service_date="2026-03-16",
        trips=[_trip("PV1", "A", "B", "05:00", "05:30", distance_km=0.0)],
        turnaround_rules={
            "A": TurnaroundRule(stop_id="A", min_turnaround_min=5),
            "B": TurnaroundRule(stop_id="B", min_turnaround_min=5),
        },
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
                fixed_use_cost_jpy=1000.0,
            )
        },
        default_turnaround_min=5,
    )
    return ProblemBuilder().build_from_dispatch(
        ctx,
        scenario_id="sc-single",
        vehicle_counts={"BEV": 1},
    )


def test_milp_arc_flow_allows_indirect_chain_same_vehicle():
    problem = _build_problem()
    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=20, mip_gap=0.01),
    )

    assert result.solver_metadata["backend"] == "gurobi"
    assert result.solver_metadata["supports_exact_milp"] is True
    assert set(result.plan.served_trip_ids) == {"T1", "T2", "T3"}
    assert result.plan.unserved_trip_ids == ()


def test_milp_objective_does_not_double_count_fixed_cost_per_trip():
    builder = ProblemBuilder()

    single_ctx = DispatchContext(
        service_date="2026-03-16",
        trips=[_trip("S1", "A", "B", "08:00", "08:30", distance_km=0.0)],
        turnaround_rules={"A": TurnaroundRule(stop_id="A", min_turnaround_min=5), "B": TurnaroundRule(stop_id="B", min_turnaround_min=5)},
        deadhead_rules={},
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV", battery_capacity_kwh=300.0, fixed_use_cost_jpy=1000.0)},
        default_turnaround_min=5,
    )
    chain_ctx = DispatchContext(
        service_date="2026-03-16",
        trips=[
            _trip("C1", "A", "B", "08:00", "08:30", distance_km=0.0),
            _trip("C2", "B", "A", "08:40", "09:10", distance_km=0.0),
        ],
        turnaround_rules={"A": TurnaroundRule(stop_id="A", min_turnaround_min=5), "B": TurnaroundRule(stop_id="B", min_turnaround_min=5)},
        deadhead_rules={},
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV", battery_capacity_kwh=300.0, fixed_use_cost_jpy=1000.0)},
        default_turnaround_min=5,
    )

    p1 = builder.build_from_dispatch(single_ctx, scenario_id="single", vehicle_counts={"BEV": 1})
    p2 = builder.build_from_dispatch(chain_ctx, scenario_id="chain", vehicle_counts={"BEV": 1})

    cfg = OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=20, mip_gap=0.01)
    r1 = MILPOptimizer().solve(p1, cfg)
    r2 = MILPOptimizer().solve(p2, cfg)

    obj1 = float(r1.plan.metadata.get("objective_value", 0.0))
    obj2 = float(r2.plan.metadata.get("objective_value", 0.0))

    # Fixed cost should be charged once per used vehicle, not once per assigned trip.
    assert obj1 == pytest.approx(obj2, rel=1e-8, abs=1e-8)


def test_deadhead_cost_uses_tou_slot_of_deadhead_departure():
    problem = _build_problem()
    evaluator = CostEvaluator()

    tuned = replace(
        problem,
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=100.0),
        ),
    )

    # horizon_start is 08:00 in this fixture.
    # next trip at 08:40 (slot 1), deadhead 20 min => deadhead departure 08:20 (slot 0).
    cost = evaluator._deadhead_energy_cost(
        tuned,
        deadhead_from_prev_min=20,
        next_trip_departure_min=8 * 60 + 40,
    )

    expected_energy_kwh = (20 / 60.0) * 20.0 * 1.2
    assert cost == pytest.approx(expected_energy_kwh * 10.0, rel=1e-8, abs=1e-8)


def test_trip_energy_cost_pv_credit_is_dimensionally_consistent():
    problem = _build_single_trip_problem()
    evaluator = CostEvaluator()

    tuned = replace(
        problem,
        trips=(replace(problem.trips[0], energy_kwh=10.0),),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=20.0, grid_sell_yen_per_kwh=5.0),
        ),
        pv_slots=(
            PVSlot(slot_index=0, pv_available_kw=100.0),
        ),
    )

    first_trip_id = tuned.trips[0].trip_id
    cost = evaluator._trip_energy_cost(tuned, first_trip_id)

    # timestep 30 min => PV available 50 kWh in slot; trip needs 10 kWh
    # credit = 10 * (buy - sell) = 10 * 15 = 150
    # gross = 10 * 20 = 200 => net = 50
    assert cost == pytest.approx(50.0, rel=1e-8, abs=1e-8)
