from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    Trip,
    TurnaroundRule,
    VehicleProfile,
)
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import (
    OptimizationConfig,
    OptimizationMode,
    ProblemTrip,
)
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import (
    _acyclic_flow_requires_path_start,
    _add_stage1_activation_start_strengthening,
    _best_objective_stop_from_certified_lower_bound,
    _configured_gurobi_feasibility_tol,
    _configured_gurobi_integrality_tol,
    _configured_gurobi_threads,
    _configured_stage1_gurobi_scale_flag,
    _configured_stage1_gurobi_search_controls,
    _has_exact_mip_optimality_certificate,
    _iter_assignment_path_incompatibility_pairs,
    _single_path_flow_implies_temporal_exclusivity,
    _stage1_numeric_coefficient_diagnostic,
    _stage1_termination_reason,
    _stage1_root_lp_diagnostic,
)
from src.optimization.engine import OptimizationEngine


def test_exact_mip_optimality_requires_zero_certified_gap() -> None:
    assert _has_exact_mip_optimality_certificate("optimal", 0.0) is True
    assert _has_exact_mip_optimality_certificate("optimal", 1.0e-9) is True
    assert _has_exact_mip_optimality_certificate("optimal", 0.0475) is False
    assert _has_exact_mip_optimality_certificate("objective_limit", 0.0) is False
    assert _has_exact_mip_optimality_certificate("optimal", None) is False


def test_acyclic_flow_requires_path_start_rejects_nonchronological_arc() -> None:
    trips = {
        "early": SimpleNamespace(departure_min=100),
        "late": SimpleNamespace(departure_min=200),
    }

    assert _acyclic_flow_requires_path_start(
        arc_pairs=(("bus", "early", "late"),),
        trip_by_id=trips,
    ) is True
    assert _acyclic_flow_requires_path_start(
        arc_pairs=(("bus", "late", "early"),),
        trip_by_id=trips,
    ) is False


def test_assignment_path_incompatibility_pairs_require_no_direct_or_reset_path() -> None:
    pairs = list(
        _iter_assignment_path_incompatibility_pairs(
            assignment_trip_ids_by_vehicle={
                "bus": ("early", "orphan", "middle", "late", "tomorrow")
            },
            direct_arc_pairs=(("bus", "early", "middle"),),
            reset_arc_pairs_by_vehicle={"bus": (("middle", "late"),)},
            trip_order_key_by_id={
                "early": (0, 100, 120, "early"),
                "orphan": (0, 150, 170, "orphan"),
                "middle": (0, 200, 220, "middle"),
                "late": (0, 300, 320, "late"),
                "tomorrow": (1, 100, 120, "tomorrow"),
            },
            trip_day_index_by_trip_id={
                "early": 0,
                "orphan": 0,
                "middle": 0,
                "late": 0,
                "tomorrow": 1,
            },
        )
    )

    assert pairs == [
        ("bus", "early", "orphan"),
        ("bus", "orphan", "middle"),
        ("bus", "orphan", "late"),
    ]


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_activation_start_strengthening_adds_only_certified_labelled_rows() -> None:
    from src.gurobi_runtime import ensure_gurobi

    gp, grb = ensure_gurobi()
    model = gp.Model("activation_start_strengthening")
    model.Params.OutputFlag = 0
    assigned = model.addVar(vtype=grb.BINARY, name="assign__bus__trip")
    start = model.addVar(vtype=grb.BINARY, name="start__bus__trip")
    used = model.addVar(vtype=grb.BINARY, name="used__bus")
    clone_used = model.addVar(vtype=grb.BINARY, name="used__clone")
    model.addConstr(assigned == start)
    model.addConstr(used == assigned)
    model.addConstr(clone_used == 0)
    model.setObjective(used, grb.MINIMIZE)

    audit = _add_stage1_activation_start_strengthening(
        model=model,
        gp=gp,
        requested=True,
        used_vehicle_vars={"bus": used, "clone": clone_used},
        path_start_vars={("bus", "trip"): start},
        exact_clone_vehicle_ids={"clone"},
        acyclic_flow_requires_path_start_certificate=True,
    )

    assert audit["applied"] is True
    assert audit["constraint_count"] == 1
    assert audit["eligible_vehicle_count"] == 1
    assert audit["excluded_exact_clone_vehicle_count"] == 1
    assert audit["integer_feasible_set_preserved"] is True
    model.optimize()
    assert model.Status == grb.OPTIMAL

    with pytest.raises(ValueError, match="strictly chronological"):
        _add_stage1_activation_start_strengthening(
            model=model,
            gp=gp,
            requested=True,
            used_vehicle_vars={"bus": used},
            path_start_vars={("bus", "trip"): start},
            acyclic_flow_requires_path_start_certificate=False,
        )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_milp_strict_coverage_metadata_is_exported() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="A",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            )
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="milp-metadata",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=10),
    )

    assert result.solver_metadata["service_coverage_mode"] == "strict"
    assert result.solver_metadata["allow_partial_service"] is False
    assert result.solver_metadata["strict_coverage_enforced"] is True


