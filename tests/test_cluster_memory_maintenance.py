"""Maintenance cannot turn an unknown/active process into a cleanup target."""
import base64
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from tools.cluster.memory_maintenance import inspect_worker, maintenance_script


def test_remote_script_uses_stdin_below_windows_command_limit(monkeypatch):
    worker = SimpleNamespace(id='node', workspace='C:/jobs', transport='ssh')
    monkeypatch.setattr('tools.cluster.memory_maintenance.ssh_command', lambda w, r: ['ssh', 'node', r])
    def run(command, **kwargs):
        assert len(' '.join(command)) < 2000
        assert b"$apply=$false" in kwargs['input']
        assert kwargs['timeout'] == 90
        return SimpleNamespace(returncode=0, stdout=b'{"hostname":"node","stopped_count":0}', stderr=b'')
    monkeypatch.setattr('tools.cluster.memory_maintenance.subprocess.run', run)
    assert inspect_worker(worker, False)['status'] == 'INSPECTED'


def test_timeout_stays_unknown_without_retry(monkeypatch):
    worker = SimpleNamespace(id='node', workspace='C:/jobs', transport='local')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, 90)
    monkeypatch.setattr('tools.cluster.memory_maintenance.subprocess.run', run)
    assert inspect_worker(worker, True)['status'] == 'UNVERIFIED'
    assert len(calls) == 1


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell behavior on Windows')
@pytest.mark.parametrize('state', ['RUNNING', 'LOST', 'CANCELLED'])
def test_active_unknown_or_recent_terminal_process_is_not_opened(tmp_path, state):
    attempt = 'test-attempt'
    launch = tmp_path / '.launch' / attempt
    launch.mkdir(parents=True)
    request = launch / 'request.json'
    # A malformed/huge input bundle must not be read for active/unknown jobs.
    request.write_text('unreadable input bundle')
    folder = tmp_path / attempt
    folder.mkdir()
    (folder / 'state.json').write_text(json.dumps({'id': attempt, 'pid': 4321, 'state': state}))
    command = f'python.exe -m bff.services.cluster.runner --request-file "{request}"'
    cmd64 = base64.b64encode(command.encode()).decode()
    prefix = r'''
function Get-CimInstance {
 param($ClassName,$Filter)
 switch($ClassName) {
 'Win32_OperatingSystem' { return [pscustomobject]@{FreePhysicalMemory=1000000} }
 'Win32_PhysicalMemory' { return [pscustomobject]@{Capacity=34359738368} }
 'Win32_Process' { return [pscustomobject]@{ProcessId=4321;ParentProcessId=1;CreationDate=[DateTime]::UtcNow;WorkingSetSize=1000;CommandLine=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__CMD__'))} }
 }
}
function Get-Process { throw 'TEST: must not open active or unverified process' }
'''.replace('__CMD__', cmd64)
    script = prefix + maintenance_script(str(tmp_path), True)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                             '$s=[Console]::In.ReadToEnd(); & ([scriptblock]::Create($s))'],
                            input=script.encode(), capture_output=True, timeout=30, check=True)
    report = json.loads(result.stdout)
    assert report['stopped_count'] == 0
    assert report['processes'][0]['action'] == 'PRESERVED'
    assert 'error_type' not in report['processes'][0]
