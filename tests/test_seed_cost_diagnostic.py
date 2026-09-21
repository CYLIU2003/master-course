from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from scripts.benchmarks.optimization_quality import native_root_log_evidence
from scripts.benchmarks.seed_cost_diagnostic import compare_costs, evaluate_supplied_seed
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.common.result import ResultSerializer
from src.optimization.milp.seed_snapshot import write_stage1_seed_snapshot
from src.optimization.engine import OptimizationEngine
from test_daily_return_policy import daily_problem
from test_multiday_rolling_contract import _fixed_plan


def test_native_root_log_does_not_confuse_internal_barrier_optimum_with_completed_root_lp():
    failed = ('Barrier solved model in 36 iterations\nOptimal objective 4.00000000e+06\n'
              'Building initial crossover basis\nCrossover changed status from Optimal to Memory Limit\n'
              'Root relaxation: memory limit, 0 iterations, 218.31 seconds\n')
    assert not native_root_log_evidence(failed)["root_lp_objective_reported"]
    assert native_root_log_evidence(failed)["crossover_memory_limit_observed"]
    passed = 'Root relaxation: objective 4.000000e+06, 0 iterations, 186.25 seconds (282.93 work units)\n'
    evidence = native_root_log_evidence(passed)
    assert evidence["root_lp_objective_jpy"] == 4000000
    assert evidence["root_lp_solve_seconds"] == 186.25
    assert not evidence["crossover_basis_build_observed"]


def result(cost, *, gap=0, feasible=True):
    return SimpleNamespace(feasible=feasible, cost_breakdown={"total_cost": cost},
        plan=SimpleNamespace(metadata={"stage2_objective_value": 100,
            "stage2_best_bound": 100*(1-gap), "stage2_solver_status": "optimal"}))


@pytest.mark.parametrize("seed,physical,expected", [
    (result(500), {"accepted": True}, 100),
    (result(300), {"accepted": True}, -100),
    (result(500, gap=.1), {"accepted": True}, None),
    (result(500, feasible=False), {"accepted": True}, None),
    (result(500), {"accepted": False}, None),
    (result(500), {"accepted": True, "violations": ["soc"]}, None),
    (result(float('nan')), {"accepted": True}, None),
])
def test_forecast_comparison_requires_physical_and_stage2_quality(seed, physical, expected):
    comparison = compare_costs(seed, physical, result(400), .01)
    assert comparison['seed_to_final_forecast_cost_reduction_jpy'] == expected
    assert not comparison['integrated_global_optimum_proven']


def test_seed_snapshot_and_fixed_stage2_use_supplied_assignment_without_changing_final(tmp_path):
    problem = daily_problem()
    seed = _fixed_plan(problem)
    problem = replace(problem, baseline_plan=seed, metadata={**problem.metadata,
        'stage1_seed_cost_diagnostic_enabled': True,
        'phase3_diagnostics_dir': str(tmp_path/'day_ahead_failure_diagnostics')})
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase='phase1_charging_only',
        fixed_assignment=seed, time_limit_sec=20, stage2_time_limit_sec=8,
        gurobi_threads=1, mip_gap=.01, allow_postsolve_repair=False)
    write_stage1_seed_snapshot(problem, config, applied=True, source='test_seed', rejection_reason=None)
    snapshot = tmp_path/'day_ahead_failure_diagnostics/stage1_supplied_seed.json'
    before = snapshot.read_bytes()
    final = OptimizationEngine().solve(problem, config)
    assert final.feasible, final.infeasibility_reasons
    final_before = ResultSerializer.serialize_result(final)
    comparison = evaluate_supplied_seed(problem, config, final, tmp_path, wall_seconds=20)
    assert comparison['status'] == 'COMPARABLE_FORECAST_COSTS'
    assert abs(comparison['seed_to_final_forecast_cost_reduction_jpy']) < 1e-6
    assert snapshot.read_bytes() == before
    assert ResultSerializer.serialize_result(final) == final_before
    with pytest.raises(FileExistsError):
        write_stage1_seed_snapshot(problem, config, applied=True, source='changed', rejection_reason=None)


def test_seed_evaluation_rejects_tampered_assignment_before_solving(tmp_path):
    path = tmp_path/'day_ahead_failure_diagnostics/stage1_supplied_seed.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'plan': {'duties': []}, 'plan_sha256': 'bad'}))
    with pytest.raises(ValueError, match='hash mismatch'):
        evaluate_supplied_seed(None, None, None, tmp_path, wall_seconds=20)


