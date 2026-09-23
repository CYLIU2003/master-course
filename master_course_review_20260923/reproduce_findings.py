"""Reproduce isolated behaviors from verified GitHub source copies.

This is NOT the repository's test suite and does NOT run Windows, SSH or Gurobi.
All files are temporary; os.kill is mocked before a PID check is executed.
A successful check means that the reported behavior was reproduced, not that
production behavior is correct.
"""
from __future__ import annotations
import ast
import json
import platform
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parent
OBSERVATIONS: list[dict] = []


def load_source(name: str, extra: dict | None = None) -> types.ModuleType:
    source = BASE / 'sources' / name
    tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
    kept = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (
            node.level or (node.module or '').startswith(('bff', 'src'))
        ):
            continue
        assigned = []
        if isinstance(node, ast.Assign):
            assigned = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned = [node.target.id]
        if set(assigned) & {'_JOB_DIR', '_jobs'}:
            continue
        kept.append(node)
    module = types.ModuleType('review_' + source.stem)
    sys.modules[module.__name__] = module
    module.__dict__.update(extra or {})
    exec(compile(ast.Module(body=kept, type_ignores=[]), str(source), 'exec'), module.__dict__)
    return module


def record(test_id: str, actual: dict, assertion: bool) -> None:
    item = {'check': test_id, 'behavior_reproduced': bool(assertion), 'actual': actual}
    OBSERVATIONS.append(item)
    print(json.dumps(item, ensure_ascii=False))
    assert assertion, f'Could not reproduce {test_id}'


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='mc-review-') as tmp:
        store = load_source('job_store.py')
        store._JOB_DIR = Path(tmp)
        store._jobs = {}

        corrupt = Path(tmp) / 'corrupt.json'
        corrupt.write_text('{"status":', encoding='utf8')
        got = store._load_jobs_from_disk()
        record('C01_CORRUPT_JOB_FILE_DELETED',
               {'file_retained': corrupt.exists(), 'job_count': len(got)},
               not corrupt.exists() and not got)

        protected = Path(tmp) / 'transient-read.json'
        protected.write_text(json.dumps({'job_id': 'transient-read', 'status': 'completed'}))
        original_read = Path.read_text
        def deny_read(path, *args, **kwargs):
            if path == protected:
                raise PermissionError('simulated transient read lock')
            return original_read(path, *args, **kwargs)
        with patch.object(Path, 'read_text', deny_read):
            store._load_jobs_from_disk()
        record('C02_VALID_JOB_DELETED_AFTER_READ_ERROR',
               {'file_retained': protected.exists(), 'error_type': 'simulated PermissionError'},
               not protected.exists())

        pending = Path(tmp) / 'pending.json'
        pending.write_text(json.dumps({'job_id': 'pending', 'status': 'pending', 'metadata': {'pid': 0}}))
        got = store._load_jobs_from_disk()
        record('C03_QUEUED_JOB_BECOMES_FAILED_AFTER_RESTART',
               {'status': got['pending'].status, 'error': got['pending'].error},
               got['pending'].status == 'failed')
        pending.unlink()

        calls = []
        store.os = types.SimpleNamespace(kill=lambda pid, sig: calls.append((pid, sig)))
        alive = store._pid_exists(12345)
        record('C04_LIVENESS_CHECK_CALLS_OS_KILL_ZERO',
               {'calls': calls, 'returned': alive, 'os_function_is_mock': True},
               calls == [(12345, 0)] and alive)

        def fake_nonconsole_kill(pid, sig):
            raise OSError('simulated console-control failure, not a missing PID')
        store.os = types.SimpleNamespace(kill=fake_nonconsole_kill)
        alive = store._pid_exists(12345)
        record('C05_CONSOLE_ERROR_COLLAPSES_TO_PID_ABSENT',
               {'returned': alive, 'mock_injected': 'OSError'},
               alive is False)

        # Deterministic interleaving of two writes to the same job's .json.tmp.
        a_written, b_written, a_replaced = (threading.Event() for _ in range(3))
        original_write, original_replace = Path.write_text, Path.replace
        errors = []
        def wait(event):
            assert event.wait(3), 'test interleaving timeout'
        def raced_write(path, text, *args, **kwargs):
            if not str(path).endswith('race.json.tmp'):
                return original_write(path, text, *args, **kwargs)
            if threading.current_thread().name == 'writer-a':
                value = original_write(path, text, *args, **kwargs)
                a_written.set(); wait(b_written)
                return value
            wait(a_written)
            value = original_write(path, text, *args, **kwargs)
            b_written.set(); wait(a_replaced)
            return value
        def raced_replace(path, target):
            value = original_replace(path, target)
            if threading.current_thread().name == 'writer-a':
                a_replaced.set()
            return value
        def write_job(status):
            try:
                store._persist_job(store.Job(job_id='race', status=status))
            except BaseException as exc:
                errors.append(type(exc).__name__)
        with patch.object(Path, 'write_text', raced_write), patch.object(Path, 'replace', raced_replace):
            a = threading.Thread(target=write_job, args=('running',), name='writer-a')
            b = threading.Thread(target=write_job, args=('completed',), name='writer-b')
            a.start(); b.start(); a.join(5); b.join(5)
            assert not a.is_alive() and not b.is_alive()
        final = json.loads((Path(tmp) / 'race.json').read_text())
        record('C06_SHARED_TEMP_PATH_RACE',
               {'writer_errors': errors, 'final_status': final['status'], 'schedule_controlled': True},
               errors == ['FileNotFoundError'] and final['status'] == 'completed')

    modes = types.SimpleNamespace(MILP='milp', ALNS='alns', GA='ga', ABC='abc', HYBRID='hybrid')
    execute = load_source('execute.py', {'OptimizationMode': modes, 'VALID_PHASES': {
        'phase1_charging_only', 'phase2_assignment_only', 'phase3_two_stage', 'phase4_integrated', 'diagnostic'}})
    values = {x: execute.parse_optimization_mode(execute.normalize_solver_mode(x))
              for x in ('cbc', 'mode_alns_onyl', 'mode_alns_only')}
    record('C07_UNKNOWN_SOLVER_TOKENS_BECOME_HYBRID', values,
           values == {'cbc': 'hybrid', 'mode_alns_onyl': 'hybrid', 'mode_alns_only': 'alns'})
    policy = load_source('benchmarking.py', {'OptimizationMode': modes})
    p = policy.exact_repair_policy(types.SimpleNamespace(alns_iterations=500, time_limit_sec=1500))
    record('C08_DECLARED_EXACT_REPAIR_POLICY',
           {'call_limit': p.call_limit, 'time_budget_sec': p.time_budget_sec,
            'note': 'Budget declaration only; operator forwarding is reviewed separately.'},
           p.call_limit == 3 and p.time_budget_sec == 120)

    output = {
        'reviewed_commit': '5d790ea16329eda22e3ceb9930548f9d33de1bb3',
        'environment': {'python': platform.python_version(), 'system': platform.system()},
        'scope': 'isolated source functions; dependencies mocked; not full integration tests',
        'windows_ssh_gurobi_executed': False,
        'checks': OBSERVATIONS,
    }
    (BASE / 'reproduction_results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf8')
    print(f'REPRODUCED {len(OBSERVATIONS)} / {len(OBSERVATIONS)} isolated checks')

if __name__ == '__main__':
    main()
