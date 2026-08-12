from __future__ import annotations

from dataclasses import replace

import pytest

from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    DutyLeg,
    Trip,
    VehicleDuty,
    VehicleProfile,
)
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
from src.optimization.rolling.reoptimizer import (
    RollingReoptimizer,
    assignment_plan_from_serialized_result,
)


class _CaptureEngine:
    def __init__(self) -> None:
        self.last_problem = None
        self.last_config = None

    def solve(self, problem, config):
        self.last_problem = problem
        self.last_config = config
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


def test_rolling_reoptimizer_rejects_unknown_actual_soc_vehicle() -> None:
    optimizer = RollingReoptimizer()

    with pytest.raises(ValueError, match="unknown vehicles"):
        optimizer.reoptimize(
            _minimal_problem(),
            config=OptimizationConfig(),
            current_min=600,
            actual_soc={"not-in-current-scope": 120.0},
        )


def test_rolling_reoptimizer_rejects_unknown_bess_depot() -> None:
    optimizer = RollingReoptimizer()

    with pytest.raises(ValueError, match="unknown depot"):
        optimizer.reoptimize(
            _minimal_problem(),
            config=OptimizationConfig(),
            current_min=600,
            actual_bess_soc_kwh={"not-in-current-scope": 120.0},
        )


def test_persisted_assignment_uses_canonical_trip_and_current_vehicle() -> None:
    dispatch_trip = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
        operator_id="operator-1",
    )
    problem = replace(
        _minimal_problem(),
        dispatch_context=DispatchContext(
            service_date="2025-08-05",
            trips=[dispatch_trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        ),
    )
    serialized = {
        "duties": [
            {
                "duty_id": "duty-1",
                "vehicle_type": "BEV",
                "legs": [{"trip_id": "t1", "deadhead_from_prev_min": 0}],
            }
        ],
        "served_trip_ids": ["t1"],
        "unserved_trip_ids": [],
        "metadata": {"duty_vehicle_map": {"duty-1": "veh-1"}},
    }

    plan = assignment_plan_from_serialized_result(problem, serialized)

    assert plan.duties[0].legs[0].trip is dispatch_trip
    assert plan.duties[0].legs[0].trip.operator_id == "operator-1"
    assert plan.vehicle_id_for_duty("duty-1") == "veh-1"


def test_persisted_assignment_rejects_unknown_mapped_vehicle() -> None:
    dispatch_trip = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    problem = replace(
        _minimal_problem(),
        dispatch_context=DispatchContext(
            service_date="2025-08-05",
            trips=[dispatch_trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        ),
    )
    serialized = {
        "duties": [
            {
                "duty_id": "duty-1",
                "vehicle_type": "BEV",
                "trip_ids": ["t1"],
            }
        ],
        "served_trip_ids": ["t1"],
        "unserved_trip_ids": [],
        "metadata": {"duty_vehicle_map": {"duty-1": "unknown-vehicle"}},
    }

    with pytest.raises(ValueError, match="unknown vehicle"):
        assignment_plan_from_serialized_result(problem, serialized)


def test_persisted_assignment_rejects_infeasible_trip_connection() -> None:
    first_trip = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    overlapping_trip = Trip(
        trip_id="t2",
        route_id="r1",
        origin="B",
        destination="C",
        departure_time="08:30",
        arrival_time="09:30",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    base = _minimal_problem()
    problem = replace(
        base,
        trips=(
            base.trips[0],
            replace(
                base.trips[0],
                trip_id="t2",
                origin="B",
                destination="C",
                departure_min=8 * 60 + 30,
                arrival_min=9 * 60 + 30,
            ),
        ),
        dispatch_context=DispatchContext(
            service_date="2025-08-05",
            trips=[first_trip, overlapping_trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        ),
    )
    serialized = {
        "duties": [
            {
                "duty_id": "duty-1",
                "vehicle_type": "BEV",
                "trip_ids": ["t1", "t2"],
            }
        ],
        "served_trip_ids": ["t1", "t2"],
        "unserved_trip_ids": [],
        "metadata": {"duty_vehicle_map": {"duty-1": "veh-1"}},
    }

    with pytest.raises(ValueError, match="violates current dispatch rules"):
        assignment_plan_from_serialized_result(problem, serialized)


def test_rolling_soc_validation_starts_from_measured_slot_state() -> None:
    dispatch_trip = Trip(
        trip_id="rolling-trip",
        route_id="r1",
        origin="A",
        destination="dep-1",
        departure_time="00:30",
        arrival_time="01:30",
        distance_km=0.0,
        allowed_vehicle_types=("BEV",),
    )
    problem_trip = ProblemTrip(
        trip_id="rolling-trip",
        route_id="r1",
        origin="A",
        destination="dep-1",
        departure_min=30,
        arrival_min=90,
        distance_km=0.0,
        allowed_vehicle_types=("BEV",),
        energy_kwh=20.0,
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="rolling-validation",
            horizon_start="00:00",
            timestep_min=60,
        ),
        dispatch_context=DispatchContext(
            service_date="2025-08-05",
            trips=[dispatch_trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        ),
        trips=(problem_trip,),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=25.0,
                battery_capacity_kwh=100.0,
                reserve_soc=10.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=100.0,
                reserve_soc=10.0,
            ),
        ),
        metadata={
            "final_soc_target_percent": 15.0,
            "final_soc_target_tolerance_percent": 0.0,
        },
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="duty-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=dispatch_trip),),
            ),
        ),
        served_trip_ids=("rolling-trip",),
        metadata={
            "duty_vehicle_map": {"duty-1": "veh-1"},
            "rolling_start_slot_index": 1,
        },
    )

    errors = FeasibilityChecker()._evaluate_soc(problem, plan)

    assert errors == []