def test_native_phase3_captures_the_supplied_seed_before_search(tmp_path):
    from test_milp_soc_validator_roundtrip import _soc_roundtrip_problem
    from src.dispatch.models import DutyLeg, VehicleDuty
    from src.optimization.common.problem import AssignmentPlan
    problem = _soc_roundtrip_problem()
    trips = tuple(replace(t, operator_id='test_operator') for t in problem.trips)
    dispatch = [replace(t, operator_id='test_operator') for t in problem.dispatch_context.trips]
    problem = replace(problem, trips=trips, dispatch_context=replace(problem.dispatch_context, trips=dispatch))
    seed = AssignmentPlan(duties=(VehicleDuty('seed', 'BEV', (DutyLeg(dispatch[0], 30),)),),
        served_trip_ids=(trips[0].trip_id,), metadata={'duty_vehicle_map': {'seed': 'bev-1'}})
    problem = replace(problem, baseline_plan=seed, metadata={**problem.metadata,
        'stage1_seed_cost_diagnostic_enabled': True,
        'phase3_diagnostics_dir': str(tmp_path/'day_ahead_failure_diagnostics')})
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase='phase3_two_stage',
        time_limit_sec=20, stage1_time_limit_sec=8, stage2_time_limit_sec=8,
        gurobi_threads=1, mip_gap=.01, allow_postsolve_repair=False,
        stage1_gurobi_search_profile='bounded_presolve_barrier_no_crossover')
    final = OptimizationEngine().solve(problem, config)
    assert final.feasible, final.infeasibility_reasons
    snapshot = json.loads((tmp_path/'day_ahead_failure_diagnostics/stage1_supplied_seed.json').read_text(encoding='utf-8'))
    assert snapshot['applied'] is True
    assert snapshot['plan']['duties'] == ResultSerializer.serialize_plan(seed)['duties']
    assert 'not_first_solver_incumbent' in snapshot['semantics']
    comparison = evaluate_supplied_seed(problem, config, final, tmp_path, wall_seconds=20)
    assert comparison['status'] == 'COMPARABLE_FORECAST_COSTS'


def test_disabled_seed_diagnostic_creates_no_files(tmp_path):
    problem = daily_problem()
    problem = replace(problem, metadata={**problem.metadata, 'phase3_diagnostics_dir': str(tmp_path)})
    write_stage1_seed_snapshot(problem, OptimizationConfig(), applied=False, source='', rejection_reason='disabled')
    assert not list(tmp_path.iterdir())


def test_native_failure_diagnostics_preserve_seed_without_enabling_cost_experiment(tmp_path):
    import hashlib
    problem = daily_problem()
    seed = _fixed_plan(problem)
    problem = replace(problem, baseline_plan=seed, metadata={**problem.metadata,
        'stage1_native_log_enabled': True, 'stage1_seed_cost_diagnostic_enabled': False,
        'phase3_diagnostics_dir': str(tmp_path)})
    write_stage1_seed_snapshot(problem, OptimizationConfig(), applied=True,
        source='baseline', rejection_reason='')
    snapshot = json.loads((tmp_path/'stage1_supplied_seed.json').read_text(encoding='utf-8'))
    expected = ResultSerializer.serialize_plan(seed)
    assert snapshot['plan'] == expected
    assert snapshot['plan_sha256'] == hashlib.sha256(json.dumps(expected, sort_keys=True,
        ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    assert problem.metadata['stage1_seed_cost_diagnostic_enabled'] is False


def test_rejected_seed_keeps_its_reason_and_does_not_invent_a_baseline_cost(tmp_path):
    problem = daily_problem()
    problem = replace(problem, metadata={**problem.metadata,
        'stage1_seed_cost_diagnostic_enabled': True,
        'phase3_diagnostics_dir': str(tmp_path/'day_ahead_failure_diagnostics')})
    write_stage1_seed_snapshot(problem, OptimizationConfig(), applied=False,
        source='baseline', rejection_reason='baseline_connection_not_representable')
    comparison = evaluate_supplied_seed(problem, None, None, tmp_path, wall_seconds=20)
    assert comparison['status'] == 'SEED_NOT_APPLIED'
    assert comparison['reason'] == 'baseline_connection_not_representable'
    assert comparison['seed_to_final_forecast_cost_reduction_jpy'] is None
    assert not (tmp_path/'supplied_seed_cost/canonical_solver_result.json').exists()
