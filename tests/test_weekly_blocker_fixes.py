import json
from types import SimpleNamespace

import pytest

from src.optimization.common.vehicle_timeline import VehicleEvent, fixed_path_soc_target_slots
from src.optimization.milp.seed_snapshot import write_stage1_seed_snapshot


def test_feedback_seed_preserves_original_and_has_its_own_evidence(tmp_path):
    problem = SimpleNamespace(metadata={"stage1_native_log_enabled": True, "phase3_diagnostics_dir": str(tmp_path)}, baseline_plan=None)
    config = SimpleNamespace(fixed_assignment=None)
    write_stage1_seed_snapshot(problem, config, applied=False, source="first", rejection_reason=None)
    original = (tmp_path / "stage1_supplied_seed.json").read_bytes()
    problem.metadata["stage2_feedback_iteration"] = 1
    write_stage1_seed_snapshot(problem, config, applied=False, source="feedback", rejection_reason=None)
    assert (tmp_path / "stage1_supplied_seed.json").read_bytes() == original
    assert json.loads((tmp_path / "stage1_supplied_seed_feedback_001.json").read_text())["source"] == "feedback"
    with pytest.raises(FileExistsError):
        write_stage1_seed_snapshot(problem, config, applied=False, source="overwrite", rejection_reason=None)


def test_full_soc_is_checked_before_outbound_energy_not_during_deadhead():
    # Native May IIS: slot 600 is outbound; the former target at slot end
    # requires maximum SOC after spending energy while charging is forbidden.
    problem = SimpleNamespace(metadata={"post_return_target_slots": [120,216,312,408,504,600,694]},
                              scenario=SimpleNamespace(timestep_min=15, horizon_start="00:00"))
    events = (VehicleEvent("v", "service_trip", 5*1440+400, 5*1440+460, "s", "d"),
              VehicleEvent("v", "daily_startup", 6*1440+355, 6*1440+380, "d", "s", energy_kwh=10),
              VehicleEvent("v", "service_trip", 6*1440+380, 6*1440+420, "s", "d"))
    deadlines = fixed_path_soc_target_slots(problem, events)
    assert deadlines[5] == 598  # Last complete slot ends at minute 8985, before departure 8995.
    assert (deadlines[5]+1)*15 <= events[1].start_min
    assert deadlines[6] == 694  # The final paid horizon is unchanged.
    # Full 90%-of-314 SOC followed by 10 kWh travel is valid, not a reset.
    soc_before = 314*.9
    assert soc_before == pytest.approx(282.6)
    assert soc_before-10 < soc_before


def test_native_next_morning_target_precedes_daily_startup():
    """Run only inside managed admission; two real service days, no SOC reset."""
    from src.gurobi_session import current_session
    if current_session() is None:
        pytest.skip("Native regression requires shared license admission")
    from dataclasses import replace
    from test_daily_return_policy import daily_problem
    from test_multiday_rolling_contract import _fixed_plan
    from src.optimization.common.problem import OptimizationConfig
    from src.optimization.common.feasibility import FeasibilityChecker
    from src.optimization.rolling.reoptimizer import RollingReoptimizer

    problem = daily_problem()
    # Second-day startup is 31:30; the service departure is 32:00.
    # Slot 31 used to require 80 kWh after 9 kWh of outbound travel.
    vehicle = replace(problem.vehicles[0], maximum_soc_kwh=80.0)
    problem = replace(problem, vehicles=(vehicle, *problem.vehicles[1:]), metadata={
        **problem.metadata, "bev_soc_deadline_mode": "next_morning_operational_max",
        "final_overnight_mode": "include", "bev_terminal_soc_policy": "fixed_target",
        "final_soc_target_percent": 80, "post_return_target_slots": [31, 47]})
    result = RollingReoptimizer().reoptimize_charging_hour(problem, _fixed_plan(problem),
        OptimizationConfig(time_limit_sec=20, mip_gap=0, gurobi_threads=1), 0, lookahead_hours=48)
    assert result.feasible, result.infeasibility_reasons
    assert not FeasibilityChecker()._evaluate_soc(problem, result.plan)
    assert result.plan.vehicle_soc_kwh_by_vehicle_slot["bev-1"][31] >= 80-1e-6
    assert result.plan.vehicle_soc_kwh_by_vehicle_slot["bev-1"][32] <= 71+1e-6
