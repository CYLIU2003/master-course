"""Reporting recovery cannot turn a solver failure into a presentation success."""
from copy import deepcopy
import json

import pytest

from tools.thesis_authoring.prepare_september_evidence import verify_original_state, sha


@pytest.fixture
def evidence(tmp_path):
    row = {'job_id': 'attempt-1', 'git_sha': 'frozen-source'}
    item = {'state': 'FAILED'}
    worker = {'id': row['job_id'], 'state': 'FAILED',
              'provenance': {'git': {'sha': row['git_sha']}},
              'result': {'error': 'LiteratureFigureError: Conflicting grid CO2 factors',
                         'metadata': {'failure_type': 'LiteratureFigureError'}}}
    receipt = {'original_worker_state': 'FAILED', 'new_solver_run': False,
               'status': 'REPORTING_RECOVERED_CONDITIONAL_EVALUATION'}
    path = tmp_path / 'recovery.json'
    path.write_text(json.dumps(receipt), encoding='utf8')
    proof = {'recovery': str(tmp_path), 'recovery_receipt_sha256': sha(path),
             'original_worker_state': 'FAILED'}
    return row, proof, item, worker


def test_reporting_warning_preserves_failed_original(evidence):
    result = verify_original_state(*evidence)
    assert result['original_state'] == 'FAILED'
    assert 'Conflicting grid CO2 factors' in result['reporting_warning']


@pytest.mark.parametrize('mutation', ['solver_failure', 'wrong_attempt', 'wrong_source', 'state_mismatch', 'tampered_receipt'])
def test_unverified_failure_or_changed_provenance_is_rejected(evidence, mutation):
    row, proof, item, worker = deepcopy(evidence)
    if mutation == 'solver_failure':
        worker['result']['metadata']['failure_type'] = 'MemoryError'
    elif mutation == 'wrong_attempt':
        worker['id'] = 'different-attempt'
    elif mutation == 'wrong_source':
        worker['provenance']['git']['sha'] = 'different-source'
    elif mutation == 'state_mismatch':
        item['state'] = 'COMPLETED'
    else:
        proof['recovery_receipt_sha256'] = 'tampered'
    with pytest.raises(ValueError):
        verify_original_state(row, proof, item, worker)


def test_failed_worker_without_recovery_is_rejected(evidence):
    row, _, item, worker = evidence
    with pytest.raises(ValueError, match='without reporting recovery'):
        verify_original_state(row, {}, item, worker)


def test_completed_worker_needs_no_recovery(evidence):
    row, _, item, worker = evidence
    worker['state'] = item['state'] = 'COMPLETED'
    assert verify_original_state(row, {}, item, worker) == {
        'original_state': 'COMPLETED', 'reporting_warning': None}


def test_chart_roundtrip_noise_only_is_normalized(tmp_path):
    from zipfile import ZipFile
    from tools.thesis_authoring.normalize_chart_cache import normalize
    source, target = tmp_path / 'source.pptx', tmp_path / 'target.pptx'
    with ZipFile(source, 'w') as archive:
        archive.writestr('ppt/charts/chart1.xml', '<c:numLit><c:pt><c:v>1.2345670000000002</c:v></c:pt></c:numLit><c:tx>1.2345670000000002</c:tx>')
        archive.writestr('source.csv', '1.2345670000000002')
    normalize(source, target)
    with ZipFile(target) as archive:
        assert b'<c:v>1.234567</c:v>' in archive.read('ppt/charts/chart1.xml')
        assert b'<c:tx>1.2345670000000002</c:tx>' in archive.read('ppt/charts/chart1.xml')
        assert archive.read('source.csv') == b'1.2345670000000002'


def test_chart_material_rounding_is_rejected(tmp_path):
    from zipfile import ZipFile
    from tools.thesis_authoring.normalize_chart_cache import normalize
    source = tmp_path / 'source.pptx'
    with ZipFile(source, 'w') as archive:
        archive.writestr('ppt/charts/chart1.xml', '<c:numCache><c:v>1.2345674</c:v></c:numCache>')
    with pytest.raises(ValueError, match='Unexpected numerical change'):
        normalize(source, tmp_path / 'target.pptx')
