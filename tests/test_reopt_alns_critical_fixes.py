from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.alns.operators_destroy import peak_hour_removal, worst_trip_removal
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationConfig,
    OptimizationScenario,
    ProblemDepot,
    ProblemRoute,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.optimization.rolling.reoptimizer import RollingReoptimizer


class _CaptureEngine:
    def __init__(self) -> None:
        self.last_problem = None

    def solve(self, problem, config):
        self.last_problem = problem
        return {"ok": True, "config": config.mode.value}


def _minimal_problem(*, initial_soc: float = 200.0) -> CanonicalOptimizationProblem:
    trip = ProblemTrip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_min=480,
        arrival_min=540,
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
        energy_kwh=30.0,
        required_soc_departure_percent=0.4,
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s1",
            horizon_start="00:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=None,
        trips=(trip,),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=initial_soc,
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
            ),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=8, grid_buy_yen_per_kwh=20.0, demand_charge_weight=1.0),
            EnergyPriceSlot(slot_index=15, grid_buy_yen_per_kwh=10.0, demand_charge_weight=0.0),
        ),
    )


def test_rolling_reoptimizer_applies_actual_soc_kwh() -> None:
    optimizer = RollingReoptimizer()
    capture = _CaptureEngine()
    optimizer._engine = capture  # type: ignore[attr-defined]

    problem = _minimal_problem(initial_soc=250.0)
    result = optimizer.reoptimize(
        problem,
        config=OptimizationConfig(),
        current_min=600,
        actual_soc={"veh-1": 120.0},
    )

    assert result["ok"] is True
    assert capture.last_problem is not None
    assert capture.last_problem.vehicles[0].initial_soc == 120.0


def test_rolling_reoptimizer_preserves_problem_fields_when_locking_baseline() -> None:
    optimizer = RollingReoptimizer()
    capture = _CaptureEngine()
    optimizer._engine = capture  # type: ignore[attr-defined]

    base = _minimal_problem(initial_soc=220.0)
    baseline_plan = AssignmentPlan()
    problem = CanonicalOptimizationProblem(
        scenario=base.scenario,
        dispatch_context=base.dispatch_context,
        trips=base.trips,
        vehicles=base.vehicles,
        routes=(ProblemRoute(route_id="r1", trip_ids=("t1",), route_name="R1"),),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot 1", charger_ids=("c1",), import_limit_kw=500.0),),
        vehicle_types=base.vehicle_types,
        chargers=base.chargers,
        price_slots=base.price_slots,
        pv_slots=base.pv_slots,
        depot_energy_assets={"dep-1": DepotEnergyAsset(depot_id="dep-1", pv_enabled=True)},
        feasible_connections=base.feasible_connections,
        objective_weights=base.objective_weights,
        baseline_plan=baseline_plan,
        metadata={"k": "v"},
    )

    optimizer.reoptimize(problem, config=OptimizationConfig(), current_min=600)

    assert capture.last_problem is not None
    assert capture.last_problem.routes == problem.routes
    assert capture.last_problem.depots == problem.depots
    assert capture.last_problem.vehicle_types == problem.vehicle_types
    assert capture.last_problem.depot_energy_assets == problem.depot_energy_assets
    assert capture.last_problem.metadata == problem.metadata


def test_peak_hour_removal_uses_data_driven_peak_slots() -> None:
    t_peak = Trip(
        trip_id="peak",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    t_off = Trip(
        trip_id="off",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="15:00",
        arrival_time="15:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="d1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=t_peak), DutyLeg(trip=t_off)),
            ),
        ),
        served_trip_ids=("peak", "off"),
        unserved_trip_ids=(),
    )
    problem = _minimal_problem()

    import random

    destroyed = peak_hour_removal(
        plan,
        random.Random(0),
        1.0,
        problem=problem,
        use_data_driven_peak=True,
    )

    assert "peak" in destroyed.unserved_trip_ids
    assert "off" not in destroyed.unserved_trip_ids


def test_worst_trip_removal_uses_marginal_objective_improvement() -> None:
    t1 = Trip(
        trip_id="high",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="10:00",
        arrival_time="10:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    t2 = Trip(
        trip_id="low",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="11:00",
        arrival_time="11:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(duty_id="d1", vehicle_type="BEV", legs=(DutyLeg(trip=t1), DutyLeg(trip=t2))),
        ),
        served_trip_ids=("high", "low"),
        unserved_trip_ids=(),
    )

    def objective(p: AssignmentPlan) -> float:
        return 100.0 if "high" in p.served_trip_ids else 0.0

    import random

    destroyed = worst_trip_removal(plan, random.Random(0), 0.5, objective_fn=objective)
    assert "high" in destroyed.unserved_trip_ids


def test_feasibility_checker_detects_soc_shortage() -> None:
    trip_dispatch = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_dispatch),),
            ),
        ),
        served_trip_ids=("t1",),
        unserved_trip_ids=(),
    )
    problem = _minimal_problem(initial_soc=10.0)

    report = FeasibilityChecker().evaluate(problem, plan)

    assert report.feasible is False
    assert any(msg.startswith("[SOC]") for msg in report.errors)