def test_certified_lower_bound_converts_to_positive_objective_stop() -> None:
    assert _best_objective_stop_from_certified_lower_bound(
        640_000.0,
        0.1,
    ) == pytest.approx(711_111.1111111111)
    assert _best_objective_stop_from_certified_lower_bound(-1.0, 0.1) is None
    assert _best_objective_stop_from_certified_lower_bound(1.0, 1.0) is None


def test_stage1_termination_reason_keeps_best_obj_stop_distinct_from_time_limit() -> None:
    assert _stage1_termination_reason(
        solver_status="objective_limit",
        best_obj_stop_applied=True,
    ) == "best_obj_stop"
    assert _stage1_termination_reason(
        solver_status="objective_limit",
        best_obj_stop_applied=False,
    ) == "objective_limit"
    assert _stage1_termination_reason(
        solver_status="time_limit",
        best_obj_stop_applied=False,
    ) == "time_limit"


def test_explicit_gurobi_threads_must_be_positive() -> None:
    assert _configured_gurobi_threads(OptimizationConfig(gurobi_threads=1)) == 1
    with pytest.raises(ValueError, match="positive integer"):
        _configured_gurobi_threads(OptimizationConfig(gurobi_threads=0))


def test_stage1_gurobi_search_profiles_are_explicit_and_validated() -> None:
    assert _configured_stage1_gurobi_search_controls(OptimizationConfig()) == {
        "profile": "default",
        "mip_focus": 0,
        "heuristics": 0.05,
        "presolve": -1,
        "cuts": -1,
        "root_method": -1,
        "node_method": -1,
        "symmetry": -1,
    }
    assert _configured_stage1_gurobi_search_controls(
        OptimizationConfig(stage1_gurobi_search_profile="bound_focus")
    ) == {
        "profile": "bound_focus",
        "mip_focus": 3,
        "heuristics": 0.05,
        "presolve": 2,
        "cuts": -1,
        "root_method": -1,
        "node_method": -1,
        "symmetry": -1,
    }
    assert _configured_stage1_gurobi_search_controls(
        OptimizationConfig(stage1_gurobi_search_profile="root_cut_focus")
    ) == {
        "profile": "root_cut_focus",
        "mip_focus": 3,
        "heuristics": 0.05,
        "presolve": 2,
        "cuts": 3,
        "root_method": -1,
        "node_method": -1,
        "symmetry": -1,
    }
    with pytest.raises(ValueError, match="stage1_gurobi_search_profile"):
        _configured_stage1_gurobi_search_controls(
            OptimizationConfig(stage1_gurobi_search_profile="unsupported")
        )


