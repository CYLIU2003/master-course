"""Feasible charging candidates cannot bypass the declared Stage2 gap gate."""
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.benchmarks.optimization_quality import stage2_execution_quality
from scripts.benchmarks.run_shibu21_seasonal_diagnostic import check_stage2_execution_quality
from scripts.benchmarks import audit_monthly_execution as auditor
from scripts.benchmarks import run_shibu21_seasonal_diagnostic as runner


def metadata(objective=100.0, bound=99.5, native_gap=.005):
    return {"stage2_objective_value": objective, "stage2_best_bound": bound,
            "stage2_mip_gap_ratio": native_gap, "stage2_has_feasible_incumbent": True,
            "stage2_solver_status": "time_limit"}


@pytest.mark.parametrize("objective,bound,gap,accepted", [
    (100, 99.5, .005, True), (0, 0, 0, True),
    (17662.531101537643, 5111.380405648195, .7106088376425724, False),
    (100, 50, 0, False), (100, 100, .71, False),
    (100, None, 0, False), (100, 100, None, False),
    (100, 100, float("nan"), False), (100, 100, -1, False),
])
def test_quality_needs_both_native_and_objective_bound_proof(objective,bound,gap,accepted):
    report = stage2_execution_quality(metadata(objective,bound,gap),target_gap=.01)
    assert report["accepted"] is accepted
    assert report["integrated_global_optimum_proven"] is False


def test_no_incumbent_is_rejected_even_if_numbers_look_optimal():
    values=metadata(0,0,0);values["stage2_has_feasible_incumbent"]=False
    assert "NO_STAGE2_INCUMBENT" in stage2_execution_quality(values,target_gap=.01)["reasons"]


@pytest.mark.parametrize("hour", [None, 155])
def test_failed_gate_records_reason_without_counting_or_executing_prefix(tmp_path,hour):
    result=SimpleNamespace(plan=SimpleNamespace(metadata=metadata(17662.531101537643,5111.380405648195,.7106088376425724)),
                           solver_status="time_limit",feasible=True)
    summary={"hourly_steps_accepted":29}
    assert not check_stage2_execution_quality(result,{"mip_gap":.01},tmp_path,summary,hour=hour)
    assert summary["hourly_steps_accepted"]==29
    assert summary["status"]==("DAY_AHEAD_QUALITY_FAILED" if hour is None else "HOURLY_QUALITY_FAILED")
    saved=json.loads((tmp_path/"quality_failure.json").read_text())
    assert saved["hour"]==hour and saved["execution_prefix_applied"] is False
    assert "NATIVE_GAP_TARGET_MISSED" in saved["quality"]["reasons"]


@pytest.mark.parametrize("bad_hour", [None, "day_ahead", 0, 167])
def test_independent_auditor_checks_each_original_gap(tmp_path,monkeypatch,bad_hour):
    root=Path(__file__).resolve().parents[1]
    design=json.loads((root/"config/shibu21_23_monthly_auxiliary_quality_20260922.json").read_text(encoding="utf-8"))
    design["require_stage2_execution_quality"]=True
    monkeypatch.setattr(auditor,"EXPECTED_SEARCH_CONTROLS_BY_KIND",{
        "day_ahead":{"stage2_gurobi_mip_focus":1,"stage2_gurobi_method":1},
        "hourly":{"stage2_gurobi_mip_focus":1,"stage2_gurobi_method":0}})
    base={"feasible":True,"trip_count_served":7,"trip_count_unserved":0,"solver_metadata":{
        "stage2_gurobi_aggregate":0,"stage2_gurobi_feasibility_tol":1e-9,"stage2_gurobi_integrality_tol":1e-9,
        "stage2_has_feasible_incumbent":True,"synthetic_pv_fallback_applied":False,
        "postsolve_repair_allowed":False,"postsolve_modified_solution":False,"derived_source_split":False,
        "successor_pruning_enabled":False,"arc_pruning_summary":{
            "candidate_arc_count_before_successor_pruning":10,"arc_count_after_successor_pruning":10,
            "pruned_arc_count":0,"pruned_origin_count":0,"max_candidate_successors_per_origin":5},
        "search_profile":{"fallback_count":0},"stage2_numeric_diagnostics":{
            "maximum_constraint_violation":0,"maximum_bound_violation":0,"maximum_integrality_violation":0}}}
    def read(path):
        result=deepcopy(base);hourly=path.name=="forecast_result.json"
        hour=int(path.parent.name.removeprefix("hour_")) if hourly else None
        result["metadata"]=metadata()
        if (hourly and hour==bad_hour) or (not hourly and bad_hour=="day_ahead"):
            result["metadata"]=metadata(100,29,.71)
        result["metadata"].update(stage2_gurobi_mip_focus=2 if hourly else 1,stage2_gurobi_method=0 if hourly else 1,
                                  stage2_gurobi_numeric_focus=3 if hourly else 0)
        result["effective_limits"]={"stage2_time_limit_sec":120,"time_limit_sec":120 if hourly else 2400}
        result["solver_metadata"].update(stage2_gurobi_presolve=0 if hourly else 2,stage2_time_limit_sec_effective=120)
        return result
    monkeypatch.setattr(auditor,"read_json",read)
    native,_,_=auditor.audit_native_entries(tmp_path,tmp_path/"chain",7,design)
    assert native["all_native_strict"] is (bad_hour is None)
    assert native["native_invalid_count"]==(0 if bad_hour is None else 1)
    if bad_hour is not None and bad_hour != "day_ahead":
        assert native["hourly_invalid"][0]["hour"]==bad_hour
        assert "stage2_gap_target_not_verified" in native["hourly_invalid"][0]["reasons"]


