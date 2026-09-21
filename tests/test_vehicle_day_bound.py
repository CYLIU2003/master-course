from dataclasses import replace
import pytest

from src.optimization.common.vehicle_day_bound import vehicle_day_overlap_lower_bounds, vehicle_day_path_cover_lower_bounds
from test_daily_return_policy import daily_problem


def trip(name, start, end):
    return replace(daily_problem().trips[0], trip_id=name, departure_min=start, arrival_min=end)


def test_daily_overlap_bound_counts_vehicle_days_and_arrival_departure_ties():
    trips = [trip("a", 10, 20), trip("b", 15, 25), trip("c", 20, 30),
             trip("d", 1450, 1460)]
    assert vehicle_day_overlap_lower_bounds(trips, {"a": 0, "b": 0, "c": 0, "d": 1}) == {0: 2, 1: 1}


def test_overnight_trip_belongs_to_its_departure_day_cost_bucket():
    trips = [trip("a", 1430, 1460), trip("b", 1440, 1470)]
    assert vehicle_day_overlap_lower_bounds(trips, {"a": 0, "b": 1}) == {0: 1, 1: 1}


def test_invalid_duration_cannot_strengthen_a_certificate():
    with pytest.raises(ValueError, match="positive absolute"):
        vehicle_day_overlap_lower_bounds([trip("a", 10, 10)], {"a": 0})


def test_bounded_presolve_controls_are_exposed_by_api_and_native_configuration():
    from bff.routers.optimization import RunOptimizationBody
    from src.optimization.common.problem import OptimizationConfig
    from src.optimization.milp.solver_adapter import _configured_stage1_gurobi_search_controls
    request = RunOptimizationBody(stage1_gurobi_search_profile="bounded_presolve")
    controls = _configured_stage1_gurobi_search_controls(OptimizationConfig(
        stage1_gurobi_search_profile=request.stage1_gurobi_search_profile))
    assert controls["presolve"] == 1
    assert controls["pre_passes"] == 3
    assert controls["mip_focus"] == 1


def test_daily_path_cover_counts_disconnected_but_nonoverlapping_trips():
    trips = [trip("a", 0, 10), trip("b", 20, 30), trip("c", 40, 50), trip("d", 1450, 1460)]
    days = {"a": 0, "b": 0, "c": 0, "d": 1}
    rows = [("a", ("c", "d")), ("b", ("d",)), ("c", ("d",))]
    assert vehicle_day_overlap_lower_bounds(trips, days) == {0: 1, 1: 1}
    assert vehicle_day_path_cover_lower_bounds(trips, days, rows, full_network=True) == {0: 2, 1: 1}


def test_daily_path_cover_relaxes_vehicle_labels_by_taking_union():
    trips = [trip("a", 0, 10), trip("b", 20, 30), trip("c", 40, 50)]
    days = {"a": 0, "b": 0, "c": 0}
    # Different vehicles supply a->b and b->c. The union's optimistic one-path
    # bound is valid even if no single real vehicle can perform that path.
    rows = [("a", ("b",)), ("a", ("b",)), ("b", ("c",))]
    assert vehicle_day_path_cover_lower_bounds(trips, days, rows, full_network=True) == {0: 1}


def test_daily_path_cover_rejects_pruned_or_backward_graph():
    trips = [trip("a", 0, 10), trip("b", 20, 30)]
    days = {"a": 0, "b": 0}
    with pytest.raises(ValueError, match="complete successor"):
        vehicle_day_path_cover_lower_bounds(trips, days, [], full_network=False)
    with pytest.raises(ValueError, match="acyclic"):
        vehicle_day_path_cover_lower_bounds(trips, days, [("b", ("a",))], full_network=True)


def test_daily_path_cover_rejects_noncontiguous_day_buckets():
    trips = [trip("a", 0, 10), trip("b", 20, 30), trip("c", 40, 50)]
    with pytest.raises(ValueError, match="chronological"):
        vehicle_day_path_cover_lower_bounds(trips, {"a": 0, "b": 1, "c": 0},
                                            [("a", ("b",)), ("b", ("c",))], full_network=True)


