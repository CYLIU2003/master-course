import json

import pytest

from bff.services.optimization_run.artifact_completeness import _rolling_step_artifacts


@pytest.mark.parametrize('count', [24, 48, 101, 168, 175])
def test_only_numerically_final_step_can_omit_handoff(tmp_path, count):
    root = tmp_path / 'rolling_hourly_chain'
    root.mkdir()
    (root / 'rolling_chain_summary.json').write_text(json.dumps({
        'expected_step_count': count, 'step_count': count,
        'chain_accepted': True, 'all_steps_feasible': True}))
    for index in range(count):
        (root / f'step_{index:02d}_{index:02d}00').mkdir()
    errors = []
    required = _rolling_step_artifacts(run_dir=tmp_path, content_errors=errors)
    assert not errors
    handoffs = {path.split('/')[1] for path in required if path.endswith('state_for_next_hour.json')}
    assert handoffs == {f'step_{index:02d}_{index:02d}00' for index in range(count - 1)}


def test_duplicate_or_missing_step_index_is_rejected(tmp_path):
    root = tmp_path / 'rolling_hourly_chain'
    root.mkdir()
    (root / 'rolling_chain_summary.json').write_text(json.dumps({
        'expected_step_count': 2, 'step_count': 2,
        'chain_accepted': True, 'all_steps_feasible': True}))
    for name in ('step_00_0000', 'step_00_0100'):
        (root / name).mkdir()
    errors = []
    _rolling_step_artifacts(run_dir=tmp_path, content_errors=errors)
    assert any('exactly once' in error for error in errors)
