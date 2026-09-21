import json

import pytest

from scripts.benchmarks import run_planning_consistency_diagnosis as runner


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "git_state", lambda: {"sha": "frozen", "status_porcelain": ""})
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"diagnostic_stop_after_day_ahead": True}))
    return config


def test_preflight_failure_keeps_original_reasons_without_reading_missing_progress(tmp_path, monkeypatch):
    config = setup(monkeypatch, tmp_path)
    reason = "渋21: verified timetable dataset has zero trips"
    monkeypatch.setattr(runner, "run_campaign", lambda *_args, **_kwargs: {
        "status": "STOPPED_AFTER_FAILED_CASE", "summaries": [{
            "status": "BLOCKED_CASE_PREFLIGHT", "diagnostic_result": {
                "solve_attempted": False, "reasons": [reason]}}]})
    with pytest.raises(RuntimeError, match="BLOCKED_CASE_PREFLIGHT"):
        runner.run(config, tmp_path / "run")
    failure = json.loads((tmp_path / "run/failure.json").read_text(encoding="utf-8"))
    assert reason in failure["error"]
    assert "FileNotFoundError" not in failure["error"]
    assert failure["campaign_outcome"]["reasons"] == [reason]
    assert failure["campaign_outcome"]["solve_attempted"] is False
    assert not failure["email_sent"] and not failure["monthly_complete"]


@pytest.mark.parametrize("physical_passed,native_feasible", [(True, True), (False, True), (True, False)])
def test_successful_day_ahead_diagnosis_requires_consistent_saved_evidence(
    tmp_path, monkeypatch, physical_passed, native_feasible,
):
    config = setup(monkeypatch, tmp_path)

    def campaign(_design, output, **_kwargs):
        case = output / "cases/2025-05-12/diagnostic/2025-05-12"
        case.mkdir(parents=True)
        for name, payload in {
            "progress.json": {"status": "DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE",
                              "day_ahead_physical_accepted": True, "day_ahead_seconds": 3},
            "canonical_solver_result.json": {"metadata": {}, "feasible": native_feasible},
            "day_ahead_physical_validation.json": {"accepted": physical_passed},
            "day_ahead_optimization_quality.json": {"subproblem_gap_targets_met": False},
            "input_audit.json": {"accepted": True},
        }.items():
            (case / name).write_text(json.dumps(payload))
        return {"status": "DAY_AHEAD_ONLY_CAMPAIGN_COMPLETE", "summaries": [{
            "status": "DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE", "diagnostic_result": {"solve_attempted": True}}]}

    monkeypatch.setattr(runner, "run_campaign", campaign)
    if not physical_passed or not native_feasible:
        with pytest.raises(RuntimeError, match="evidence contradicts"):
            runner.run(config, tmp_path / "run")
        assert not (tmp_path / "run/summary.json").exists()
        failure = json.loads((tmp_path / "run/failure.json").read_text(encoding="utf-8"))
        assert "evidence contradicts" in failure["error"]
        return
    summary = runner.run(config, tmp_path / "run")
    assert summary["status"] == "DIAGNOSIS_COMPLETE" and summary["physical_accepted"]
    assert not summary["monthly_complete"] and not summary["email_sent"]
    assert len(summary["evidence_sha256"]) == 4
    assert summary["evidence_assessment"]["diagnosis_completed_is_optimization_accepted"] is False


def test_memory_stop_below_soft_limit_is_still_a_blocker_and_zero_charging_is_not_free_operation():
    assessment = runner.assess_evidence(
        {"feasible": True, "cost_breakdown": {"total_cost": 4157027.34},
         "metadata": {"native_memory": {"peak_gb": 17.66, "soft_limit_gb": 18}}},
        {"stage1": {"target_met": False, "solver_status": "memory_limit"},
         "stage2": {"target_met": True, "solver_status": "optimal", "objective_jpy": 0},
         "incumbent_improvement_jpy": 132.52},
        {"accepted": True, "violations": []},
    )
    assert "STAGE1_MEMORY_LIMIT" in assessment["blocking_reasons"]
    assert not assessment["subproblem_gap_targets_met"]
    assert assessment["final_forecast_total_cost_jpy"] == 4157027.34
    assert assessment["initial_incumbent_fixed_stage2_total_cost_improvement_jpy"] is None
    assert not assessment["stage2_objective_is_total_cost"]


@pytest.mark.parametrize("total", [None, float("nan"), float("inf"), True])
def test_missing_or_nonfinite_total_is_not_converted_to_zero(total):
    assessment = runner.assess_evidence(
        {"feasible": True, "cost_breakdown": {"total_cost": total}},
        {"stage1": {"target_met": True}, "stage2": {"target_met": True}}, {"accepted": True})
    assert assessment["subproblem_gap_targets_met"]
    assert assessment["final_forecast_total_cost_jpy"] is None
    assert "FINAL_FORECAST_TOTAL_COST_MISSING" in assessment["blocking_reasons"]
    assert not assessment["integrated_global_optimum_proven"]


@pytest.mark.parametrize("native,physical", [
    ({"feasible": False}, {"accepted": True}),
    ({"feasible": True}, {"accepted": False}),
    ({"feasible": True}, {"accepted": True, "violations": ["soc"]}),
])
def test_inconsistent_physical_evidence_blocks_acceptance(native, physical):
    assessment = runner.assess_evidence(native, {}, physical)
    assert "PHYSICAL_OR_SOLVER_FEASIBILITY_NOT_ACCEPTED" in assessment["blocking_reasons"]


@pytest.mark.parametrize("diagnostic_reasons,phase_reasons", [
    (["[ROUTE_BAND] actual solver rejection"], []),
    ([], ["[ROUTE_BAND] actual solver rejection"]),
    (["[ROUTE_BAND] actual solver rejection"], ["[ROUTE_BAND] actual solver rejection"]),
])
def test_day_ahead_failure_preserves_nested_reasons(tmp_path, monkeypatch,
                                                  diagnostic_reasons, phase_reasons):
    config = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "run_campaign", lambda *_args, **_kwargs: {
        "status": "STOPPED_AFTER_FAILED_CASE", "summaries": [{
            "status": "DAY_AHEAD_FAILED", "diagnostic_result": {
                "solve_attempted": True, "day_ahead_reasons": diagnostic_reasons},
            "day_ahead": {"reasons": phase_reasons}}]})
    with pytest.raises(RuntimeError, match="actual solver rejection"):
        runner.run(config, tmp_path / "run")
    failure = json.loads((tmp_path / "run/failure.json").read_text(encoding="utf-8"))
    assert failure["campaign_outcome"]["reasons"] == ["[ROUTE_BAND] actual solver rejection"]
    assert failure["campaign_outcome"]["solve_attempted"] is True
