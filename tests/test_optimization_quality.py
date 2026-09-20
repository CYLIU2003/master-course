from scripts.benchmarks.optimization_quality import day_ahead_quality


def metadata(bound=98, objective=100):
    return {'stage1_objective_value': objective, 'stage1_certified_best_bound': bound,
            'stage2_objective_value': 0, 'stage2_best_bound': 0,
            'stage1_search_telemetry': {'first_incumbent_objective': objective}}


def test_two_percent_gap_is_not_one_percent_quality_or_integrated_optimality():
    result = day_ahead_quality(metadata(), target_gap=.01)
    assert result['stage1']['gap_ratio'] == .02
    assert not result['subproblem_gap_targets_met']
    assert not result['integrated_global_optimum_proven']
    assert result['incumbent_improvement_jpy'] == 0


def test_missing_or_inconsistent_bound_is_not_a_quality_certificate():
    for bound in (None, float('nan'), 101):
        assert not day_ahead_quality(metadata(bound), target_gap=.01)['stage1']['target_met']


def test_zero_objective_and_zero_bound_is_certified_for_that_subproblem_only():
    result = day_ahead_quality(metadata(0, 0), target_gap=.01)
    assert result['subproblem_gap_targets_met']
    assert not result['integrated_global_optimum_proven']
