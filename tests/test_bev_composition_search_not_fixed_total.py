from src.optimization import OptimizationMode
from src.optimization.common.problem import OptimizationConfig
from src.optimization.milp.engine import MILPOptimizer
from test_weather_coupled_assignment import (
    _full_phase3_composition_counterexample,
)


def test_bev_frontier_uses_only_minimum_bev_constraint() -> None:
    result = MILPOptimizer().solve(
        _full_phase3_composition_counterexample(),
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=60,
            stage1_time_limit_sec=40,
            stage2_time_limit_sec=20,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            stage1_stage2_candidate_limit=3,
            stage1_bev_frontier_enabled=True,
            stage1_bev_frontier_min_count=1,
            stage1_bev_frontier_max_count=2,
            stage1_bev_frontier_target_time_limit_sec=5.0,
            gurobi_threads=1,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    frontier = dict(result.plan.metadata["bev_cost_frontier"])
    rows = list(frontier["rows"])
    certificate = dict(
        result.plan.metadata[
            "stage1_used_powertrain_composition_search"
        ]
    )

    assert frontier["constraint_semantics"].startswith(
        "sum(used_electric_vehicle) >= K"
    )
    assert frontier["frontier_total_used_vehicle_count_fixed"] is False
    assert certificate["frontier_total_used_vehicle_count_fixed"] is False
    assert all(record["target_used_ice"] is None for record in certificate["target_records"])
    assert all(record["target_total_used_vehicle_count"] is None for record in certificate["target_records"])
    assert [row["minimum_used_bev_count"] for row in rows] == [1, 2]
