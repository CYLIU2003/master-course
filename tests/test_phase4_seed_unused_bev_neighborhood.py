from __future__ import annotations

from types import SimpleNamespace

import src.optimization.milp.solver_adapter as solver_adapter_module
from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationScenario,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import (
    GurobiMILPAdapter,
    MILPSolverOutcome,
    _maximum_bipartite_vehicle_matching,
    _remap_plan_vehicle_ids,
)


def _trip(trip_id: str, departure: str) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="route",
        origin="DEPOT",
        destination="DEPOT",
        departure_time=departure,
        arrival_time=departure,
        distance_km=1.0,
        allowed_vehicle_types=("BEV", "ICE"),
        operator_id="tokyu",
    )


def _seed_plan() -> AssignmentPlan:
    duties = (
        VehicleDuty(
            duty_id="duty-ice",
            vehicle_type="ICE",
            legs=(DutyLeg(_trip("trip-ice", "08:00")),),
        ),
        VehicleDuty(
            duty_id="duty-bev",
            vehicle_type="BEV",
            legs=(DutyLeg(_trip("trip-bev", "09:00")),),
        ),
    )
    return AssignmentPlan(
        duties=duties,
        served_trip_ids=("trip-ice", "trip-bev"),
        metadata={
            "duty_vehicle_map": {
                "duty-ice": "ice-1",
                "duty-bev": "bev-used",
            },
            "stage1_feasible": True,
            "stage2_feasible": True,
            "stage2_has_feasible_incumbent": True,
        },
    )


def _problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="unused-bev-neighborhood",
            timestep_min=60,
        ),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(
            ProblemVehicle("ice-1", "ICE", "DEPOT"),
            ProblemVehicle("bev-used", "BEV", "DEPOT"),
            ProblemVehicle("bev-a", "BEV", "DEPOT"),
            ProblemVehicle("bev-b", "BEV", "DEPOT"),
        ),
    )


def test_maximum_bipartite_vehicle_matching_is_maximum_and_deterministic() -> None:
    matching = _maximum_bipartite_vehicle_matching(
        {
            "ice-a": ("bev-1", "bev-2"),
            "ice-b": ("bev-1",),
            "ice-c": ("bev-2", "bev-3"),
        }
    )

    assert matching == {
        "ice-a": "bev-2",
        "ice-b": "bev-1",
        "ice-c": "bev-3",
    }


def test_remap_plan_vehicle_ids_clears_stale_energy_and_preserves_paths() -> None:
    seed = _seed_plan()
    remapped = _remap_plan_vehicle_ids(
        seed,
        replacement_by_source_vehicle={"ice-1": "bev-a"},
        vehicle_type_by_id={
            "ice-1": "ICE",
            "bev-used": "BEV",
            "bev-a": "BEV",
        },
        candidate_source="test",
    )

    assert remapped.vehicle_paths() == {
        "bev-a": ("trip-ice",),
        "bev-used": ("trip-bev",),
    }
    assert all(duty.vehicle_type == "BEV" for duty in remapped.duties)
    assert remapped.charging_slots == ()
    assert remapped.vehicle_soc_kwh_by_vehicle_slot == {}


def test_unused_bev_neighborhood_selects_only_exact_lower_cost_candidate(
    monkeypatch,
) -> None:
    class _FakeFeasibilityChecker:
        def evaluate(self, _problem, _plan):
            return SimpleNamespace(feasible=True, errors=())

    class _FakeCostEvaluator:
        def evaluate(self, _problem, plan):
            used_ids = set(plan.duties_by_vehicle())
            if "ice-1" in used_ids:
                cost = 100.0
            elif used_ids == {"bev-a", "bev-b"}:
                cost = 70.0
            elif used_ids == {"bev-used", "bev-b"}:
                cost = 75.0
            else:
                cost = 80.0
            return SimpleNamespace(
                total_cost=cost,
                evaluation_feasible=True,
            )

    monkeypatch.setattr(
        solver_adapter_module,
        "FeasibilityChecker",
        _FakeFeasibilityChecker,
    )
    monkeypatch.setattr(
        solver_adapter_module,
        "CostEvaluator",
        _FakeCostEvaluator,
    )
    adapter = GurobiMILPAdapter()

    def _fake_stage2(_problem, _config, plan, **_kwargs):
        solved = AssignmentPlan(
            **{
                **plan.__dict__,
                "metadata": {
                    **dict(plan.metadata or {}),
                    "stage2_feasible": True,
                    "stage2_has_feasible_incumbent": True,
                },
            }
        )
        return (
            MILPSolverOutcome(
                solver_status="optimal",
                used_backend="test",
                supports_exact_milp=True,
                has_feasible_incumbent=True,
                incumbent_count=1,
            ),
            solved,
        )

    monkeypatch.setattr(
        adapter,
        "_solve_thesis_stage2_charging_dispatch",
        _fake_stage2,
    )

    selected, audit = (
        adapter.improve_phase4_seed_with_unused_bev_neighborhood(
            _problem(),
            OptimizationConfig(
                phase4_phase3_seed_unused_bev_neighborhood_enabled=True,
                phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec=30,
                phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec=1,
                phase4_phase3_seed_unused_bev_neighborhood_max_evaluations=20,
                phase4_phase3_seed_unused_bev_identity_exchange_rounds=2,
            ),
            _seed_plan(),
        )
    )

    assert set(selected.duties_by_vehicle()) == {"bev-a", "bev-b"}
    assert audit["selected"] is True
    assert audit["selected_canonical_cost_jpy"] == 70.0
    assert audit["selected_cost_improvement_jpy"] == 30.0
    assert audit["selected_used_bev"] == 2
    assert audit["selected_used_ice"] == 0
    assert audit["maximum_observed_used_bev"] == 2
    assert audit["weather_strategy_bias_applied"] is False
    assert audit["global_optimality_claimed"] is False

    class _ExpensiveBevCostEvaluator:
        def evaluate(self, _problem, plan):
            used_ids = set(plan.duties_by_vehicle())
            cost = 100.0 if "ice-1" in used_ids else 120.0
            return SimpleNamespace(
                total_cost=cost,
                evaluation_feasible=True,
            )

    monkeypatch.setattr(
        solver_adapter_module,
        "CostEvaluator",
        _ExpensiveBevCostEvaluator,
    )
    expensive_bev_adapter = GurobiMILPAdapter()
    monkeypatch.setattr(
        expensive_bev_adapter,
        "_solve_thesis_stage2_charging_dispatch",
        _fake_stage2,
    )
    retained, expensive_audit = (
        expensive_bev_adapter.improve_phase4_seed_with_unused_bev_neighborhood(
            _problem(),
            OptimizationConfig(
                phase4_phase3_seed_unused_bev_neighborhood_enabled=True,
                phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec=30,
                phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec=1,
                phase4_phase3_seed_unused_bev_neighborhood_max_evaluations=20,
                phase4_phase3_seed_unused_bev_identity_exchange_rounds=2,
            ),
            _seed_plan(),
        )
    )

    assert set(retained.duties_by_vehicle()) == {"ice-1", "bev-used"}
    assert expensive_audit["selected"] is False
    assert expensive_audit["selected_canonical_cost_jpy"] == 100.0
    assert expensive_audit["maximum_observed_used_bev"] == 2
    assert expensive_audit["maximum_bev_candidate_canonical_cost_jpy"] == 120.0
