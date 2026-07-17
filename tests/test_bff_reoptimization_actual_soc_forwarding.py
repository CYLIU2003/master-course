from __future__ import annotations

from pathlib import Path

import pytest

from bff.routers import optimization as opt
from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
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
        def reoptimize(
            self,
            problem,
            config,
            current_min,
            actual_soc=None,
            actual_bess_soc_kwh=None,
        ):
            captured["actual_soc"] = dict(actual_soc or {})
            captured["actual_bess_soc_kwh"] = dict(actual_bess_soc_kwh or {})
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


def test_reoptimization_body_collections_are_not_shared() -> None:
    first = opt.ReoptimizeBody(current_time="08:00")
    second = opt.ReoptimizeBody(current_time="09:00")

    first.actual_soc["veh-1"] = 100.0
    first.updated_pv_profile.append({"slot_index": 1})

    assert second.actual_soc == {}
    assert second.updated_pv_profile == []


def test_day_ahead_contract_accepts_same_prepared_scope() -> None:
    opt._validate_day_ahead_result_contract(
        {
            "scenario_id": "scenario-x",
            "prepared_input_id": "prep-x",
            "scope": {"serviceId": "WEEKDAY", "depotId": "dep-1"},
        },
        scenario_id="scenario-x",
        prepared_input_id="prep-x",
        service_id="WEEKDAY",
        depot_id="dep-1",
    )


def test_day_ahead_contract_rejects_different_prepared_input() -> None:
    with pytest.raises(ValueError, match="prepared input mismatch"):
        opt._validate_day_ahead_result_contract(
            {
                "scenario_id": "scenario-x",
                "prepared_input_id": "old-prep",
                "scope": {"serviceId": "WEEKDAY", "depotId": "dep-1"},
            },
            scenario_id="scenario-x",
            prepared_input_id="prep-x",
            service_id="WEEKDAY",
            depot_id="dep-1",
        )


def test_day_ahead_hourly_result_preserves_assignment_for_next_update(
    monkeypatch,
) -> None:
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
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="scenario-x", timestep_min=60),
        dispatch_context=DispatchContext(
            service_date="2025-08-05",
            trips=[dispatch_trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
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
                energy_kwh=30.0,
            ),
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
    )
    canonical_day_ahead = {
        "duties": [
            {
                "duty_id": "duty-1",
                "vehicle_type": "BEV",
                "trip_ids": ["t1"],
            }
        ],
        "served_trip_ids": ["t1"],
        "unserved_trip_ids": [],
        "metadata": {"duty_vehicle_map": {"duty-1": "veh-1"}},
    }
    stored_fields: dict[str, object] = {
        "optimization_result": {
            "scenario_id": "scenario-x",
            "prepared_input_id": "prep-x",
            "scope": {"serviceId": "WEEKDAY", "depotId": "dep-1"},
            "canonical_solver_result": canonical_day_ahead,
        }
    }
    hourly_calls: list[AssignmentPlan] = []

    class _FakeBuilder:
        def build_from_scenario(
            self, scenario, depot_id, service_id, config, planning_days=1
        ):
            return problem

    class _FakeRollingReoptimizer:
        def reoptimize_charging_hour(self, problem, day_ahead_plan, *args, **kwargs):
            hourly_calls.append(day_ahead_plan)
            return object()

    monkeypatch.setattr(
        opt.store,
        "get_scenario_document_shallow",
        lambda scenario_id: {"scenario_id": scenario_id},
    )
    monkeypatch.setattr(
        opt.store,
        "get_field",
        lambda scenario_id, field: stored_fields.get(field),
    )
    monkeypatch.setattr(
        opt.store,
        "set_field",
        lambda scenario_id, field, value: stored_fields.__setitem__(field, value),
    )
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
    monkeypatch.setattr(
        opt.ResultSerializer,
        "serialize_result",
        staticmethod(lambda result: {"objective_value": 0.0}),
    )
    monkeypatch.setattr(opt, "_git_sha", lambda: "test-sha")
    body_payload = {
        "mode": "hybrid",
        "current_time": "00:00",
        "reoptimization_strategy": "day_ahead_hourly",
    }

    for index in range(2):
        opt._run_reoptimization(
            scenario_id="scenario-x",
            job_id=f"job-{index}",
            body_payload=body_payload,
            prepared_input_id="prep-x",
            service_id="WEEKDAY",
            depot_id="dep-1",
        )

    assert len(hourly_calls) == 2
    latest = stored_fields["optimization_result"]
    assert isinstance(latest, dict)
    assert latest["canonical_solver_result"] == canonical_day_ahead
    assert latest["prepared_input_id"] == "prep-x"
    assert latest["scope"] == {"serviceId": "WEEKDAY", "depotId": "dep-1"}