def test_stage1_gurobi_scale_flag_is_explicit_and_validated() -> None:
    assert _configured_stage1_gurobi_scale_flag(OptimizationConfig()) == -1
    assert _configured_stage1_gurobi_scale_flag(
        OptimizationConfig(stage1_gurobi_scale_flag=2)
    ) == 2
    with pytest.raises(ValueError, match="stage1_gurobi_scale_flag"):
        _configured_stage1_gurobi_scale_flag(
            OptimizationConfig(stage1_gurobi_scale_flag=4)
        )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_root_lp_diagnostic_reports_fractional_assignment_without_mutating_mip() -> None:
    from src.gurobi_runtime import ensure_gurobi

    gp, grb = ensure_gurobi()
    model = gp.Model("root_lp_diagnostic")
    model.Params.OutputFlag = 0
    assignment = model.addVar(vtype=grb.BINARY, name="assign__bev__trip")
    used = model.addVar(vtype=grb.BINARY, name="used__bev")
    model.addConstr(assignment == 0.5)
    model.addConstr(used == assignment)
    model.setObjective(assignment, grb.MINIMIZE)

    diagnostic = _stage1_root_lp_diagnostic(
        model=model,
        grb=grb,
        assignment_vars={("bev", "trip"): assignment},
        used_vehicle_vars={"bev": used},
        vehicle_type_by_id={"bev": "BEV"},
        time_limit_sec=5,
        threads=2,
    )

    assert diagnostic["status"] == "optimal"
    assert diagnostic["solver_controls"] == {
        "method": 2,
        "method_name": "barrier",
        "crossover": -1,
        "crossover_name": "automatic",
        "threads": 2,
    }
    assert diagnostic["solution_quality"]["max_unscaled_violation"] <= 1.0e-6
    assert (
        diagnostic["solution_quality"]["max_unscaled_constraint_violation"]
        <= 1.0e-6
    )
    assert diagnostic["quality_assessment"][
        "primal_quality_within_configured_tolerance"
    ] is True
    assert diagnostic["objective_jpy"] == pytest.approx(0.5)
    assert diagnostic["assignment_summary"]["fractional_assignment_variable_count"] == 1
    assert diagnostic["assignment_summary"]["trips_split_across_multiple_vehicle_labels"] == 0
    assert diagnostic["vehicle_activation_summary"]["fractional_activation_count"] == 1
    assert model.NumBinVars == 2


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_root_lp_diagnostic_reports_exclusive_trip_set_violations_read_only() -> None:
    from src.gurobi_runtime import ensure_gurobi

    gp, grb = ensure_gurobi()
    model = gp.Model("root_lp_exclusive_trip_set_diagnostic")
    model.Params.OutputFlag = 0
    first_assignment = model.addVar(vtype=grb.BINARY, name="assign__bus__first")
    second_assignment = model.addVar(vtype=grb.BINARY, name="assign__bus__second")
    used = model.addVar(vtype=grb.BINARY, name="used__bus")
    model.addConstr(first_assignment == 0.75)
    model.addConstr(second_assignment == 0.75)
    model.addConstr(used == 1)
    model.setObjective(first_assignment + second_assignment, grb.MINIMIZE)

    diagnostic = _stage1_root_lp_diagnostic(
        model=model,
        grb=grb,
        assignment_vars={
            ("bus", "first"): first_assignment,
            ("bus", "second"): second_assignment,
        },
        used_vehicle_vars={"bus": used},
        vehicle_type_by_id={"bus": "ICE"},
        mutually_exclusive_trip_sets=(("first", "second"),),
        time_limit_sec=5,
        threads=2,
    )

    summary = diagnostic["mutually_exclusive_trip_set_summary"]
    assert summary["enabled"] is True
    assert summary["maximal_trip_set_count"] == 1
    assert summary["checked_vehicle_trip_set_pairs"] == 1
    assert summary["violated_vehicle_trip_set_count"] == 1
    assert summary["maximum_assignment_mass"] == pytest.approx(1.5)
    assert summary["maximum_assignment_mass_excess"] == pytest.approx(0.5)
    assert summary["violation_sample"] == [
        {
            "vehicle_id": "bus",
            "trip_ids": ["first", "second"],
            "assignment_mass": pytest.approx(1.5),
            "excess": pytest.approx(0.5),
        }
    ]
    assert model.NumBinVars == 3


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_root_lp_diagnostic_reports_path_incompatibility_violations_read_only() -> None:
    from src.gurobi_runtime import ensure_gurobi

    gp, grb = ensure_gurobi()
    model = gp.Model("root_lp_path_incompatibility_diagnostic")
    model.Params.OutputFlag = 0
    first_assignment = model.addVar(vtype=grb.BINARY, name="assign__bus__first")
    second_assignment = model.addVar(vtype=grb.BINARY, name="assign__bus__second")
    used = model.addVar(vtype=grb.BINARY, name="used__bus")
    model.addConstr(first_assignment == 0.75)
    model.addConstr(second_assignment == 0.75)
    model.addConstr(used == 1)
    model.setObjective(first_assignment + second_assignment, grb.MINIMIZE)

    diagnostic = _stage1_root_lp_diagnostic(
        model=model,
        grb=grb,
        assignment_vars={
            ("bus", "first"): first_assignment,
            ("bus", "second"): second_assignment,
        },
        used_vehicle_vars={"bus": used},
        vehicle_type_by_id={"bus": "ICE"},
        assignment_path_incompatible_pairs=(("bus", "first", "second"),),
        time_limit_sec=5,
        threads=2,
    )

    summary = diagnostic["assignment_path_incompatibility_summary"]
    assert summary["enabled"] is True
    assert summary["candidate_pair_count"] == 1
    assert summary["checked_assignment_pair_count"] == 1
    assert summary["violated_assignment_pair_count"] == 1
    assert summary["evaluation_wall_seconds"] >= 0.0
    assert summary["maximum_assignment_mass"] == pytest.approx(1.5)
    assert summary["maximum_assignment_mass_excess"] == pytest.approx(0.5)
    assert summary["violation_sample"] == [
        {
            "vehicle_id": "bus",
            "trip_ids": ["first", "second"],
            "assignment_mass": pytest.approx(1.5),
            "excess": pytest.approx(0.5),
        }
    ]
    assert model.NumBinVars == 3


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_root_lp_diagnostic_reports_activation_start_deficit_read_only() -> None:
    from src.gurobi_runtime import ensure_gurobi

    gp, grb = ensure_gurobi()
    model = gp.Model("root_lp_activation_start_diagnostic")
    model.Params.OutputFlag = 0
    assignment = model.addVar(vtype=grb.BINARY, name="assign__bus__trip")
    start = model.addVar(vtype=grb.BINARY, name="start__bus__trip")
    used = model.addVar(vtype=grb.BINARY, name="used__bus")
    model.addConstr(assignment == 0.5)
    model.addConstr(start == 0.25)
    model.addConstr(used == 1)
    model.setObjective(assignment, grb.MINIMIZE)

    diagnostic = _stage1_root_lp_diagnostic(
        model=model,
        grb=grb,
        assignment_vars={("bus", "trip"): assignment},
        used_vehicle_vars={"bus": used},
        vehicle_type_by_id={"bus": "ICE"},
        path_start_vars={("bus", "trip"): start},
        path_start_count_limit=1,
        acyclic_flow_requires_path_start_certificate=True,
        time_limit_sec=5,
        threads=2,
    )

    summary = diagnostic["activation_start_summary"]
    assert summary["enabled"] is True
    assert summary["acyclic_flow_requires_path_start_certificate"] is True
    assert summary["path_start_count_limit"] == 1
    assert summary["checked_vehicle_count"] == 1
    assert summary["excluded_vehicle_count"] == 0
    assert summary["activation_start_deficit_count"] == 1
    assert summary["maximum_activation_start_deficit"] == pytest.approx(0.75)
    assert summary["deficit_sample"] == [
        {
            "vehicle_id": "bus",
            "used_vehicle_value": pytest.approx(1.0),
            "path_start_mass": pytest.approx(0.25),
            "deficit": pytest.approx(0.75),
        }
    ]
    assert model.NumBinVars == 3


