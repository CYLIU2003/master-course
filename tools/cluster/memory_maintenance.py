"""Inspect registered Windows PCs and release only proven terminal worker remnants.

No reboot, cache purge, application shutdown, solver probe, or license release.
Active/unknown attempts remain untouched; cancel them through the controller first.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.contracts import ClusterConfig
from bff.services.cluster.transport import ssh_command
from tools.cluster.atomic_file import replace_bytes


def maintenance_script(workspace: str, apply: bool) -> str:
    """Pass trusted configuration as base64 data, never executable shell text."""
    encoded = base64.b64encode(workspace.encode('utf-8')).decode('ascii')
    return r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$workspace=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__WORKSPACE__'))
$apply=__APPLY__
$before=Get-CimInstance Win32_OperatingSystem
$installed=(Get-CimInstance Win32_PhysicalMemory | Measure-Object Capacity -Sum).Sum / 1GB
$processes=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")
$records=@()
foreach($p in $processes) {
    $row=[ordered]@{pid=$p.ProcessId; parent_pid=$p.ParentProcessId; created=$p.CreationDate.ToUniversalTime().ToString('o'); working_set_mb=[math]::Round($p.WorkingSetSize/1MB,2); action='PRESERVED'; reason='Not an identified terminal cluster runner'}
    $command=[string]$p.CommandLine
    if($command -match '-m bff\.services\.cluster\.runner' -and $command -match '--request-file\s+"?([^"\r\n]+?request\.json)"?(?:\s|$)') {
        $requestPath=[IO.Path]::GetFullPath($Matches[1])
        $launchRoot=[IO.Path]::GetFullPath((Join-Path $workspace '.launch')).TrimEnd('\')+'\'
        if($requestPath.StartsWith($launchRoot,[StringComparison]::OrdinalIgnoreCase)) {
            $attempt=Split-Path (Split-Path $requestPath -Parent) -Leaf
            $row.attempt_id=$attempt
            if($attempt -match '^[A-Za-z0-9_-]+$') {
                $statePath=Join-Path (Join-Path $workspace $attempt) 'state.json'
                try {
                    $state=Get-Content -Raw -Encoding UTF8 -LiteralPath $statePath | ConvertFrom-Json
                    $row.state=$state.state
                    $oldEnough=$state.finished_at -and ([DateTimeOffset]::UtcNow-[DateTimeOffset]::Parse($state.finished_at)).TotalSeconds -ge 300
                    if($state.id -eq $attempt -and $state.pid -eq $p.ProcessId -and $state.state -in @('COMPLETED','FAILED','CANCELLED','BLOCKED') -and $oldEnough) {
                        # Never deserialize request.json: it contains the full large
                        # optimization bundle. Use the small launch receipt instead.
                        $launch=Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path (Split-Path $requestPath -Parent) 'state.json') | ConvertFrom-Json
                        if($launch.id -ne $attempt -or -not $launch.manifest_sha256 -or $launch.manifest_sha256 -ne $state.manifest_sha256) { throw 'Launch binding differs' }
                        if(-not (Test-Path -LiteralPath (Join-Path $workspace ($attempt+'.zip'))) -or (Test-Path -LiteralPath (Join-Path $workspace ($attempt+'.zip.tmp')))) { throw 'Artifact collection not finished' }
                        # The retained Process object binds Kill to the opened process,
                        # while birth time and command prevent a recycled-PID match.
                        $live=Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ProcessId)"
                        if($live.CreationDate -eq $p.CreationDate -and $live.CommandLine -eq $command) {
                            $handle=Get-Process -Id $p.ProcessId -ErrorAction Stop
                            try {
                                $null=$handle.Handle
                                if([math]::Abs(($handle.StartTime.ToUniversalTime()-$p.CreationDate.ToUniversalTime()).TotalSeconds) -gt 0.01) { throw 'Process identity changed' }
                                $birth=$handle.StartTime.ToFileTimeUtc()
                                $identity=([string]($birth -shr 32))+':'+([string]($birth -band 4294967295))
                                if($state.process_identity -ne $identity) { throw 'Saved process birth token differs' }
                                $row.reason='Terminal attempt older than five minutes; matching PID, creation time and request path'
                                $row.action='ELIGIBLE'
                                if($apply) { $handle.Kill(); $handle.WaitForExit(10000) | Out-Null; if(-not $handle.HasExited) {throw 'Process did not exit'}; $row.action='STOPPED' }
                            } finally { $handle.Dispose() }
                        }
                    } else { $row.reason='Active, recent, unknown, or mismatched attempt; retained' }
                } catch { $row.reason='State or process identity could not be verified; retained'; $row.error_type=$_.Exception.GetType().Name }
            }
        }
    }
    $records+=[pscustomobject]$row
}
$after=Get-CimInstance Win32_OperatingSystem
[ordered]@{hostname=$env:COMPUTERNAME; observed_at_utc=[DateTime]::UtcNow.ToString('o'); installed_ram_gb=$installed; free_before_gb=[math]::Round($before.FreePhysicalMemory/1MB,3); free_after_gb=[math]::Round($after.FreePhysicalMemory/1MB,3); apply=$apply; processes=$records; stopped_count=@($records | Where-Object action -eq 'STOPPED').Count; scope='Terminal cluster runners only; OS cache and other applications preserved'} | ConvertTo-Json -Depth 8 -Compress
'''.replace('__WORKSPACE__', encoded).replace('__APPLY__', '$true' if apply else '$false')


def inspect_worker(worker, apply: bool) -> dict:
    # Windows OpenSSH commonly invokes cmd.exe (8191-character command limit).
    # Keep the command short and pass the fixed script over standard input.
    bootstrap = '$s=[Console]::In.ReadToEnd(); & ([scriptblock]::Create($s))'
    encoded = base64.b64encode(bootstrap.encode('utf-16le')).decode('ascii')
    command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
    if worker.transport == 'ssh':
        command = ssh_command(worker, ' '.join(command))
    try:
        result = subprocess.run(command, input=maintenance_script(worker.workspace, apply).encode('utf-8'),
                                capture_output=True, timeout=90)
        if result.returncode:
            return {'worker_id': worker.id, 'status': 'UNVERIFIED', 'returncode': result.returncode,
                    'error': result.stderr.decode('utf-8', errors='replace')[-1200:]}
        return {'worker_id': worker.id, 'status': 'INSPECTED', **json.loads(result.stdout.decode('utf-8-sig'))}
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return {'worker_id': worker.id, 'status': 'UNVERIFIED', 'error_type': type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = ClusterConfig.model_validate_json(args.config.read_bytes())
    if args.output.exists():
        parser.error('Use a new report path; maintenance evidence is not overwritten')
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda worker: inspect_worker(worker, args.apply), config.workers))
    report = {'mode': 'terminal_remnant_cleanup' if args.apply else 'inspection', 'workers': rows,
              'registered': len(rows), 'inspected': sum(r['status'] == 'INSPECTED' for r in rows),
              'stopped': sum(r.get('stopped_count', 0) for r in rows), 'solver_started': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    replace_bytes(args.output, json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8'))
    print(json.dumps({k: v for k, v in report.items() if k != 'workers'}))
    return 0 if report['inspected'] == report['registered'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
