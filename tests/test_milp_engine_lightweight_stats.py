from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationMode,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import MILPSolverOutcome


class _Breakdown:
    def to_dict(self) -> dict[str, float]:
        return {"objective_value": 0.0}


def test_milp_optimizer_avoids_full_model_build_for_metadata(monkeypatch) -> None:
    optimizer = MILPOptimizer()

    class _FakeBuilder:
        def enumerate_assignment_pairs(self, problem):
            return [("veh-1", "t1")]

        def enumerate_arc_pairs(self, problem, trip_by_id):
            return []

        def build(self, problem):
            raise AssertionError("full MILP model build should not run for metadata only")

    class _FakeAdapter:
        def solve(self, problem, config):
            return (
                MILPSolverOutcome(
                    solver_status="optimal",
                    used_backend="fake",
                    supports_exact_milp=True,
                ),
                AssignmentPlan(served_trip_ids=("t1",)),
            )

    monkeypatch.setattr(optimizer, "_builder", _FakeBuilder())
    monkeypatch.setattr(optimizer, "_adapter", _FakeAdapter())
    monkeypatch.setattr(
        optimizer,
        "_feasibility",
        SimpleNamespace(
            evaluate=lambda problem, plan: SimpleNamespace(
                feasible=True,
                warnings=(),
                errors=(),
            )
        ),
    )
    monkeypatch.setattr(
        optimizer,
        "_evaluator",
        SimpleNamespace(
            evaluate=lambda problem, plan: _Breakdown(),
            build_plan_ledgers=lambda problem, plan, breakdown: ((), ()),
        ),
    )

    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s1", timestep_min=60),
        dispatch_context=SimpleNamespace(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=510,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=12.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
            ),
        ),
    )

    result = optimizer.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=15),
    )

    assert result.solver_status == "optimal"
    assert result.solver_metadata["model_stats"]["variables"]["assignment"] == 1
