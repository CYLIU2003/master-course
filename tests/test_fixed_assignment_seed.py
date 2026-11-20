"""Charging-only runs hold the supplied seed assignment fixed (2026-11-21)."""
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from bff.services.optimization_run.execute import apply_stage1_seed_plan


def test_charging_only_phase_fixes_the_seed_assignment():
    seed = object()
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase="phase1_charging_only")
    out = apply_stage1_seed_plan(config, "phase1_charging_only", seed)
    assert out.fixed_assignment is seed
    assert out.stage1_seed_plan is seed


def test_two_stage_phase_uses_the_seed_only_as_a_start():
    seed = object()
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase="phase3_two_stage")
    out = apply_stage1_seed_plan(config, "phase3_two_stage", seed)
    assert out.fixed_assignment is None
    assert out.stage1_seed_plan is seed
