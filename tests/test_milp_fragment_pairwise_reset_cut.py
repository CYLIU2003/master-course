from __future__ import annotations

import pytest

from src.dispatch.models import DeadheadRule, DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_milp_fragment_pairwise_reset_cut_blocks_impossible_two_fragment_reuse() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="milp-reset-cut",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            time_limit_sec=10,
            mip_gap=0.0,
            phase="phase3_two_stage",
        ),
    )

    assert result.feasible is False
    assert result.plan.unserved_trip_ids == ("t1", "t2")
    assert (
        result.plan.metadata["fragment_pairwise_depot_reset_constraint_count"]
        == 0
    )
    assert (
        result.plan.metadata["fragment_pairwise_depot_reset_constraint_mode"]
        == "lazy_integer_incumbent_separation"
    )
    separator = result.plan.metadata["fragment_transition_lazy_separator"]
    assert separator["enabled"] is True
    assert separator["callback_error"] is None
    assert separator["explicit_pairwise_rows_materialized"] == 0
    assert (
        result.solver_metadata[
            "fragment_pairwise_depot_reset_constraint_mode"
        ]
        == "lazy_integer_incumbent_separation"
    )
    assert result.solver_metadata[
        "fragment_transition_lazy_separator"
    ] == separator


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_fragment_transition_lazy_separator_adds_exact_invalid_pair_cut() -> None:
    import gurobipy as gp

    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="lazy-reset-cut",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        service_coverage_mode="strict",
    )
    vehicle_id = problem.vehicles[0].vehicle_id
    model = gp.Model("lazy_reset_cut")
    model.Params.OutputFlag = 0
    model.Params.LazyConstraints = 1
    end_t1 = model.addVar(vtype=gp.GRB.BINARY, name="end_t1")
    start_t2 = model.addVar(vtype=gp.GRB.BINARY, name="start_t2")
    model.addConstr(end_t1 == 1)
    model.addConstr(start_t2 == 1)
    separator = GurobiMILPAdapter()._build_fragment_transition_lazy_separator(
        grb=gp.GRB,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        start_arc={(vehicle_id, "t2"): start_t2},
        end_arc={(vehicle_id, "t1"): end_t1},
        trip_day_index_by_trip_id={"t1": 0, "t2": 0},
        allow_same_day_depot_cycles=True,
        fixed_route_band_mode=False,
    )

    separator.begin_solve()
    model.optimize(separator.callback)

    assert separator.callback_error == ""
    assert separator.lazy_constraint_count == 1
    assert model.Status == gp.GRB.INFEASIBLE
    metadata = separator.to_metadata()
    assert metadata["integer_feasible_set_preserved"] is True
    assert metadata["explicit_pairwise_rows_materialized"] == 0


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_fragment_transition_root_user_cut_adds_only_a_violated_exact_row() -> None:
    """Fractional-node cuts use the same valid row as lazy incumbents."""
    import gurobipy as gp

    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="root-user-cut",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        service_coverage_mode="strict",
    )
    vehicle_id = problem.vehicles[0].vehicle_id
    model = gp.Model("root_user_cut")
    model.Params.OutputFlag = 0
    end_t1 = model.addVar(vtype=gp.GRB.BINARY, name="end_t1")
    start_t2 = model.addVar(vtype=gp.GRB.BINARY, name="start_t2")
    separator = GurobiMILPAdapter()._build_fragment_transition_lazy_separator(
        grb=gp.GRB,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        start_arc={(vehicle_id, "t2"): start_t2},
        end_arc={(vehicle_id, "t1"): end_t1},
        trip_day_index_by_trip_id={"t1": 0, "t2": 0},
        allow_same_day_depot_cycles=True,
        fixed_route_band_mode=False,
        root_user_cuts=True,
    )

    class FakeMipNode:
        def __init__(self) -> None:
            self.cuts: list[object] = []

        def cbGet(self, _attribute: int) -> int:
            return gp.GRB.OPTIMAL

        def cbGetNodeRel(self, variables: list[object]) -> list[float]:
            return [0.75] * len(variables)

        def cbCut(self, constraint: object) -> None:
            self.cuts.append(constraint)

    callback_model = FakeMipNode()
    added = separator.separate_mipnode(
        callback_model,
        gp.GRB.Callback.MIPNODE,
    )

    assert added == 1
    assert len(callback_model.cuts) == 1
    metadata = separator.to_metadata()
    assert metadata["root_user_cuts_enabled"] is True
    assert metadata["root_user_cut_count"] == 1
    assert metadata["lazy_constraint_count"] == 0