def test_rolling_soc_validation_keeps_discretely_posted_unfinished_deadhead() -> None:
    base = _minimal_problem()
    previous_trip = replace(
        base.trips[0],
        trip_id="previous",
        origin="A",
        destination="X",
        departure_min=0,
        arrival_min=30,
    )
    next_trip = replace(
        base.trips[0],
        trip_id="next",
        origin="Y",
        destination="B",
        departure_min=90,
        arrival_min=120,
    )
    problem = replace(
        base,
        dispatch_context=DispatchContext(
            service_date="2025-08-05",
            trips=[],
            turnaround_rules={},
            deadhead_rules={
                ("X", "Y"): DeadheadRule(
                    from_stop="X",
                    to_stop="Y",
                    travel_time_min=60,
                )
            },
            vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        ),
    )

    fraction = FeasibilityChecker()._remaining_deadhead_fraction(
        problem,
        base.vehicles[0],
        previous_trip,
        next_trip,
        rolling_start_abs_min=60,
    )

    # The solver posts the transition as one departure-slot event. The
    # independent validator must keep that whole event across a rolling
    # boundary instead of prorating it.
    assert fraction == pytest.approx(1.0)


def test_hourly_charging_reoptimization_carries_measured_bess_state_and_fixed_assignment() -> None:
    optimizer = RollingReoptimizer()
    capture = _CaptureEngine()
    optimizer._engine = capture  # type: ignore[attr-defined]

    base = _minimal_problem(initial_soc=250.0)
    dispatch_trip = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    day_ahead_plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=dispatch_trip),),
            ),
        ),
        served_trip_ids=("t1",),
    )
    problem = replace(
        base,
        scenario=replace(base.scenario, horizon_start="00:00"),
        metadata={
            **dict(base.metadata or {}),
            "bev_terminal_soc_policy": "return_to_initial",
        },
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                bess_enabled=True,
                bess_energy_kwh=600.0,
                bess_soc_min_kwh=120.0,
                bess_soc_max_kwh=480.0,
                bess_initial_soc_kwh=300.0,
                bess_terminal_soc_min_kwh=120.0,
                bess_terminal_soc_policy="return_to_initial",
                bess_terminal_soc_target_kwh=0.0,
            )
        },
    )

    result = optimizer.reoptimize_charging_hour(
        problem,
        day_ahead_plan,
        OptimizationConfig(time_limit_sec=30),
        current_min=0,
        actual_soc={"veh-1": 240.0},
        actual_bess_soc_kwh={"dep-1": 275.0},
        observed_on_peak_kw_by_depot={"dep-1": 90.0},
        observed_off_peak_kw_by_depot={"dep-1": 70.0},
        active_charge_session_vehicle_ids=("veh-1",),
        bess_terminal_policy="scenario",
    )

    assert result["ok"] is True
    assert capture.last_problem is not None
    assert capture.last_problem.vehicles[0].initial_soc == 240.0
    assert capture.last_problem.metadata[
        "bev_terminal_soc_target_kwh_by_vehicle"
    ] == {"veh-1": 250.0}
    assert capture.last_problem.depot_energy_assets["dep-1"].bess_initial_soc_kwh == 275.0
    assert capture.last_problem.depot_energy_assets["dep-1"].bess_terminal_soc_policy == "fixed_target"
    assert capture.last_problem.depot_energy_assets["dep-1"].bess_terminal_soc_target_kwh == 300.0
    assert capture.last_problem.metadata["bess_terminal_soc_target_kwh_by_depot"] == {
        "dep-1": 300.0
    }
    assert result["config"] == "milp"
    assert capture.last_config is not None
    assert capture.last_config.rolling_active_charge_session_vehicle_ids == (
        "veh-1",
    )

    with pytest.raises(
        ValueError,
        match="outside the fixed electric assignment",
    ):
        optimizer.reoptimize_charging_hour(
            problem,
            day_ahead_plan,
            OptimizationConfig(time_limit_sec=30),
            current_min=0,
            actual_soc={"veh-1": 240.0},
            actual_bess_soc_kwh={"dep-1": 275.0},
            observed_on_peak_kw_by_depot={"dep-1": 90.0},
            observed_off_peak_kw_by_depot={"dep-1": 70.0},
            active_charge_session_vehicle_ids=("unknown-vehicle",),
            bess_terminal_policy="scenario",
        )

    optimizer.reoptimize_charging_hour(
        problem,
        day_ahead_plan,
        OptimizationConfig(time_limit_sec=30),
        current_min=0,
        actual_soc={"veh-1": 240.0},
        actual_bess_soc_kwh={"dep-1": 275.0},
        observed_on_peak_kw_by_depot={"dep-1": 90.0},
        observed_off_peak_kw_by_depot={"dep-1": 70.0},
        bess_terminal_policy="minimum_only",
    )
    assert capture.last_problem is not None
    assert capture.last_problem.depot_energy_assets["dep-1"].bess_terminal_soc_policy == "minimum_only"
    assert capture.last_problem.depot_energy_assets["dep-1"].bess_terminal_soc_target_kwh == 0.0

    optimizer.reoptimize_charging_hour(
        problem,
        day_ahead_plan,
        OptimizationConfig(time_limit_sec=30),
        current_min=0,
        actual_soc={"veh-1": 240.0},
        actual_bess_soc_kwh={"dep-1": 119.99999999999999},
        observed_on_peak_kw_by_depot={"dep-1": 90.0},
        observed_off_peak_kw_by_depot={"dep-1": 70.0},
        bess_terminal_policy="scenario",
    )
    assert capture.last_problem is not None
    assert capture.last_problem.depot_energy_assets["dep-1"].bess_initial_soc_kwh == 120.0

    with pytest.raises(ValueError, match="Measured BESS SOC"):
        optimizer.reoptimize_charging_hour(
            problem,
            day_ahead_plan,
            OptimizationConfig(time_limit_sec=30),
            current_min=0,
            actual_soc={"veh-1": 240.0},
            actual_bess_soc_kwh={"dep-1": 119.99},
            observed_on_peak_kw_by_depot={"dep-1": 90.0},
            observed_off_peak_kw_by_depot={"dep-1": 70.0},
            bess_terminal_policy="scenario",
        )

    with pytest.raises(ValueError, match="finite and non-negative"):
        optimizer.reoptimize_charging_hour(
            problem,
            day_ahead_plan,
            OptimizationConfig(time_limit_sec=30),
            current_min=0,
            actual_soc={"veh-1": 240.0},
            actual_bess_soc_kwh={"dep-1": 275.0},
            observed_on_peak_kw_by_depot={"dep-1": float("nan")},
            observed_off_peak_kw_by_depot={"dep-1": 70.0},
        )


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


