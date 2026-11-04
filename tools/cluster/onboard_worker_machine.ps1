# Run ON a new worker PC in an elevated PowerShell, in a folder that also holds controller.pub.
# One step replaces install_openssh_server.ps1 + enable_worker_access.ps1 for a PC that is not
# in the roster yet: installs/starts OpenSSH Server, installs the controller public key for the
# CURRENT user (administrator accounts use administrators_authorized_keys), then writes
# onboard_report.json (identity, RAM, sshd, Tailscale IP) for the controller to read.
# It does not copy the Gurobi secret, edit sshd_config, add firewall rules beyond the default
# OpenSSH rule, or change Windows Update. Usage:
#   powershell -ExecutionPolicy Bypass -File onboard_worker_machine.ps1
[CmdletBinding()]
param([string]$BundleDirectory, [string]$ControllerTailscaleIp = '100.74.254.53')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($BundleDirectory)) { $BundleDirectory = $PSScriptRoot }
if ([string]::IsNullOrWhiteSpace($BundleDirectory) -and $PSCommandPath) { $BundleDirectory = Split-Path -Parent $PSCommandPath }
if ([string]::IsNullOrWhiteSpace($BundleDirectory)) { throw 'Cannot locate the folder. Pass -BundleDirectory.' }

# The log (no secrets: only service/identity state) is sent back to the controller by Taildrop,
# so a failure can be diagnosed without retyping the error.
$logPath = Join-Path $BundleDirectory ("onboard_log_{0}.txt" -f $env:COMPUTERNAME)
Start-Transcript -LiteralPath $logPath -Force | Out-Null
function Send-LogToController {
    try { Stop-Transcript | Out-Null } catch {}
    $tsExe = 'C:\Program Files\Tailscale\tailscale.exe'
    if (-not (Test-Path -LiteralPath $tsExe)) { $c = Get-Command tailscale -ErrorAction SilentlyContinue; if ($c) { $tsExe = $c.Source } else { return } }
    try { & $tsExe file cp $logPath ("{0}:" -f $ControllerTailscaleIp) 2>$null; Write-Host "Log sent to controller: $logPath" } catch { Write-Host "Could not send log; it is at $logPath" }
}
trap { Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red; Send-LogToController; break }

function Invoke-ServiceControl {
    param([string[]]$Arguments)
    $output = & "$env:WINDIR\System32\sc.exe" @Arguments 2>&1 | Out-String
    return [pscustomobject]@{code=$LASTEXITCODE; output=$output.Trim()}
}
$keyFile = Join-Path $BundleDirectory 'controller.pub'
if (-not (Test-Path -LiteralPath $keyFile -PathType Leaf)) { throw 'controller.pub must be in the same folder as this script.' }
$publicKey = (Get-Content -LiteralPath $keyFile -Raw).Trim()
if ($publicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/]+=*( .*)?$') { throw 'Expected the controller Ed25519 public key.' }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this in an elevated PowerShell (Run as administrator).'
}
$adminSid = 'S-1-5-32-544'
$isAdminAccount = @($identity.Groups | ForEach-Object { $_.Value }) -contains $adminSid

# 1) OpenSSH Server. Report a second OpenSSH install (e.g. Program Files (x86)) instead of mixing them.
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
$service = Get-CimInstance Win32_Service -Filter "Name='sshd'"
$running = Get-Process sshd -ErrorAction SilentlyContinue | Select-Object -First 1
Write-Host ("Before: capability={0} service_path={1} start={2} state={3} running_exe={4}" -f $(if ($cap) { $cap.State } else { 'none' }),
    $(if ($service) { $service.PathName } else { 'none' }), $(if ($service) { $service.StartMode } else { '' }),
    $(if ($service) { $service.State } else { '' }), $(try { $running.Path } catch { '' }))
