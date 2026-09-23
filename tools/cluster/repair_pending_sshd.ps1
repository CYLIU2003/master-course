# Run by an elevated, independent scheduled task; the SSH transport may disconnect.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ExpectedComputer,
    [Parameter(Mandatory=$true)][string]$StateDirectory,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

function Invoke-ServiceControl {
    param([string[]]$Arguments)
    $output = & "$env:WINDIR\System32\sc.exe" @Arguments 2>&1 | Out-String
    return [pscustomobject]@{code=$LASTEXITCODE; output=$output.Trim()}
}

function Repair-PendingSshService {
    param([string]$BinaryPath, [string]$ServiceSecurity, [int]$WaitSeconds=45)
    # A failed config call proves the actual SCM state; DeleteFlag in the registry
    # can be zero while ChangeServiceConfig still returns ERROR_SERVICE_MARKED_FOR_DELETE.
    $configure = Invoke-ServiceControl @('config', 'sshd', 'start=', 'auto')
    if ($configure.code -eq 0) { return 'AUTOMATIC' }
    if ($configure.code -notin @(1072, 1060)) { throw "Cannot configure sshd: $($configure.code) $($configure.output)" }
    if ($configure.code -eq 1072) {
        $stop = Invoke-ServiceControl @('stop', 'sshd')
        if ($stop.code -notin @(0, 1060, 1062)) { throw "Cannot stop pending sshd: $($stop.code) $($stop.output)" }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
    do {
        $query = Invoke-ServiceControl @('query', 'sshd')
        if ($query.code -eq 1060) { break }
        if ($query.code -notin @(0, 1072)) { throw "Cannot inspect sshd: $($query.code)" }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'SSHD_PENDING_HANDLES: close Services/Computer Management on this PC before retrying recovery.' }
        Start-Sleep -Milliseconds 500
    } while ($true)
    New-Service -Name sshd -DisplayName 'OpenSSH SSH Server' -BinaryPathName ('"' + $BinaryPath + '"') -StartupType Automatic | Out-Null
    # Preserve the previous service DACL. These are the privileges from Microsoft's installer.
    foreach ($arguments in @(
        @('sdset', 'sshd', $ServiceSecurity),
        @('privs', 'sshd', 'SeAssignPrimaryTokenPrivilege/SeTcbPrivilege/SeBackupPrivilege/SeRestorePrivilege/SeImpersonatePrivilege')
    )) {
        $result = Invoke-ServiceControl $arguments
        if ($result.code -ne 0) { throw "Cannot restore sshd service security: $($result.code)" }
    }
    $start = Invoke-ServiceControl @('start', 'sshd')
    if ($start.code -notin @(0, 1056)) { throw "Cannot start restored sshd: $($start.code) $($start.output)" }
    return 'RECREATED'
}

if ($env:COMPUTERNAME -ine $ExpectedComputer) { throw 'Recovery target computer does not match.' }
if (-not [Environment]::Is64BitProcess) { throw 'Run recovery in 64-bit Windows PowerShell.' }
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator or SYSTEM is required.' }
$binary = Join-Path $env:WINDIR 'System32\OpenSSH\sshd.exe'
$signature = Get-AuthenticodeSignature -LiteralPath $binary
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'The Windows OpenSSH server must have a valid Microsoft signature.'
}
$validation = Start-Process -FilePath $binary -ArgumentList '-t' -PassThru -WindowStyle Hidden
try {
    # Start-Process -Wait waits on a process tree and can hang in an SSH job object.
    if (-not $validation.WaitForExit(15000)) { $validation.Kill(); throw 'OpenSSH configuration validation timed out.' }
    if ($validation.ExitCode -ne 0) { throw 'OpenSSH configuration validation failed; no services were stopped.' }
} finally { $validation.Dispose() }
$before = Get-CimInstance Win32_Service -Filter "Name='sshd'"
$savedSecurity = Join-Path $StateDirectory 'service-before.sddl'
if ($before) {
    $security = Invoke-ServiceControl @('sdshow', 'sshd')
    if ($security.code -ne 0) { throw "Cannot preserve the current sshd service security: $($security.code)" }
    $sddl = @($security.output -split '\r?\n' | Where-Object { $_ -match '^D:' })
} elseif (Test-Path -LiteralPath $savedSecurity) {
    $sddl = @((Get-Content -LiteralPath $savedSecurity -Raw).Trim())
} else { throw 'Missing service and recovery backup; refusing to invent service permissions.' }
if ($sddl.Count -ne 1) { throw 'Cannot identify the existing service DACL.' }
if ($ValidateOnly) {
    [pscustomobject]@{validated=$true; computer=$env:COMPUTERNAME; binary=$binary; service_present=[bool]$before} | ConvertTo-Json -Compress
    return
}
New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $savedSecurity)) {
    $before | Select-Object Name,State,StartMode,PathName,ProcessId,StartName | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $StateDirectory 'service-before.json')
    $sddl[0] | Set-Content -Encoding UTF8 -LiteralPath $savedSecurity
}
$state = @{computer=$env:COMPUTERNAME; state='REPAIRING'; started_at=[DateTime]::UtcNow.ToString('o')}
$state | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $StateDirectory 'state.json')
try {
    $state.action = Repair-PendingSshService -BinaryPath $binary -ServiceSecurity $sddl[0]
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $after = Get-CimInstance Win32_Service -Filter "Name='sshd'"
        if ($after -and $after.State -eq 'Running' -and $after.StartMode -eq 'Auto') { break }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Restored sshd did not reach Running/Auto.' }
        Start-Sleep -Milliseconds 500
    } while ($true)
    $state.state = 'COMPLETED'
    $state.service_pid = $after.ProcessId
    $state.service_path = $after.PathName
} catch {
    $state.state = 'FAILED'
    $state.error = $_.Exception.Message
} finally {
    $state.finished_at = [DateTime]::UtcNow.ToString('o')
    $state | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $StateDirectory 'state.json')
}
if ($state.state -ne 'COMPLETED') { exit 1 }