def test_feasibility_checker_treats_small_builder_required_soc_as_percent() -> None:
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
    base = _minimal_problem(initial_soc=80.0)
    problem = CanonicalOptimizationProblem(
        scenario=base.scenario,
        dispatch_context=base.dispatch_context,
        trips=base.trips,
        vehicles=base.vehicles,
        routes=base.routes,
        depots=base.depots,
        vehicle_types=base.vehicle_types,
        chargers=base.chargers,
        price_slots=base.price_slots,
        pv_slots=base.pv_slots,
        depot_energy_assets=base.depot_energy_assets,
        feasible_connections=base.feasible_connections,
        objective_weights=base.objective_weights,
        baseline_plan=base.baseline_plan,
        metadata={"required_soc_departure_unit": "percent_0_100"},
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert not any(msg.startswith("[SOC]") for msg in report.errors)


def test_feasibility_checker_keeps_unserved_warning_but_fails_required_validation() -> None:
    trip_1_dispatch = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    trip_2_dispatch = Trip(
        trip_id="t2",
        route_id="r1",
        origin="B",
        destination="C",
        departure_time="10:00",
        arrival_time="11:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="warn-only",
            horizon_start="00:00",
            timestep_min=60,
            objective_mode="total_cost",
            service_coverage_mode="penalized",
        ),
        dispatch_context=DispatchContext(
            service_date="2026-03-23",
            trips=[trip_1_dispatch, trip_2_dispatch],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={
                "BEV": VehicleProfile(
                    vehicle_type="BEV",
                    battery_capacity_kwh=300.0,
                )
            },
            default_turnaround_min=0,
        ),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=540,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            ),
            ProblemTrip(
                trip_id="t2",
                route_id="r1",
                origin="B",
                destination="C",
                departure_min=600,
                arrival_min=660,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=250.0,
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
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_1_dispatch),),
            ),
        ),
        served_trip_ids=("t1",),
        unserved_trip_ids=("t2",),
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert report.feasible is False
    assert any("unassigned trips remain" in msg for msg in report.errors)
    assert report.uncovered_trip_ids == ("t2",)
    assert any(msg.startswith("Uncovered trips:") for msg in report.warnings)


