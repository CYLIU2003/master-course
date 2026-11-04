# Read-only interrogation of a candidate worker PC (run ON that PC, before SSH/key setup).
# Changes nothing, installs nothing, reads no secrets. Output: human summary + JSON file
# whose fields map onto the workers.json entry (name, ssh_user, tailscale_ip, ...).
# Usage:  powershell -ExecutionPolicy Bypass -File inspect_new_worker.ps1 [-OutFile path.json]
[CmdletBinding()]
param([string]$OutFile)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Off

function Try-Get { param([scriptblock]$Block) try { & $Block } catch { $null } }
function Find-Exe {
    param([string]$Name, [string[]]$Extra = @())
    # Skip the Microsoft Store "App execution alias" stubs; they are not real installs.
    $cmd = Get-Command $Name -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -and $_.Source -notmatch '\\WindowsApps\\' } | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    foreach ($p in $Extra) { if (Test-Path -LiteralPath $p) { return $p } }
    return $null
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$adminSid = 'S-1-5-32-544'
$inAdminGroup = @($identity.Groups | ForEach-Object { $_.Value }) -contains $adminSid
$elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

$os = Try-Get { Get-CimInstance Win32_OperatingSystem }
$cs = Try-Get { Get-CimInstance Win32_ComputerSystem }
$cpu = Try-Get { Get-CimInstance Win32_Processor | Select-Object -First 1 }
$disks = Try-Get { Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
    [ordered]@{drive=$_.DeviceID; size_gib=[math]::Round($_.Size/1GB,1); free_gib=[math]::Round($_.FreeSpace/1GB,1)} } }

# --- Tailscale (CLI status only; no auth keys are read) ---
$tsExe = Find-Exe 'tailscale' @('C:\Program Files\Tailscale\tailscale.exe')
$ts = [ordered]@{installed=[bool]$tsExe; ipv4=$null; backend_state=$null; hostname=$null; tailnet=$null; peers_online=$null}
if ($tsExe) {
    $ts.ipv4 = Try-Get { (& $tsExe ip -4 2>$null | Select-Object -First 1) }
    $json = Try-Get { & $tsExe status --json 2>$null | ConvertFrom-Json }
    if ($json) {
        $ts.backend_state = $json.BackendState
        $ts.hostname = $json.Self.HostName
        $ts.tailnet = $json.CurrentTailnet.Name
        $ts.peers_online = @($json.Peer.PSObject.Properties | Where-Object { $_.Value.Online }).Count
    }
}

# --- OpenSSH server ---
$sshd = Try-Get { Get-CimInstance Win32_Service -Filter "Name='sshd'" }
$sshCap = Try-Get { Get-WindowsCapability -Online -Name 'OpenSSH.Server*' -ErrorAction Stop | Select-Object -First 1 }
$listen22 = Try-Get { @(Get-NetTCPConnection -State Listen -LocalPort 22 -ErrorAction Stop).Count -gt 0 }
$fw = Try-Get { Get-NetFirewallRule -DisplayName '*ssh*' -ErrorAction Stop | Select-Object DisplayName, Enabled, Direction, Action }
$sshdConfig = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'ssh\sshd_config'
$authKeysAdmin = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'ssh\administrators_authorized_keys'
$authKeysUser = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.ssh\authorized_keys'
$ssh = [ordered]@{
    sshd_service_present = [bool]$sshd
    sshd_state = if ($sshd) { $sshd.State } else { $null }
    sshd_start_mode = if ($sshd) { $sshd.StartMode } else { $null }
    openssh_server_capability = if ($sshCap) { [string]$sshCap.State } else { 'unknown (needs elevation or unsupported)' }
    listening_on_22 = $listen22
    sshd_config_present = (Test-Path -LiteralPath $sshdConfig)
    administrators_authorized_keys_present = (Test-Path -LiteralPath $authKeysAdmin)
    user_authorized_keys_present = (Test-Path -LiteralPath $authKeysUser)
    firewall_ssh_rules = @($fw)
}

# --- Toolchain / project-relevant ---
$pyExe = Find-Exe 'python'
$gitExe = Find-Exe 'git'
$tools = [ordered]@{
    python = if ($pyExe) { Try-Get { (& $pyExe --version 2>&1 | Out-String).Trim() } } else { $null }
    python_path = $pyExe
    git = if ($gitExe) { Try-Get { (& $gitExe --version 2>&1 | Out-String).Trim() } } else { $null }
    uv = [bool](Find-Exe 'uv')
    mc_worker_root_present = (Test-Path 'C:\mc-worker')
    mc_worker_venv_present = (Test-Path 'C:\mc-worker\venv\Scripts\python.exe')
    gurobi_home_env = $env:GUROBI_HOME
    gurobi_lic_env_set = [bool]$env:GRB_LICENSE_FILE
    gurobi_lic_file_in_home = (Test-Path (Join-Path $env:USERPROFILE 'gurobi.lic'))
}

