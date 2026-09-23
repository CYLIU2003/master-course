"""Run the production service-repair flow with isolated SCM responses in WinPS5.1."""
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows service recovery')
SCRIPT = Path(__file__).resolve().parents[1] / 'tools/cluster/repair_pending_sshd.ps1'


@pytest.mark.parametrize('scenario', ['healthy', 'pending', 'missing', 'held', 'denied', 'privilege_failure'])
def test_recovery_preserves_healthy_services_and_handles_deletion(tmp_path, scenario):
    harness = tmp_path / 'harness.ps1'
    harness.write_text(r'''
param($Source, $Scenario)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$definition=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Repair-PendingSshService'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$script:calls=@(); $script:created=0
function Invoke-ServiceControl {
    param([string[]]$Arguments)
    $verb=$Arguments[0]; $script:calls+=$verb
    if ($Arguments[1] -ne 'sshd') { throw 'Touched an unrelated service' }
    $code=0
    if($verb -eq 'config'){
        $code=switch($Scenario){'healthy'{0}; 'missing'{1060}; 'denied'{5}; default{1072}}
    }
    if($verb -eq 'query'){$code=if($Scenario -eq 'held'){1072}else{1060}}
    if($verb -eq 'privs' -and $Scenario -eq 'privilege_failure'){$code=5}
    if($verb -eq 'sdset' -and $Arguments[2] -ne 'D:(A;;GA;;;SY)'){throw 'Lost the original DACL'}
    [pscustomobject]@{code=$code; output='stub'}
}
function New-Service {
    param($Name,$DisplayName,$BinaryPathName,$StartupType)
    if($Name -ne 'sshd' -or $BinaryPathName -ne '"C:\Windows\System32\OpenSSH\sshd.exe"' -or $StartupType -ne 'Automatic'){throw 'Wrong service installation'}
    $script:created++
}
$failed=$false
try{$result=Repair-PendingSshService -BinaryPath 'C:\Windows\System32\OpenSSH\sshd.exe' -ServiceSecurity 'D:(A;;GA;;;SY)' -WaitSeconds 0}catch{$failed=$true; $message=$_.Exception.Message}
switch($Scenario){
 'healthy'{if($failed -or $script:created -ne 0 -or ($script:calls -join ',') -ne 'config'){throw 'Changed healthy service'}}
 'pending'{if($failed -or $result -ne 'RECREATED' -or ($script:calls -join ',') -ne 'config,stop,query,sdset,privs,start'){throw 'Pending service recovery failed'}}
 'missing'{if($failed -or $script:created -ne 1 -or $script:calls -contains 'stop'){throw 'Missing service recovery failed'}}
 'held'{if(-not $failed -or $message -notmatch 'SSHD_PENDING_HANDLES' -or $script:created -ne 0){throw 'Unreleased handles not reported'}}
 'denied'{if(-not $failed -or ($script:calls -join ',') -ne 'config'){throw 'Access denial changed service'}}
 'privilege_failure'{if(-not $failed -or $script:calls -contains 'start'){throw 'Started service without restored privileges'}}
}
Write-Output 'RECOVERY_FLOW_OK'
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness),
                             '-Source', str(SCRIPT), '-Scenario', scenario], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert b'RECOVERY_FLOW_OK' in result.stdout


@pytest.mark.parametrize('scenario', ['healthy', 'manual', 'pending', 'missing', 'stopped', 'nonadmin_stopped'])
def test_setup_checks_service_before_registering_keys(tmp_path, scenario):
    harness = tmp_path / 'setup_service_check.ps1'
    harness.write_text(r'''
param($Source,$Scenario)
$ErrorActionPreference='Stop'
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$definition=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Initialize-WorkerSshService'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$script:calls=@()
$script:mode=if($Scenario -in @('manual','pending')){'Manual'}else{'Auto'}
$script:state=if($Scenario -in @('stopped','nonadmin_stopped')){'Stopped'}else{'Running'}
function Get-CimInstance {param($ClassName,$Filter) if($Scenario -ne 'missing'){[pscustomobject]@{StartMode=$script:mode;State=$script:state}}}
function Invoke-WorkerServiceControl {
 param([string[]]$Arguments)
 if($Arguments[1] -ne 'sshd'){throw 'Unexpected service'}
 $script:calls+=$Arguments[0]
 if($Scenario -eq 'pending'){return [pscustomobject]@{code=1072;output='localized error'}}
 if($Arguments[0] -eq 'config'){$script:mode='Auto'}
 if($Arguments[0] -eq 'start'){$script:state='Running'}
 [pscustomobject]@{code=0;output='success'}
}
$failed=$false
try{Initialize-WorkerSshService -IsElevated ($Scenario -ne 'nonadmin_stopped')}catch{$failed=$true;$message=$_.Exception.Message}
switch($Scenario){
 'healthy'{if($failed -or $script:calls.Count){throw 'Changed a healthy service'}}
 'manual'{if($failed -or ($script:calls -join ',') -ne 'config'){throw 'Automatic startup not configured'}}
 'stopped'{if($failed -or ($script:calls -join ',') -ne 'start'){throw 'Stopped service not started'}}
 'pending'{if(-not $failed -or $message -notmatch 'SSHD_PENDING_DELETE' -or ($script:calls -join ',') -ne 'config'){throw 'Pending deletion was not reported'}}
 'missing'{if(-not $failed -or $message -notmatch 'SSHD_SERVICE_MISSING' -or $script:calls.Count){throw 'Missing service changed'}}
 'nonadmin_stopped'{if(-not $failed -or $script:calls.Count){throw 'Unprivileged service start attempted'}}
}
$body=$ast.Extent.Text
if($body.LastIndexOf('Initialize-WorkerSshService -IsElevated') -gt $body.LastIndexOf('Install-ControllerPublicKey -keyPath')){throw 'Keys changed before service preflight'}
Write-Output 'SETUP_SERVICE_OK'
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness),
                             '-Source', str(SCRIPT.with_name('enable_worker_access.ps1')), '-Scenario', scenario],
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert b'SETUP_SERVICE_OK' in result.stdout