def test_fragment_transition_lazy_separator_fails_closed_on_callback_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.optimization.milp import solver_adapter as adapter_module

    separator = object.__new__(
        adapter_module._FragmentTransitionLazySeparator
    )
    separator.callback_error = ""

    def raise_callback_error(_model: object, _where: int) -> int:
        raise RuntimeError("diagnostic failed")

    monkeypatch.setattr(
        separator,
        "separate_mipsol",
        raise_callback_error,
    )

    class FakeCallbackModel:
        terminated = False

        def terminate(self) -> None:
            self.terminated = True

    model = FakeCallbackModel()

    assert separator.callback(model, 0) == 0
    assert model.terminated is True
    assert separator.callback_error == "RuntimeError: diagnostic failed"


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_explicit_root_fragment_cuts_preserve_the_two_fragment_infeasibility() -> None:
    """The explicit-root representation must match the lazy integer contract."""
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip("t1", "r1", "A", "B", "08:00", "08:10", 1.0, ("ICE",)),
            Trip("t2", "r1", "C", "D", "08:30", "08:40", 1.0, ("ICE",)),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="explicit-root-reset-cut",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            time_limit_sec=10,
            mip_gap=0.0,
            phase="phase3_two_stage",
            stage1_fragment_transition_cut_mode="explicit_root",
        ),
    )

    assert result.feasible is False
    assert result.plan.unserved_trip_ids == ("t1", "t2")
    assert result.plan.metadata["fragment_pairwise_depot_reset_constraint_count"] == 1
    assert (
        result.plan.metadata["fragment_pairwise_depot_reset_constraint_mode"]
        == "explicit_root_relaxation_strengthening"
    )
    separator = result.plan.metadata["fragment_transition_lazy_separator"]
    assert separator["enabled"] is False
    assert separator["explicit_pairwise_rows_materialized"] == 1
    assert separator["integer_feasible_set_preserved"] is True


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_phase4_uses_lazy_fragment_separator_for_valid_depot_cycle() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
            ("D", "DEPOT"): DeadheadRule("D", "DEPOT", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="phase4-valid-lazy-reset",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=10,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
            research_run=True,
        ),
    )

    assert result.feasible, result.solver_status
    plan = result.plan
    assert plan.unserved_trip_ids == ()
    assert plan.metadata["integrated_fragment_pairwise_constraint_count"] == 0
    assert (
        plan.metadata["integrated_fragment_pairwise_constraint_mode"]
        == "lazy_integer_incumbent_separation"
    )
    separator = plan.metadata[
        "integrated_fragment_transition_lazy_separator"
    ]
    assert separator["enabled"] is True
    assert separator["mipsol_callback_count"] >= 1
    assert separator["callback_error"] is None
    assert result.solver_metadata[
        "integrated_fragment_pairwise_constraint_count"
    ] == 0
    assert (
        result.solver_metadata[
            "integrated_fragment_pairwise_constraint_mode"
        ]
        == "lazy_integer_incumbent_separation"
    )
    assert result.solver_metadata[
        "integrated_fragment_transition_lazy_separator"
    ] == separator


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_milp_blocks_nested_fragments_inside_selected_connection_span() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                route_family_code="band-1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r2",
                route_family_code="band-2",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t3",
                route_id="r1",
                route_family_code="band-1",
                origin="E",
                destination="F",
                departure_time="09:00",
                arrival_time="09:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
            ("DEPOT", "E"): DeadheadRule("DEPOT", "E", 5),
            ("B", "E"): DeadheadRule("B", "E", 5),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 5),
            ("D", "DEPOT"): DeadheadRule("D", "DEPOT", 5),
            ("F", "DEPOT"): DeadheadRule("F", "DEPOT", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="nested-fragment-cut",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        fixed_route_band_mode=True,
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            time_limit_sec=10,
            mip_gap=0.0,
            phase="phase3_two_stage",
        ),
    )

    assert result.feasible is False
    assert result.plan.unserved_trip_ids == ("t1", "t2", "t3")
    telemetry = result.plan.metadata["stage1_search_telemetry"]
    assert telemetry["schema_version"] == "stage1_search_telemetry_v1"
    assert telemetry["callback_error"] is None
    assert telemetry["final"]["solution_count"] == 0
    assert result.solver_metadata["stage1_search_telemetry"] == telemetry


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_fragment_reset_cuts_cache_diagnostic_but_keep_per_vehicle_cuts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache only the repeated diagnosis, never the vehicle-specific cut."""
    import gurobipy as gp
    from src.optimization.milp import solver_adapter as adapter_module

    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="cached-reset-cut",
        vehicle_counts={"ICE": 2},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )
    model = gp.Model("cached_reset_cut")
    model.Params.OutputFlag = 0
    vehicle_ids = tuple(vehicle.vehicle_id for vehicle in problem.vehicles)
    end_arc = {
        (vehicle_id, trip.trip_id): model.addVar(vtype=gp.GRB.BINARY)
        for vehicle_id in vehicle_ids
        for trip in problem.trips
    }
    start_arc = {
        (vehicle_id, trip.trip_id): model.addVar(vtype=gp.GRB.BINARY)
        for vehicle_id in vehicle_ids
        for trip in problem.trips
    }
    calls = 0
    original = adapter_module.fragment_transition_diagnostic

    def counted_diagnostic(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "fragment_transition_diagnostic", counted_diagnostic)
    cut_count = GurobiMILPAdapter()._add_fragment_pairwise_depot_reset_cuts(
        model,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={
            vehicle_id: ["t1", "t2"] for vehicle_id in vehicle_ids
        },
        start_arc=start_arc,
        end_arc=end_arc,
        trip_day_index_by_trip_id={"t1": 0, "t2": 0},
        problem=problem,
        allow_same_day_depot_cycles=True,
        fixed_route_band_mode=False,
    )

    assert calls == 1
    assert cut_count == 2
    lifted_count = GurobiMILPAdapter()._add_fragment_lifted_depot_reset_cuts(
        model,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={
            vehicle_id: ["t1", "t2"] for vehicle_id in vehicle_ids
        },
        start_arc=start_arc,
        end_arc=end_arc,
        trip_day_index_by_trip_id={"t1": 0, "t2": 0},
        problem=problem,
        allow_same_day_depot_cycles=True,
        fixed_route_band_mode=False,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
    )
    assert lifted_count == 4
