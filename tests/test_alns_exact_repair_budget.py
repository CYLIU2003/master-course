from src.optimization.alns.engine import remaining_exact_repair_seconds
from src.optimization.common.benchmarking import ExactRepairPolicy


def test_exact_repair_call_budget_is_minimum_of_outer_remaining_and_repair_limits():
    policy = ExactRepairPolicy(call_limit=3, time_budget_sec=120.0)
    assert remaining_exact_repair_seconds(
        total_limit_sec=1500, elapsed_sec=100, policy=policy,
        calls_used=0, time_used_sec=0,
    ) == 40
    assert remaining_exact_repair_seconds(
        total_limit_sec=1500, elapsed_sec=1491.5, policy=policy,
        calls_used=1, time_used_sec=39,
    ) == 8
    assert remaining_exact_repair_seconds(
        total_limit_sec=1500, elapsed_sec=100, policy=policy,
        calls_used=2, time_used_sec=118.5,
    ) == 1
    assert remaining_exact_repair_seconds(
        total_limit_sec=1500, elapsed_sec=100, policy=policy,
        calls_used=3, time_used_sec=20,
    ) == 0
    assert remaining_exact_repair_seconds(
        total_limit_sec=1500, elapsed_sec=1499.5, policy=policy,
        calls_used=0, time_used_sec=0,
    ) == 0