# --- Power / sleep (a worker that sleeps drops off the tailnet) ---
$power = Try-Get { (powercfg /getactivescheme 2>$null | Out-String).Trim() }
$acSleep = Try-Get {
    $o = powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>$null | Out-String
    if ($o -match 'Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)') { [Convert]::ToInt32($Matches[1],16) } else { $null }
}
$battery = Try-Get { @(Get-CimInstance Win32_Battery).Count -gt 0 }
$wu = Try-Get { (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update' -ErrorAction Stop).AUOptions }

$ramGib = if ($cs) { [math]::Round($cs.TotalPhysicalMemory/1GB,1) } else { $null }
$report = [ordered]@{
    collected_at = (Get-Date).ToString('o')
    identity = [ordered]@{
        computer_name = $env:COMPUTERNAME
        user = $env:USERNAME
        user_domain = $env:USERDOMAIN
        user_sid = $identity.User.Value
        in_administrators_group = $inAdminGroup
        shell_elevated = $elevated
        key_install_path_would_be = if ($inAdminGroup) { $authKeysAdmin } else { $authKeysUser }
    }
    os = [ordered]@{
        caption = if ($os) { $os.Caption } else { $null }
        version = if ($os) { $os.Version } else { $null }
        build = if ($os) { $os.BuildNumber } else { $null }
        arch = $env:PROCESSOR_ARCHITECTURE
        last_boot = if ($os) { $os.LastBootUpTime.ToString('o') } else { $null }
        powershell = $PSVersionTable.PSVersion.ToString()
    }
    hardware = [ordered]@{
        manufacturer = if ($cs) { $cs.Manufacturer } else { $null }
        model = if ($cs) { $cs.Model } else { $null }
        cpu = if ($cpu) { $cpu.Name.Trim() } else { $null }
        physical_cores = if ($cpu) { $cpu.NumberOfCores } else { $null }
        logical_processors = if ($cpu) { $cpu.NumberOfLogicalProcessors } else { $null }
        ram_gib = $ramGib
        free_ram_gib = if ($os) { [math]::Round($os.FreePhysicalMemory/1MB,1) } else { $null }
        disks = @($disks)
        is_laptop_battery = $battery
    }
    tailscale = $ts
    ssh = $ssh
    toolchain = $tools
    power = [ordered]@{active_scheme=$power; ac_standby_idle_seconds=$acSleep; windows_update_au_options=$wu}
}

# Blocking / attention items (facts only; nothing is changed).
$todo = New-Object System.Collections.Generic.List[string]
if (-not $ts.installed) { $todo.Add('Tailscale not installed.') }
elseif (-not $ts.backend_state) { $todo.Add("Tailscale state unreadable (status --json failed); IP $($ts.ipv4) was obtained, so it is probably connected.") }
elseif ($ts.backend_state -ne 'Running') { $todo.Add("Tailscale backend is '$($ts.backend_state)' (not Running); log in / start it.") }
if (-not $ssh.sshd_service_present) { $todo.Add('sshd service missing: install OpenSSH Server (elevated).') }
else {
    if ($ssh.sshd_state -ne 'Running') { $todo.Add("sshd is $($ssh.sshd_state); start it (elevated).") }
    if ($ssh.sshd_start_mode -ne 'Auto') { $todo.Add("sshd StartMode is $($ssh.sshd_start_mode); set to Automatic (elevated).") }
}
if ($ssh.sshd_state -eq 'Running' -and $listen22 -eq $false) { $todo.Add('sshd running but nothing listens on :22.') }
if ($inAdminGroup -and -not $elevated) { $todo.Add('Account is an administrator but this shell is not elevated; setup must run as administrator.') }
if ($acSleep -ne $null -and $acSleep -gt 0) { $todo.Add("AC sleep timer is $acSleep s; a sleeping worker drops off the tailnet.") }
if ($ramGib -ne $null -and $ramGib -lt 32) { $todo.Add("Reported RAM $ramGib GiB < 32 GiB (a nominal 32 GB PC reads ~31.7); confirm Gurobi eligibility against lab policy.") }
if (-not $tools.mc_worker_venv_present) { $todo.Add('C:\mc-worker\venv absent: worker environment not installed yet.') }
$report['attention'] = @($todo)

$jsonText = $report | ConvertTo-Json -Depth 6
if ($OutFile) {
    [IO.File]::WriteAllText($OutFile, $jsonText, [Text.UTF8Encoding]::new($false))
}

Write-Host "=== Worker candidate: $env:COMPUTERNAME / $env:USERNAME ==="
Write-Host ("OS        : {0} (build {1})" -f $report.os.caption, $report.os.build)
Write-Host ("HW        : {0} {1} | {2} | {3}C/{4}T | RAM {5} GiB" -f $report.hardware.manufacturer, $report.hardware.model, $report.hardware.cpu, $report.hardware.physical_cores, $report.hardware.logical_processors, $ramGib)
Write-Host ("Tailscale : installed={0} state={1} ip={2}" -f $ts.installed, $ts.backend_state, $ts.ipv4)
Write-Host ("sshd      : present={0} state={1} start={2} listen22={3}" -f $ssh.sshd_service_present, $ssh.sshd_state, $ssh.sshd_start_mode, $listen22)
Write-Host ("Admin     : group={0} elevated={1} -> key file {2}" -f $inAdminGroup, $elevated, $report.identity.key_install_path_would_be)
Write-Host ("Toolchain : python={0} git={1} mc-worker venv={2}" -f $tools.python, $tools.git, $tools.mc_worker_venv_present)
Write-Host 'Attention :'
if ($todo.Count -eq 0) { Write-Host '  (none)' } else { $todo | ForEach-Object { Write-Host "  - $_" } }
Write-Host ''
Write-Host 'workers.json candidate (fill remaining fields by hand):'
Write-Host ("  name={0} ssh_user={1} tailscale_ip={2}" -f $env:COMPUTERNAME, $env:USERNAME, $ts.ipv4)
if ($OutFile) { Write-Host "Full JSON: $OutFile" } else { Write-Host '(pass -OutFile to save the full JSON)' }