if ($cap -and [string]$cap.State -match 'Pending') { throw "REBOOT_REQUIRED: OpenSSH.Server is $($cap.State). Restart Windows, then run this script again." }
if (-not $service -and $running) {
    throw "SSHD_NOT_REGISTERED: sshd.exe runs from $($running.Path) but no sshd service exists. Not changed; report this to the controller."
}
if (-not $service) {
    if (-not $cap) { throw 'OpenSSH.Server capability not found on this Windows build.' }
    Write-Host "Installing $($cap.Name) (needs internet) ..."
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
    $cap = Get-WindowsCapability -Online -Name $cap.Name
    if ([string]$cap.State -ne 'Installed') { throw "REBOOT_REQUIRED: OpenSSH.Server is $($cap.State) after install. Restart Windows, then run this script again." }
    $service = Get-CimInstance Win32_Service -Filter "Name='sshd'"
    if (-not $service) { throw 'OpenSSH.Server installed but the sshd service is missing.' }
}
if ($service.PathName -notmatch '\\System32\\OpenSSH\\sshd\.exe') {
    # A manually installed Win32-OpenSSH (e.g. Program Files (x86)) is used as-is if it is signed.
    $binaryPath = ($service.PathName -replace '^"([^"]+)".*$', '$1').Trim()
    $signature = Get-AuthenticodeSignature -LiteralPath $binaryPath
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw "UNSIGNED_OPENSSH: sshd service points to $binaryPath without a valid Microsoft signature. Not changed."
    }
    Write-Host "Using the manually installed OpenSSH: $binaryPath (Microsoft-signed)"
}
if ($service.StartMode -ne 'Auto') {
    $configure = Invoke-ServiceControl @('config', 'sshd', 'start=', 'auto')
    if ($configure.code -eq 1072) { throw 'SSHD_PENDING_DELETE: the sshd service is marked for deletion. Keys were not changed; report this to the controller.' }
    if ($configure.code -ne 0) { throw "Cannot set sshd to automatic ($($configure.code)): $($configure.output)" }
}
if ((Get-Service sshd).Status -ne 'Running') { Start-Service sshd }

# 2) Controller key for the current user
if ($isAdminAccount) {
    $keyPath = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'ssh\administrators_authorized_keys'
    $allowedSids = @('S-1-5-18', $adminSid); $ownerSid = $adminSid
} else {
    $keyPath = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.ssh\authorized_keys'
    $allowedSids = @('S-1-5-18', $identity.User.Value); $ownerSid = $identity.User.Value
}
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1') -Force -ErrorAction Stop
New-Item -ItemType Directory -Path (Split-Path -Parent $keyPath) -Force | Out-Null
$existing = if (Test-Path -LiteralPath $keyPath) { [IO.File]::ReadAllText($keyPath) } else { '' }
if (-not ($existing -split '\r?\n' | Where-Object { $_.Trim() -eq $publicKey })) {
    if (Test-Path -LiteralPath $keyPath) { Copy-Item -LiteralPath $keyPath -Destination ($keyPath + '.backup-' + [Guid]::NewGuid().ToString('N')) }
    [IO.File]::WriteAllText($keyPath, $existing.TrimEnd() + "`n" + $publicKey + "`n", [Text.UTF8Encoding]::new($false))
}
$acl = [IO.File]::GetAccessControl($keyPath, [Security.AccessControl.AccessControlSections]::Access)
$acl.SetAccessRuleProtection($true, $false)
foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRuleSpecific($rule) }
foreach ($sid in $allowedSids) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid), 'FullControl', 'Allow'))
}
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new($ownerSid))
[IO.File]::SetAccessControl($keyPath, $acl)
if (-not ([IO.File]::ReadAllLines($keyPath) -contains $publicKey)) { throw 'Public key could not be verified after writing.' }

# 3) Report
Start-Sleep -Seconds 2
$svc = Get-CimInstance Win32_Service -Filter "Name='sshd'"
# Get-NetTCPConnection can miss the listener on some PCs; an actual loopback connect is authoritative.
$listen = $false
$probe = [Net.Sockets.TcpClient]::new()
try { $listen = $probe.ConnectAsync('127.0.0.1', 22).Wait(3000) -and $probe.Connected } catch { $listen = $false } finally { $probe.Dispose() }
$ts = Get-Command tailscale -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $ts -and (Test-Path 'C:\Program Files\Tailscale\tailscale.exe')) { $ts = [pscustomobject]@{Source='C:\Program Files\Tailscale\tailscale.exe'} }
$tsIp = if ($ts) { try { (& $ts.Source ip -4 2>$null | Select-Object -First 1) } catch { $null } } else { $null }
$cs = Get-CimInstance Win32_ComputerSystem
$report = [ordered]@{
    computer = $env:COMPUTERNAME; user = $env:USERNAME; administrator_account = $isAdminAccount
    key_path = $keyPath; sshd_state = [string]$svc.State; sshd_start_mode = $svc.StartMode; listening_on_22 = $listen
    tailscale_ip = $tsIp; ram_gib = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    os = (Get-CimInstance Win32_OperatingSystem).Caption
}
$reportPath = Join-Path $BundleDirectory 'onboard_report.json'
[IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
$report | ConvertTo-Json | Write-Host
if ($svc.State -ne 'Running' -or $svc.StartMode -ne 'Auto' -or -not $listen) { throw 'OpenSSH Server is not in the expected state.' }
Write-Host "OK: onboarded $env:COMPUTERNAME / $env:USERNAME. Keep it powered and on the tailnet."
Send-LogToController