def test_path_cover_matches_exhaustive_four_trip_vehicle_assignments():
    from itertools import combinations, product
    trips = [trip(str(i), i * 20, i * 20 + 10) for i in range(4)]
    possible = list(combinations(range(4), 2))
    for flags in product((False, True), repeat=len(possible)):
        edges = {edge for edge, enabled in zip(possible, flags) if enabled}
        best = 4
        for labels in product(range(4), repeat=4):
            paths = [[i for i in range(4) if labels[i] == label] for label in set(labels)]
            if all(all(edge in edges for edge in zip(path, path[1:])) for path in paths):
                best = min(best, len(paths))
        rows = [(str(i), tuple(str(j) for a, j in sorted(edges) if a == i)) for i in range(4)]
        assert vehicle_day_path_cover_lower_bounds(trips, {str(i): 0 for i in range(4)}, rows, full_network=True) == {0: best}


@pytest.mark.parametrize("profile,method,work", [("bounded_presolve_barrier", 2, 0), ("bounded_presolve_barrier_no_crossover", 2, 0), ("bounded_presolve_dual", 1, 0), ("bounded_presolve_norel", 1, 120)])
def test_root_profiles_preserve_bounds_and_have_explicit_memory_limit(profile, method, work):
    from bff.routers.optimization import RunOptimizationBody
    from src.optimization.common.problem import OptimizationConfig
    from src.optimization.milp.solver_adapter import _configured_stage1_gurobi_search_controls
    request = RunOptimizationBody(stage1_gurobi_search_profile=profile)
    controls = _configured_stage1_gurobi_search_controls(OptimizationConfig(stage1_gurobi_search_profile=request.stage1_gurobi_search_profile))
    assert controls["root_method"] == method
    assert controls["no_rel_heur_work"] == work
    assert controls["soft_mem_limit_gb"] == 18


@pytest.mark.parametrize("profile,threads", [
    ("bounded_presolve_barrier", 1), ("bounded_presolve_barrier_no_crossover", 1),
    ("bounded_presolve_dual", 1), ("bounded_presolve_norel", 1),
    ("bounded_presolve_barrier_no_crossover", 2),
])
def test_native_daily_bound_and_effective_search_parameters(profile, threads, tmp_path):
    from src.optimization.milp.engine import MILPOptimizer
    from test_milp_soc_validator_roundtrip import _soc_roundtrip_problem
    from src.optimization.common.problem import OptimizationConfig, OptimizationMode
    problem = _soc_roundtrip_problem()
    problem = replace(problem, metadata={**problem.metadata,
        "stage1_daily_path_cover_bound": True, "stage1_exact_depot_connection_factors": True,
        "stage1_native_log_enabled": True, "phase3_diagnostics_dir": str(tmp_path)})
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase="phase3_two_stage",
        stage1_time_limit_sec=5, stage2_time_limit_sec=5, time_limit_sec=20,
        gurobi_threads=threads, stage1_best_obj_stop_enabled=False, stage1_gurobi_search_profile=profile)
    result = MILPOptimizer().solve(problem, config)
    assert result.feasible, result.infeasibility_reasons
    from src.optimization.common.feasibility import FeasibilityChecker
    independent = FeasibilityChecker().evaluate(problem, result.plan)
    assert independent.feasible, independent.errors
    metadata = result.plan.metadata
    assert metadata["stage1_vehicle_day_path_cover_lower_bounds"] == {0: 1}
    effective = metadata["stage1_gurobi_search_controls"]
    assert effective["pre_passes"] == 3
    if profile.endswith("no_crossover"):
        assert effective["node_method"] == 2
        assert effective["crossover"] == 0
    else:
        assert effective["node_method"] == -1
        assert "crossover" not in effective
    assert effective["root_method"] == (2 if "barrier" in profile else 1)
    assert effective["no_rel_heur_work"] == (120 if profile.endswith("norel") else 0)
    memory = metadata["stage1_search_telemetry"]["native_memory"]
    assert memory["after_optimize"]["peak_gb"] >= memory["after_optimize"]["used_gb"] > 0
    assert memory["before_optimize"]["used_gb"] > 0
    assert memory["soft_limit_gb"] == 18
    assert metadata["gurobi_threads"] == threads
    assert memory["threads"] == threads
    from pathlib import Path
    assert Path(metadata["stage1_native_log_path"]).is_file()