@pytest.mark.parametrize("bad_phase", ["day_ahead", "hourly"])
def test_real_week_entrypoint_stops_before_pv_execution_on_quality_failure(tmp_path, monkeypatch, bad_phase):
    """Exercise the caller: neither an unmet day-ahead nor hourly gap may execute."""
    @dataclass
    class Problem:
        metadata: dict = field(default_factory=dict)
        trips: tuple = ()
        vehicles: tuple = ()
        depot_energy_assets: dict = field(default_factory=dict)

    root = Path(__file__).resolve().parents[1]
    design = json.loads((root/"config/shibu21_23_monthly_auxiliary_budget_20260922.json").read_text(encoding="utf-8"))
    design["input_manifests_directory"] = "inputs"
    week = "2025-01-06"
    manifest = tmp_path/"inputs"/week/"derived_scenarios.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"cases":[{"scenario_id":"scenario", "prepared_input_id":"prepared",
        "timetable_row_count":0,"vehicle_count":0,"days":7}]}))
    actual = tmp_path/"actual.json"
    actual.write_text('{"depot_profiles":{}}')
    monkeypatch.setattr(runner,"ROOT",tmp_path)
    monkeypatch.setattr(runner,"require_execution_enabled",lambda *_:None)
    monkeypatch.setattr(runner.scenario_store,"_load",lambda *a,**kw:{})
    monkeypatch.setattr(runner,"load_prepared_input",lambda **kw:{})
    monkeypatch.setattr(runner,"materialize_scenario_from_prepared_input",lambda *a:{})
    monkeypatch.setattr(runner,"ProblemBuilder",lambda:SimpleNamespace(build_from_scenario=lambda *a,**kw:Problem()))
    monkeypatch.setattr(runner,"_prepare_actual_pv_execution_file",lambda *a,**kw:actual)
    monkeypatch.setattr(runner,"validate_physical_event_schedule",lambda **kw:{"accepted":True})
    monkeypatch.setattr(runner.ResultSerializer,"serialize_result",lambda result:{"metadata":result.plan.metadata})
    monkeypatch.setattr(runner.ResultSerializer,"serialize_plan",lambda plan:{})
    def result(bad):
        return SimpleNamespace(feasible=True,solver_status="time_limit",cost_breakdown={},infeasibility_reasons=[],
            solver_metadata={},plan=SimpleNamespace(metadata=metadata(100,29,.71) if bad else metadata()))
    monkeypatch.setattr(runner,"OptimizationEngine",lambda:SimpleNamespace(solve=lambda *a:result(bad_phase=="day_ahead")))
    def hourly(*args,**kwargs):
        assert bad_phase=="hourly", "Unaccepted day-ahead plan reached rolling"
        return result(True)
    monkeypatch.setattr(runner,"RollingReoptimizer",lambda:SimpleNamespace(reoptimize_charging_hour=hourly))
    def forbidden(*args,**kwargs):
        pytest.fail("A candidate missing the gap target reached execution")
    monkeypatch.setattr(runner,"execute_pv_prefix",forbidden)
    output=tmp_path/"case"
    summary=runner.solve_week(week,output,design,contract_validator=lambda *a:{})
    assert summary["status"]==("DAY_AHEAD_QUALITY_FAILED" if bad_phase=="day_ahead" else "HOURLY_QUALITY_FAILED")
    assert summary["hourly_steps_accepted"]==0
    assert json.loads((output/"progress.json").read_text())["status"]==summary["status"]
    assert not list(output.rglob("execution_state.json"))
