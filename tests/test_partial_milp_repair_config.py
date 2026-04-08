from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization.alns import operators_repair as repair_module
from src.optimization.alns.operators_repair import partial_milp_repair
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationMode,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)


class _FakeMILPOptimizer:
    def __init__(self, captured: dict[str, object]) -> None:
        self._captured = captured

    def solve(self, problem, config):
        self._captured["sub_problem"] = problem
        self._captured["sub_config"] = config
        return SimpleNamespace(
            plan=AssignmentPlan(),
            solver_status="optimal",
            feasible=True,
        )


def _make_problem() -> CanonicalOptimizationProblem:
    dispatch_trips = [
        Trip(
            trip_id=f"t{i}",
            route_id="r1",
            origin="A",
            destination="B",
            departure_time=f"0{i}:00",
            arrival_time=f"0{i}:30",
            distance_km=10.0,
            allowed_vehicle_types=("BEV",),
        )
        for i in range(1, 4)
    ]
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="partial-milp-repair",
            horizon_start="00:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=DispatchContext(
            service_date="2026-03-23",
            trips=dispatch_trips,
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={
                "BEV": VehicleProfile(
                    vehicle_type="BEV",
                    battery_capacity_kwh=300.0,
                )
            },
        ),
        trips=tuple(
            ProblemTrip(
                trip_id=f"t{i}",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=60 * i,
                arrival_min=60 * i + 30,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            )
            for i in range(1, 4)
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
        feasible_connections={},
        metadata={},
    )


def test_partial_milp_repair_uses_config_and_records_metadata(monkeypatch) -> None:
    problem = _make_problem()
    plan = AssignmentPlan(
        duties=(),
        served_trip_ids=(),
        unserved_trip_ids=("t1", "t2", "t3"),
        metadata={},
    )
    config = OptimizationConfig(
        mode=OptimizationMode.ALNS,
        time_limit_sec=123,
        mip_gap=0.07,
        random_seed=99,
        partial_milp_trip_limit=2,
        warm_start=False,
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        repair_module,
        "MILPOptimizer",
        lambda: _FakeMILPOptimizer(captured),
    )

    def fake_append(problem, plan, duties, operator_name):
        captured["append_operator_name"] = operator_name
        captured["append_duty_count"] = len(duties)
        return replace(
            plan,
            metadata={
                **dict(plan.metadata),
                "repair_operator": operator_name,
                "append_duty_count": len(duties),
            },
        )

    monkeypatch.setattr(repair_module, "_append_generated_duties", fake_append)
    monkeypatch.setattr(repair_module, "_with_recomputed_charging", lambda problem, plan: plan)

    repaired = partial_milp_repair(problem, plan, config=config)

    sub_config = captured["sub_config"]
    sub_problem = captured["sub_problem"]

    assert sub_config.time_limit_sec == 123
    assert abs(sub_config.mip_gap - 0.07) < 1.0e-9
    assert sub_config.random_seed == 99
    assert sub_config.partial_milp_trip_limit == 2
    assert sub_config.warm_start is False
    assert sub_problem.metadata["partial_milp_repair_settings"] == {
        "trip_limit": 2,
        "time_limit_sec": 123,
        "mip_gap": 0.07,
        "random_seed": 99,
    }
    assert sub_problem.metadata["partial_milp_repair_target_trip_ids"] == ("t1", "t2")
    assert captured["append_operator_name"] == "partial_milp_repair"
    assert captured["append_duty_count"] == 0
    assert repaired.metadata["repair_operator"] == "partial_milp_repair"
    assert repaired.metadata["partial_milp_repair_settings"] == {
        "trip_limit": 2,
        "time_limit_sec": 123,
        "mip_gap": 0.07,
        "random_seed": 99,
    }
    assert repaired.metadata["partial_milp_repair_solver_status"] == "optimal"
    assert repaired.metadata["partial_milp_repair_has_feasible_incumbent"] is True
