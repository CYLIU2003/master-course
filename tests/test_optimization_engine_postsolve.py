from __future__ import annotations

from src.dispatch.models import DeadheadRule, DispatchContext, DutyLeg, Trip, VehicleDuty, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import AssignmentPlan, OptimizationConfig, OptimizationEngineResult, OptimizationMode
from src.optimization.engine import OptimizationEngine


class _FakeMILPOptimizer:
    def __init__(self, result: OptimizationEngineResult) -> None:
        self._result = result

    def solve(self, problem, config) -> OptimizationEngineResult:  # noqa: ANN001
        return self._result


def test_optimization_engine_rebuilds_impossible_fragment_sequence() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Stop A",
        destination="Stop B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-b",
        route_family_code="渋24",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-b",
        origin="Stop C",
        destination="Stop D",
        departure_time="08:45",
        arrival_time="09:15",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-c",
        destination_stop_id="stop-d",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={
            ("stop-b", "stop-depot"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-depot",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-c"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-c",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-a"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-a",
                travel_time_min=5,
            ),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_postsolve_rebuild",
        vehicle_counts={"BEV": 1},
        fixed_route_band_mode=True,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        canonical_depot_id="dep1",
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=5),),
            ),
            VehicleDuty(
                duty_id="veh-1__frag2",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_b, deadhead_from_prev_min=10),),
            ),
        ),
        served_trip_ids=("t_a", "t_b"),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1", "veh-1__frag2": "veh-1"}},
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=plan,
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={},
    )

    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=5, mip_gap=0.0),
    )

    assert result.feasible is True
    assert result.plan.served_trip_ids == ("t_a",)
    assert result.plan.unserved_trip_ids == ("t_b",)
    assert result.plan.duty_vehicle_map() == {"BEV_001": "BEV_001"}
    assert result.solver_metadata.get("postsolve_assignment_rebuilt") is True


def test_optimization_engine_merges_directly_connectable_same_band_fragments() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Stop A",
        destination="Stop B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-b",
        route_family_code="渋24",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-b",
        origin="Stop C",
        destination="Stop D",
        departure_time="08:50",
        arrival_time="09:20",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-c",
        destination_stop_id="stop-d",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={
            ("stop-b", "stop-c"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-c",
                travel_time_min=5,
            ),
            ("stop-b", "stop-depot"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-depot",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-c"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-c",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-a"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-a",
                travel_time_min=5,
            ),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_postsolve_merge",
        vehicle_counts={"BEV": 1},
        fixed_route_band_mode=True,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        canonical_depot_id="dep1",
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=5),),
            ),
            VehicleDuty(
                duty_id="veh-1__frag2",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_b, deadhead_from_prev_min=10),),
            ),
        ),
        served_trip_ids=("t_a", "t_b"),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1", "veh-1__frag2": "veh-1"}},
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=plan,
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={},
    )

    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=5, mip_gap=0.0),
    )

    assert result.feasible is True
    assert result.plan.served_trip_ids == ("t_a", "t_b")
    assert result.plan.unserved_trip_ids == ()
    assert len(result.plan.duties) == 1
    assert result.plan.duties[0].trip_ids == ["t_a", "t_b"]
    assert result.plan.duties[0].legs[1].deadhead_from_prev_min == 5


def test_optimization_engine_uses_truthful_baseline_guardrail_when_milp_candidate_is_worse() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Depot",
        destination="Stop A",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-depot",
        destination_stop_id="stop-a",
        route_family_code="渋24",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-a",
        origin="Stop A",
        destination="Depot",
        departure_time="08:40",
        arrival_time="09:10",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-depot",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_truthful_guardrail",
        vehicle_counts={"BEV": 1},
        fixed_route_band_mode=True,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        canonical_depot_id="dep1",
    )
    weak_plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=0),),
            ),
        ),
        served_trip_ids=("t_a",),
        unserved_trip_ids=("t_b",),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1"}},
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=123.0,
        plan=weak_plan,
        feasible=True,
        cost_breakdown={"objective_value": 123.0, "total_cost": 123.0},
        solver_metadata={"supports_exact_milp": True},
    )

    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=5, mip_gap=0.0),
    )

    assert result.solver_status == "truthful_baseline_guardrail"
    assert result.plan.unserved_trip_ids == ()
    assert tuple(sorted(result.plan.served_trip_ids)) == ("t_a", "t_b")
    assert result.solver_metadata.get("truthful_baseline_guardrail_applied") is True
    assert result.solver_metadata.get("supports_exact_milp") is False