def test_feasibility_checker_marks_unserved_as_error_when_partial_service_disabled() -> None:
    trip_1_dispatch = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    trip_2_dispatch = Trip(
        trip_id="t2",
        route_id="r1",
        origin="B",
        destination="C",
        departure_time="10:00",
        arrival_time="11:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="strict-unserved",
            horizon_start="00:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=DispatchContext(
            service_date="2026-03-23",
            trips=[trip_1_dispatch, trip_2_dispatch],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={
                "BEV": VehicleProfile(
                    vehicle_type="BEV",
                    battery_capacity_kwh=300.0,
                )
            },
            default_turnaround_min=0,
        ),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=540,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            ),
            ProblemTrip(
                trip_id="t2",
                route_id="r1",
                origin="B",
                destination="C",
                departure_min=600,
                arrival_min=660,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=250.0,
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
        metadata={"allow_partial_service": False},
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_1_dispatch),),
            ),
        ),
        served_trip_ids=("t1",),
        unserved_trip_ids=("t2",),
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert report.feasible is False
    assert any("uncovered trips" in msg for msg in report.errors)
    assert not report.warnings


def test_feasibility_checker_allows_sparse_fragments_in_same_vehicle_gap() -> None:
    trip_a1 = Trip(
        trip_id="a1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    trip_a2 = Trip(
        trip_id="a2",
        route_id="r1",
        origin="B",
        destination="C",
        departure_time="12:00",
        arrival_time="12:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    trip_b = Trip(
        trip_id="b1",
        route_id="r1",
        origin="X",
        destination="Y",
        departure_time="13:00",
        arrival_time="13:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="frag-gap",
            horizon_start="00:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=DispatchContext(
            service_date="2026-03-23",
            trips=[trip_a1, trip_a2, trip_b],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV", battery_capacity_kwh=300.0)},
        ),
        trips=(
            ProblemTrip("a1", "r1", "A", "B", 480, 510, 5.0, ("BEV",), energy_kwh=5.0),
            ProblemTrip("a2", "r1", "B", "C", 720, 750, 5.0, ("BEV",), energy_kwh=5.0),
        ProblemTrip("b1", "r1", "X", "Y", 780, 810, 5.0, ("BEV",), energy_kwh=5.0),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=200.0,
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
        metadata={"max_start_fragments_per_vehicle": 4, "max_end_fragments_per_vehicle": 4},
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_a1), DutyLeg(trip=trip_a2)),
            ),
            VehicleDuty(
                duty_id="veh-1__frag2",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_b),),
            ),
        ),
        served_trip_ids=("a1", "a2", "b1"),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1", "veh-1__frag2": "veh-1"}},
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert not any(msg.startswith("[FRAGMENT]") for msg in report.errors)
