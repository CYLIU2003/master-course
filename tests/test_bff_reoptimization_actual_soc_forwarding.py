from __future__ import annotations

from pathlib import Path

from bff.routers import optimization as opt
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemVehicle,
)


def _minimal_problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s1", timestep_min=60),
        dispatch_context=None,
        trips=(),
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
    )


def test_run_reoptimization_forwards_actual_soc_to_reoptimizer(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeBuilder:
        def build_from_scenario(self, scenario, depot_id, service_id, config, planning_days=1):
            return _minimal_problem()

    class _FakeRollingReoptimizer:
        def reoptimize(self, problem, config, current_min, actual_soc=None):
            captured["actual_soc"] = dict(actual_soc or {})
            captured["current_min"] = int(current_min)
            return object()

    monkeypatch.setattr(opt.store, "get_scenario_document_shallow", lambda scenario_id: {"scenario_id": scenario_id})
    monkeypatch.setattr(opt.store, "set_field", lambda *args, **kwargs: None)
    monkeypatch.setattr(opt.store, "get_field", lambda *args, **kwargs: None)
    monkeypatch.setattr(opt.job_store, "update_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(opt, "_prepared_inputs_root", lambda: Path("."))
    monkeypatch.setattr(opt, "load_prepared_input", lambda **kwargs: {})
    monkeypatch.setattr(
        opt,
        "materialize_scenario_from_prepared_input",
        lambda base, prepared: dict(base),
    )
    monkeypatch.setattr(opt, "ProblemBuilder", _FakeBuilder)
    monkeypatch.setattr(opt, "RollingReoptimizer", _FakeRollingReoptimizer)
    monkeypatch.setattr(opt.ResultSerializer, "serialize_result", staticmethod(lambda result: {"objective_value": 0.0}))
    monkeypatch.setattr(opt, "_git_sha", lambda: "test-sha")

    payload = {
        "mode": "hybrid",
        "current_time": "08:30",
        "time_limit_seconds": 30,
        "mip_gap": 0.1,
        "random_seed": 1,
        "alns_iterations": 5,
        "no_improvement_limit": 2,
        "destroy_fraction": 0.2,
        "actual_soc": {"veh-1": 123.0},
        "actual_location_node_id": {},
        "delays": [],
        "updated_pv_profile": [],
    }

    opt._run_reoptimization(
        scenario_id="scenario-x",
        job_id="job-x",
        body_payload=payload,
        prepared_input_id="prep-x",
        service_id="WEEKDAY",
        depot_id="dep-1",
    )

    assert captured["actual_soc"] == {"veh-1": 123.0}
    assert captured["current_min"] == 8 * 60 + 30
