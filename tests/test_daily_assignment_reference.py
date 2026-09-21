"""Reference coverage and same-total-cost bounds must fail closed."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scripts.benchmarks.run_daily_assignment_reference import (
    build_example, run_reference, summarize,
)
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.engine import OptimizationEngine


@pytest.mark.parametrize('fault',['missing','duplicate','unresolved','nan','wrong_bound','wrong_assignment'])
def test_incomplete_or_invalid_certificate_cannot_claim_reference(fault):
    expected = [('a','a'),('a','b')]
    rows = [dict(assignment=x,accepted=True,total_upper_jpy=10,total_lower_jpy=10) for x in expected]
    if fault == 'missing':
        rows.pop()
    elif fault == 'duplicate':
        rows[1] = deepcopy(rows[0])
    elif fault == 'unresolved':
        rows[1]['accepted'] = False
    elif fault == 'nan':
        rows[1]['total_lower_jpy'] = float('nan')
    elif fault == 'wrong_bound':
        rows[1]['total_lower_jpy'] = 11
    else:
        rows[1]['assignment'] = ('b','b')
    report = summarize(rows,expected_assignments=expected)
    assert report['status'] == 'REFERENCE_BLOCKED'
    assert report['total_lower_jpy'] is None
    assert not report['full_week_global_optimality_proven']


def test_native_daily_reference_covers_all_assignments_and_more_pv_cannot_raise_minimum(tmp_path):
    pytest.importorskip('gurobipy')
    low = run_reference(tmp_path/'low')
    high = run_reference(tmp_path/'high',extra_pv_kwh=10)
    for report in (low,high):
        assert report['status'] == 'NUMERICAL_REFERENCE_COMPLETE', report['rows']
        assert report['assignment_count'] == report['expected_assignment_count'] == 4
        assert abs(report['absolute_gap_jpy']) <= 1e-6
        assert all(row['physical_accepted'] and row['cost_match'] for row in report['rows'])
        assert all(20-1e-6 <= row['bess_final_kwh'] <= 80+1e-6 for row in report['rows'])
        assert not report['full_week_global_optimality_proven']
    assert high['total_upper_jpy'] <= low['total_upper_jpy']+1e-6
    # A feasible two-stage result must never undercut the complete reference.
    problem = build_example()
    problem = replace(problem,metadata={**problem.metadata,
        'max_start_fragments_per_vehicle':100,'max_end_fragments_per_vehicle':100})
    candidate = OptimizationEngine().solve(problem,OptimizationConfig(mode=OptimizationMode.MILP,
        phase='phase3_two_stage',time_limit_sec=20,stage1_time_limit_sec=10,
        stage2_time_limit_sec=10,mip_gap=0,gurobi_threads=1,allow_postsolve_repair=False))
    assert candidate.feasible, candidate.infeasibility_reasons
    assert candidate.cost_breakdown['total_cost'] >= low['total_lower_jpy']-1e-6