def test_numeric_coefficient_diagnostic_locates_smallest_matrix_row_read_only() -> None:
    class _Variable:
        def __init__(self, name: str) -> None:
            self.VarName = name

    class _Row:
        def __init__(self, entries: list[tuple[_Variable, float]]) -> None:
            self._entries = entries

        def size(self) -> int:
            return len(self._entries)

        def getCoeff(self, index: int) -> float:
            return self._entries[index][1]

        def getVar(self, index: int) -> _Variable:
            return self._entries[index][0]

    class _Constraint:
        def __init__(self, name: str, rhs: float) -> None:
            self.ConstrName = name
            self.Sense = "="
            self.RHS = rhs

    class _Model:
        def __init__(self) -> None:
            self.updated = False
            self._first = _Constraint("energy_balance", 0.0)
            self._second = _Constraint("soc_link", 1.0)
            self._rows = {
                self._first: _Row(
                    [(_Variable("charge_kw"), 1450.0), (_Variable("loss"), 1.0e-6)]
                ),
                self._second: _Row(
                    [(_Variable("soc"), -1.0e-7), (_Variable("reserve"), 1.0e-7)]
                ),
            }

        def update(self) -> None:
            self.updated = True

        def getConstrs(self) -> list[_Constraint]:
            return [self._first, self._second]

        def getRow(self, constraint: _Constraint) -> _Row:
            return self._rows[constraint]

    model = _Model()

    diagnostic = _stage1_numeric_coefficient_diagnostic(
        model,
        max_examples=1,
    )

    assert model.updated is True
    assert diagnostic["status"] == "ok"
    assert diagnostic["scanned_constraint_count"] == 2
    assert diagnostic["scanned_nonzero_coefficient_count"] == 4
    assert diagnostic["minimum_absolute_coefficient"] == pytest.approx(1.0e-7)
    assert diagnostic["maximum_absolute_coefficient"] == pytest.approx(1450.0)
    assert diagnostic["minimum_coefficient_examples"] == [
        {
            "constraint_name": "soc_link",
            "constraint_sense": "=",
            "constraint_rhs": 1.0,
            "variable_name": "soc",
            "coefficient": -1.0e-7,
            "absolute_coefficient": 1.0e-7,
        }
    ]


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_numeric_coefficient_diagnostic_reads_actual_gurobi_constraint_rows() -> None:
    from src.gurobi_runtime import ensure_gurobi

    gp, _ = ensure_gurobi()
    model = gp.Model("numeric_coefficient_diagnostic")
    model.Params.OutputFlag = 0
    variable = model.addVar(name="charge_kw")
    model.addConstr(1.0e-6 * variable <= 1.0, name="small_coefficient")
    model.addConstr(4.0 * variable <= 4.0, name="ordinary_coefficient")
    model.update()

    diagnostic = _stage1_numeric_coefficient_diagnostic(model)

    assert diagnostic["status"] == "ok"
    assert diagnostic["minimum_absolute_coefficient"] == pytest.approx(1.0e-6)
    assert diagnostic["maximum_absolute_coefficient"] == pytest.approx(4.0)
    assert diagnostic["minimum_coefficient_examples"] == [
        {
            "constraint_name": "small_coefficient",
            "constraint_sense": "<",
            "constraint_rhs": 1.0,
            "variable_name": "charge_kw",
            "coefficient": 1.0e-6,
            "absolute_coefficient": 1.0e-6,
        }
    ]
    assert model.NumVars == 1
    assert model.NumConstrs == 2


