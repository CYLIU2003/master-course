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


def test_charging_only_gives_a_supplied_assignment_the_slot_clock(monkeypatch):
    """rc48 (2026-11-21): a seed plan without timestep_min wrote refuelling times as ''."""
    from types import SimpleNamespace
    from src.optimization.common.problem import AssignmentPlan
    from src.optimization.common.result import ResultSerializer
    from src.optimization.milp import solver_adapter
    adapter = solver_adapter.GurobiMILPAdapter.__new__(solver_adapter.GurobiMILPAdapter)
    seed = AssignmentPlan(metadata={"duty_vehicle_map": {"d": "v"}, "horizon_start_min": 0})
    seen = {}
    monkeypatch.setattr(solver_adapter, "is_gurobi_available", lambda: True)
    monkeypatch.setattr(adapter, "_normalize_phase1_fixed_assignment", lambda problem, plan: (plan, None), raising=False)
    monkeypatch.setattr(adapter, "_stamp_phase_metadata", lambda plan, config, **kw: plan, raising=False)

    def stage2(problem, config, stage1_plan, **kwargs):
        seen["plan"] = stage1_plan
        return "outcome", stage1_plan
    monkeypatch.setattr(adapter, "_solve_thesis_stage2_charging_dispatch", stage2, raising=False)
    problem = SimpleNamespace(scenario=SimpleNamespace(horizon_start="05:00", timestep_min=15), price_slots=())
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase="phase1_charging_only", fixed_assignment=seed)
    adapter._solve_charging_only(problem, config)
    meta = seen["plan"].metadata
    assert meta["timestep_min"] == 15 and meta["horizon_start"] == "05:00"
    assert meta["duty_vehicle_map"] == {"d": "v"}
    from src.optimization.common.problem import RefuelSlot
    refuel = RefuelSlot(vehicle_id="v", slot_index=2, refuel_liters=10.0, location_id="depot")
    from dataclasses import replace
    row = ResultSerializer.serialize_plan(replace(seen["plan"], refuel_slots=(refuel,)))["refueling_schedule"][0]
    assert row["time_hhmm"] == "05:30"
