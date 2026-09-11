from dataclasses import replace

import pytest

from src.optimization.common.problem import OptimizationConfig
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from test_daily_return_policy import daily_problem
from test_multiday_rolling_contract import _fixed_plan


class _CaptureEngine:
    def __init__(self):
        self.problem = None
        self.config = None

    def solve(self, problem, config):
        self.problem = problem
        self.config = config
        return {"ok": True}


def _boundary_problem(*, physical_floor=0.0, bess_reference=1199.9999999999998):
    problem = daily_problem()
    depot, asset = next(iter(problem.depot_energy_assets.items()))
    problem = replace(
        problem,
        depot_energy_assets={depot: replace(
            asset,
            # The physical floor is zero; 1200 kWh is the stricter
            # period-end floor that must not leak into intermediate windows.
            bess_energy_kwh=4800.0,
            bess_soc_min_kwh=physical_floor,
            bess_soc_max_kwh=4800.0,
            bess_initial_soc_kwh=3000.0,
            bess_terminal_soc_min_kwh=1200.0,
            bess_terminal_soc_policy="return_to_initial",
            bess_terminal_soc_target_kwh=3000.0,
        )},
        metadata={
            **problem.metadata,
            "rolling_window_terminal_policy": "day_ahead_boundary_state",
        },
    )
    plan = replace(
        _fixed_plan(problem),
        vehicle_soc_kwh_by_vehicle_slot={"bev-1": {24: 80.0}},
        bess_soc_kwh_by_depot_slot={depot: {23: bess_reference}},
    )
    return problem, plan, depot


def test_public_minimum_only_skips_roundoff_bess_boundary_but_keeps_bev_reference():
    problem, plan, depot = _boundary_problem()
    rolling = RollingReoptimizer()
    capture = _CaptureEngine()
    rolling._engine = capture  # type: ignore[attr-defined]

    result = rolling.reoptimize_charging_hour(
        problem,
        plan,
        OptimizationConfig(),
        0,
        lookahead_hours=24,
        bess_terminal_policy="minimum_only",
    )

    assert result == {"ok": True}
    assert capture.problem is not None
    asset = capture.problem.depot_energy_assets[depot]
    assert asset.bess_terminal_soc_policy == "minimum_only"
    assert asset.bess_terminal_soc_target_kwh == 0.0
    assert asset.bess_soc_min_kwh == 0.0
    assert capture.problem.metadata["bess_daily_balance_target_kwh_by_depot"] == {
        depot: 3000.0
    }
    assert capture.problem.metadata["bev_terminal_soc_target_kwh_by_vehicle"] == {
        "bev-1": 80.0
    }
    reference = capture.problem.metadata["rolling_window_terminal_reference"]
    assert reference["policy"] == "day_ahead_boundary_state"
    assert capture.config.fixed_assignment is plan


def test_minimum_only_accepts_roundoff_at_the_actual_physical_floor():
    problem, plan, depot = _boundary_problem(physical_floor=1200.0)
    rolling = RollingReoptimizer()
    capture = _CaptureEngine()
    rolling._engine = capture  # type: ignore[attr-defined]

    # This is the old failure mechanism: constructing an intermediate fixed
    # target compares the one-ulp-lower reference against the period floor.
    with pytest.raises(ValueError, match="fixed terminal BESS SOC target must"):
        rolling._apply_window_terminal_targets(problem, plan, 0, 24)

    assert rolling.reoptimize_charging_hour(
        problem,
        plan,
        OptimizationConfig(),
        0,
        lookahead_hours=24,
        bess_terminal_policy="minimum_only",
    ) == {"ok": True}
    assert capture.problem.depot_energy_assets[depot].bess_soc_min_kwh == 1200.0


def test_minimum_only_does_not_require_a_bess_reference_trace():
    problem, plan, depot = _boundary_problem()
    rolling = RollingReoptimizer()
    capture = _CaptureEngine()
    rolling._engine = capture  # type: ignore[attr-defined]
    plan = replace(plan, bess_soc_kwh_by_depot_slot={})

    assert rolling.reoptimize_charging_hour(
        problem,
        plan,
        OptimizationConfig(),
        0,
        lookahead_hours=24,
        bess_terminal_policy="minimum_only",
    ) == {"ok": True}
    assert capture.problem.depot_energy_assets[depot].bess_terminal_soc_policy == "minimum_only"


def test_public_scenario_policy_requires_valid_bess_reference_and_rejects_invalid_reference():
    problem, plan, _depot = _boundary_problem()
    rolling = RollingReoptimizer()
    capture = _CaptureEngine()
    rolling._engine = capture  # type: ignore[attr-defined]

    invalid_plan = replace(
        plan,
        bess_soc_kwh_by_depot_slot={_depot: {23: 5000.0}},
    )
    with pytest.raises(ValueError, match="fixed terminal BESS SOC target must"):
        rolling.reoptimize_charging_hour(
            problem,
            invalid_plan,
            OptimizationConfig(),
            0,
            lookahead_hours=24,
            bess_terminal_policy="scenario",
        )

    valid_plan = replace(
        plan,
        bess_soc_kwh_by_depot_slot={_depot: {23: 1200.0}},
    )
    assert rolling.reoptimize_charging_hour(
        problem,
        valid_plan,
        OptimizationConfig(),
        0,
        lookahead_hours=24,
        bess_terminal_policy="scenario",
    ) == {"ok": True}
    assert capture.problem.depot_energy_assets[_depot].bess_terminal_soc_policy == "fixed_target"
    assert capture.problem.depot_energy_assets[_depot].bess_terminal_soc_target_kwh == 1200.0

    missing_trace = replace(plan, bess_soc_kwh_by_depot_slot={})
    with pytest.raises(ValueError, match="lacks BESS"):
        rolling.reoptimize_charging_hour(
            problem,
            missing_trace,
            OptimizationConfig(),
            0,
            lookahead_hours=24,
            bess_terminal_policy="scenario",
        )


def test_out_of_range_measured_bess_soc_is_still_rejected():
    problem, plan, depot = _boundary_problem()
    rolling = RollingReoptimizer()

    with pytest.raises(ValueError, match="Measured BESS SOC"):
        rolling.reoptimize_charging_hour(
            problem,
            plan,
            OptimizationConfig(),
            0,
            lookahead_hours=24,
            actual_bess_soc_kwh={depot: -10.0},
            bess_terminal_policy="minimum_only",
        )


def test_evaluation_end_does_not_create_intermediate_bess_reference():
    problem, plan, depot = _boundary_problem()
    rolling = RollingReoptimizer()

    end = rolling._apply_window_terminal_targets(problem, plan, 24 * 60, 24)
    assert end.depot_energy_assets[depot].bess_terminal_soc_policy == "return_to_initial"
    assert end.depot_energy_assets[depot].bess_terminal_soc_min_kwh == 1200.0
    minimum_only = rolling._apply_bess_terminal_policy(end, "minimum_only")
    assert minimum_only.depot_energy_assets[depot].bess_terminal_soc_policy == "minimum_only"
    assert minimum_only.depot_energy_assets[depot].bess_terminal_soc_target_kwh == 0.0