def test_gurobi_feasibility_tolerances_are_stage_specific_and_validated() -> None:
    config = OptimizationConfig()
    assert _configured_gurobi_feasibility_tol(
        config, stage=1
    ) == pytest.approx(1.0e-6)
    assert _configured_gurobi_feasibility_tol(
        config, stage=2
    ) == pytest.approx(1.0e-9)

    with pytest.raises(ValueError, match=r"\[1e-9, 1e-2\]"):
        _configured_gurobi_feasibility_tol(
            OptimizationConfig(stage2_gurobi_feasibility_tol=1.0e-10),
            stage=2,
        )


def test_stage2_gurobi_integrality_tolerance_is_strict_and_validated() -> None:
    assert _configured_gurobi_integrality_tol(
        OptimizationConfig(),
        stage=2,
    ) == pytest.approx(1.0e-9)

    with pytest.raises(ValueError, match=r"\[1e-9, 1e-1\]"):
        _configured_gurobi_integrality_tol(
            OptimizationConfig(stage2_gurobi_integrality_tol=1.0e-10),
            stage=2,
        )
    with pytest.raises(ValueError, match="stage must be 2"):
        _configured_gurobi_integrality_tol(
            OptimizationConfig(),
            stage=1,
        )


def test_single_path_redundancy_requires_strictly_forward_arcs() -> None:
    trip_by_id = {
        "t1": ProblemTrip(
            trip_id="t1",
            route_id="r",
            origin="A",
            destination="B",
            departure_min=480,
            arrival_min=490,
            distance_km=1.0,
            allowed_vehicle_types=("ICE",),
        ),
        "t2": ProblemTrip(
            trip_id="t2",
            route_id="r",
            origin="B",
            destination="C",
            departure_min=500,
            arrival_min=510,
            distance_km=1.0,
            allowed_vehicle_types=("ICE",),
        ),
        "same": ProblemTrip(
            trip_id="same",
            route_id="r",
            origin="B",
            destination="C",
            departure_min=480,
            arrival_min=490,
            distance_km=1.0,
            allowed_vehicle_types=("ICE",),
        ),
    }
    assert _single_path_flow_implies_temporal_exclusivity(
        max_start_fragments_per_vehicle=1,
        max_end_fragments_per_vehicle=1,
        arc_pairs=(("v", "t1", "t2"),),
        trip_by_id=trip_by_id,
    ) is True
    assert _single_path_flow_implies_temporal_exclusivity(
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=1,
        arc_pairs=(("v", "t1", "t2"),),
        trip_by_id=trip_by_id,
    ) is False
    assert _single_path_flow_implies_temporal_exclusivity(
        max_start_fragments_per_vehicle=1,
        max_end_fragments_per_vehicle=1,
        arc_pairs=(("v", "t1", "same"),),
        trip_by_id=trip_by_id,
    ) is False


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_path_cover_lower_bound_reaches_vehicle_day_cost_bound() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id=trip_id,
                route_id="r1",
                origin="DEPOT",
                destination=destination,
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            )
            for trip_id, destination in (("t1", "A"), ("t2", "B"))
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="stage1-lower-bound",
        vehicle_counts={"ICE": 2},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )
    problem = replace(
        problem,
        metadata={
            **dict(problem.metadata or {}),
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
            "cost_component_flags": {
                "vehicle_usage_cost": True,
                # Isolate the path-cover vehicle-day certificate. Phase 3 now
                # includes enabled driver cost in the Stage 1 objective.
                "driver_cost": False,
            },
        },
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase2_assignment_only",
            time_limit_sec=10,
            mip_gap=0.0,
        ),
    )

    assert result.solver_metadata["stage1_vehicle_count_lower_bound"] == 2
    assert result.solver_metadata[
        "stage1_vehicle_count_lower_bound_constraint_count"
    ] == 1
    assert result.solver_metadata["stage1_best_bound"] == pytest.approx(40_000.0)
    assert result.solver_metadata[
        "stage1_analytical_objective_lower_bound"
    ] == pytest.approx(40_000.0)
    assert result.solver_metadata[
        "stage1_analytical_objective_lower_bound_semantics"
    ] == (
        "sum_of_strict_path_cover_vehicle_usage_cost_floor_"
        "and_optimistic_weather_energy_fuel_cost_floor"
    )
    assert result.solver_metadata[
        "stage1_vehicle_usage_analytical_lower_bound"
    ] == pytest.approx(40_000.0)
    assert result.solver_metadata[
        "stage1_analytical_weather_energy_fuel_lower_bound"
    ] == pytest.approx(0.0)
    assert (
        result.solver_metadata[
            "stage1_analytical_total_objective_certificate_eligible"
        ]
        is True
    )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_exact_bev_activation_count_policy_is_enforced() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id=trip_id,
                route_id="r1",
                origin="DEPOT",
                destination=destination,
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("BEV",),
            )
            for trip_id, destination in (("t1", "A"), ("t2", "B"))
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="stage1-exact-bev-activation-count",
        vehicle_counts={"BEV": 3},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )
    unmarked_problem = replace(
        problem,
        metadata={
            **dict(problem.metadata or {}),
            "minimum_used_bev_count": 2,
            "phase4_seed_route_band_repartition_"
            "maximum_used_vehicle_count": 2,
        },
    )
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase2_assignment_only",
        time_limit_sec=10,
        mip_gap=0.0,
    )
    with pytest.raises(
        ValueError,
        match="only for an explicit Phase-4 seed candidate",
    ):
        OptimizationEngine().solve(unmarked_problem, config)

    problem = replace(
        unmarked_problem,
        metadata={
            **dict(unmarked_problem.metadata or {}),
            "phase4_seed_route_band_repartition_candidate": True,
        },
    )

    result = OptimizationEngine().solve(
        problem,
        config,
    )

    assert result.feasible is True
    assert len(result.plan.duties_by_vehicle()) == 2
    assert result.plan.metadata["minimum_used_bev_count"] == 2
    assert result.plan.metadata[
        "phase4_seed_route_band_repartition_maximum_used_vehicle_count"
    ] == 2
    assert result.plan.metadata[
        "phase4_seed_route_band_repartition_"
        "maximum_used_vehicle_count_policy_enabled"
    ] is True


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_omits_arc_links_implied_by_node_flow_equalities() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="A",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="A",
                destination="DEPOT",
                departure_time="08:20",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={"A": TurnaroundRule(stop_id="A", min_turnaround_min=0)},
        deadhead_rules={},
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="stage1-redundant-arc-links",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase2_assignment_only",
            time_limit_sec=10,
            mip_gap=0.0,
        ),
    )

    assert result.feasible is True
    assert set(result.plan.served_trip_ids) == {"t1", "t2"}
    assert result.solver_metadata[
        "stage1_redundant_arc_link_constraints_omitted"
    ] == 2
    assert result.solver_metadata["stage1_model_variable_count"] > 0
    assert result.solver_metadata["stage1_model_constraint_count"] > 0
    assert result.solver_metadata["stage1_model_binary_variable_count"] >= 0
    assert result.solver_metadata["stage1_model_integer_variable_count"] >= 0
    assert result.solver_metadata["stage1_model_continuous_variable_count"] >= 0
    assert result.solver_metadata["stage1_model_nonzero_coefficient_count"] > 0
    assert result.solver_metadata["stage1_pre_optimize_seconds"] >= 0.0
    assert result.solver_metadata[
        "stage1_single_path_redundancy_elimination_applied"
    ] is True
    assert result.solver_metadata["assignment_solution_method"] == (
        "full_candidate_network_stage1_milp"
    )
    assert result.solver_metadata["assignment_global_optimality"] is (
        result.solver_metadata["stage1_solver_status"] == "optimal"
        and result.solver_metadata["stage1_mip_gap_ratio"] <= 1.0e-8
    )
    assert result.solver_metadata["assignment_global_optimality_scope"] == (
        "full_candidate_network_stage1_assignment_objective"
    )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_integrated_omits_arc_links_implied_by_node_flow_equalities() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="A",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="B",
                destination="DEPOT",
                departure_time="08:20",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={"A": TurnaroundRule(stop_id="A", min_turnaround_min=0)},
        deadhead_rules={
            ("A", "B"): DeadheadRule(
                from_stop="A",
                to_stop="B",
                travel_time_min=5,
            )
        },
        vehicle_profiles={
            "ICE": VehicleProfile(
                vehicle_type="ICE",
                fuel_tank_capacity_l=300.0,
                fuel_consumption_l_per_km=0.2,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="integrated-redundant-arc-links",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            time_limit_sec=10,
            mip_gap=0.0,
            warm_start=False,
        ),
    )

    assert result.feasible is True
    assert set(result.plan.served_trip_ids) == {"t1", "t2"}
    assert result.solver_metadata[
        "integrated_redundant_arc_link_constraints_omitted"
    ] == 2
    assert result.solver_metadata[
        "integrated_activity_blocking_formulation"
    ] == "pairwise_strong_lp"
    assert result.solver_metadata[
        "integrated_activity_blocking_constraint_count"
    ] > 0
    assert result.solver_metadata[
        "integrated_redundant_endpoint_away_blocking_terms_omitted"
    ] == 1
    assert result.solver_metadata[
        "integrated_redundant_endpoint_away_blocking_semantics"
    ].startswith("lp_dominance_only")
