# Run on the target worker as the Windows user listed in workers.json.
[CmdletBinding()]
param([string]$BundleDirectory, [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# Windows PowerShell 5.1 can evaluate parameter defaults before PSScriptRoot is populated.
# Resolve the bundle location in the script body, independent of the working directory.
if ([string]::IsNullOrWhiteSpace($BundleDirectory)) {
    $BundleDirectory = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($BundleDirectory) -and $PSCommandPath) {
        $BundleDirectory = Split-Path -Parent $PSCommandPath
    }
}
if ([string]::IsNullOrWhiteSpace($BundleDirectory)) {
    throw 'Cannot locate the setup folder. Extract the ZIP and run SETUP.cmd, or pass -BundleDirectory.'
}
$BundleDirectory = (Resolve-Path -LiteralPath $BundleDirectory).ProviderPath
foreach ($required in @('workers.json', 'controller.pub')) {
    if (-not (Test-Path -LiteralPath (Join-Path $BundleDirectory $required) -PathType Leaf)) {
        throw "Missing $required. Extract all files from the setup ZIP together."
    }
}
$roster = Get-Content -LiteralPath (Join-Path $BundleDirectory 'workers.json') -Raw | ConvertFrom-Json
$normalize = { param($value) ($value.ToLowerInvariant() -replace '[^a-z0-9]', '') }
$matched = @($roster | Where-Object { (& $normalize $_.name) -eq (& $normalize $env:COMPUTERNAME) })
if ($matched.Count -ne 1) { throw 'This computer is not uniquely registered in the worker pool.' }
$worker = $matched[0]
if ($env:USERNAME -ine $worker.ssh_user) { throw "Run this setup as $($worker.ssh_user). Current user is $env:USERNAME." }
$publicKey = (Get-Content -LiteralPath (Join-Path $BundleDirectory 'controller.pub') -Raw).Trim()
if ($publicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/]+=*( .*)?$') { throw 'Expected the controller Ed25519 public key.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$administratorSid = 'S-1-5-32-544'
$isAdministratorAccount = @($identity.Groups | ForEach-Object { $_.Value }) -contains $administratorSid
if (-not $ValidateOnly -and $isAdministratorAccount -and -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'This account is an administrator. Run SETUP.cmd using Run as administrator.'
}
if ($isAdministratorAccount) {
    $profileRoot = [Environment]::GetFolderPath('CommonApplicationData')
    if ([string]::IsNullOrWhiteSpace($profileRoot)) { throw 'Windows CommonApplicationData is unavailable.' }
    $keyPath = Join-Path $profileRoot 'ssh/administrators_authorized_keys'
    $allowedSids = @('S-1-5-18', $administratorSid)
} else {
    $profileRoot = [Environment]::GetFolderPath('UserProfile')
    if ([string]::IsNullOrWhiteSpace($profileRoot)) { throw 'Windows UserProfile is unavailable.' }
    $keyPath = Join-Path $profileRoot '.ssh/authorized_keys'
    $allowedSids = @('S-1-5-18', $identity.User.Value)
}
function Install-ControllerPublicKey {
    param([string]$keyPath, [string]$publicKey, [string[]]$allowedSids, [string]$ownerSid)
    # A PowerShell 7 parent can leave PSModulePath pointing at incompatible modules.
    Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1') -Force -ErrorAction Stop
    if ([string]::IsNullOrWhiteSpace($keyPath)) { throw "Authorized key destination is empty." }
    $directory = Split-Path -Parent $keyPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $existing = if (Test-Path -LiteralPath $keyPath) { [IO.File]::ReadAllText($keyPath) } else { '' }
    if (-not ($existing -split '\r?\n' | Where-Object { $_.Trim() -eq $publicKey })) {
        if (Test-Path -LiteralPath $keyPath) {
            Copy-Item -LiteralPath $keyPath -Destination ($keyPath + '.backup-' + ([Guid]::NewGuid().ToString('N')))
        }
        [IO.File]::WriteAllText($keyPath, $existing.TrimEnd() + "`n" + $publicKey + "`n", [Text.UTF8Encoding]::new($false))
    }
    # Read/write only the DACL. Copying a whole security descriptor can require
    # SeSecurityPrivilege even for a standard user's own authorized_keys file.
    $acl = [IO.File]::GetAccessControl($keyPath, [Security.AccessControl.AccessControlSections]::Access)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRuleSpecific($rule) }
    foreach ($sid in $allowedSids) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid), 'FullControl', 'Allow')
        $acl.AddAccessRule($rule)
    }
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new($ownerSid))
    [IO.File]::SetAccessControl($keyPath, $acl)
    if (-not (Get-Acl -LiteralPath $keyPath).AreAccessRulesProtected) { throw "SSH key permissions were not applied." }
    if (-not ([IO.File]::ReadAllLines($keyPath) -contains $publicKey)) { throw "SSH public key could not be verified after writing." }
}

function Invoke-WorkerServiceControl {
    param([string[]]$Arguments)
    $output = & "$env:WINDIR\System32\sc.exe" @Arguments 2>&1 | Out-String
    return [pscustomobject]@{code=$LASTEXITCODE; output=$output.Trim()}
}

function Initialize-WorkerSshService {
    param([bool]$IsElevated)
    # CIM snapshots do not keep ServiceController handles alive across a change.
    $service = Get-CimInstance Win32_Service -Filter "Name='sshd'"
    if (-not $service) { throw 'SSHD_SERVICE_MISSING: the controller must repair OpenSSH before key setup.' }
    if ($IsElevated -and $service.StartMode -ne 'Auto') {
        $configuration = Invoke-WorkerServiceControl @('config', 'sshd', 'start=', 'auto')
        if ($configuration.code -eq 1072) {
            throw "SSHD_PENDING_DELETE on $env:COMPUTERNAME. Keys were not changed. Leave this PC online; the controller can repair its service."
        }
        if ($configuration.code -ne 0) { throw "Cannot configure OpenSSH ($($configuration.code)): $($configuration.output)" }
    }
    if ($service.State -ne 'Running') {
        if (-not $IsElevated) { throw 'sshd is stopped. An administrator must start it.' }
        $startResult = Invoke-WorkerServiceControl @('start', 'sshd')
        if ($startResult.code -notin @(0, 1056)) { throw "Cannot start OpenSSH: $($startResult.output)" }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $current = Get-CimInstance Win32_Service -Filter "Name='sshd'"
        if ($current -and $current.State -eq 'Running' -and (-not $IsElevated -or $current.StartMode -eq 'Auto')) { return }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'OpenSSH did not reach its expected running/startup state.' }
        Start-Sleep -Milliseconds 500
    } while ($true)
}

if ($ValidateOnly) {
    [pscustomobject]@{validated=$true; bundle_directory=$BundleDirectory; computer=$env:COMPUTERNAME; user=$env:USERNAME; key_path=$keyPath} | ConvertTo-Json -Compress
    return
}
$ownerSid = if ($isAdministratorAccount) { $administratorSid } else { $identity.User.Value }
Initialize-WorkerSshService -IsElevated ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
Install-ControllerPublicKey -keyPath $keyPath -publicKey $publicKey -allowedSids $allowedSids -ownerSid $ownerSid
Write-Host "Worker access configured: $($worker.name) / $env:USERNAME"
Write-Host 'Keep this computer powered and connected. The controller will verify SSH automatically.'
Write-Host 'This script does not copy the Gurobi secret, change firewall rules, or disable Windows Update.'
