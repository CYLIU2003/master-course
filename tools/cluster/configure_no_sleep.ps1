# Disable idle sleep/hibernate on AC and on battery (DC), and make lid close do nothing.
# Keeps the critical-battery action (hibernate/shutdown) unchanged to avoid data loss at empty battery.
# Writes the previous values once to C:/mc-worker/power-before-no-sleep.json. Prints one JSON line.
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
function Read-Index($sub,$setting) {
 $value=(& powercfg /query SCHEME_CURRENT $sub $setting 2>$null | Out-String)
 if($LASTEXITCODE -ne 0){return $null}
 $ac=[regex]::Match($value,'AC[^\r\n]*0x([0-9a-fA-F]{8})')
 $dc=[regex]::Match($value,'DC[^\r\n]*0x([0-9a-fA-F]{8})')
 if(-not $ac.Success -or -not $dc.Success){
  if($setting -eq 'LIDACTION'){return $null}  # desktops without a lid expose no index
  throw "Power query format not recognized: $setting"
 }
 return @{ac=[Convert]::ToInt64($ac.Groups[1].Value,16);dc=[Convert]::ToInt64($dc.Groups[1].Value,16)}
}
function Read-All { @{standby=(Read-Index SUB_SLEEP STANDBYIDLE);hibernate=(Read-Index SUB_SLEEP HIBERNATEIDLE);lid=(Read-Index SUB_BUTTONS LIDACTION)} }
$scheme=[regex]::Match((& powercfg /getactivescheme | Out-String),'[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}').Value
if(-not $scheme){throw 'Active power scheme unavailable'}
$before=Read-All; $before.hostname=$env:COMPUTERNAME; $before.scheme=$scheme
$backup='C:/mc-worker/power-before-no-sleep.json'
[IO.Directory]::CreateDirectory('C:/mc-worker') | Out-Null
if(-not (Test-Path -LiteralPath $backup)){[IO.File]::WriteAllText($backup,($before|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))}
foreach($arg in 'standby-timeout-ac','standby-timeout-dc','hibernate-timeout-ac','hibernate-timeout-dc'){
 & powercfg /change $arg 0; if($LASTEXITCODE -ne 0){throw "powercfg $arg failed"}
}
if($before.lid){
 & powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0; if($LASTEXITCODE -ne 0){throw 'lid AC failed'}
 & powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0; if($LASTEXITCODE -ne 0){throw 'lid DC failed'}
 & powercfg /setactive SCHEME_CURRENT; if($LASTEXITCODE -ne 0){throw 'setactive failed'}
}
$after=Read-All
$ok=($after.standby.ac -eq 0 -and $after.standby.dc -eq 0 -and $after.hibernate.ac -eq 0 -and $after.hibernate.dc -eq 0 -and (-not $after.lid -or ($after.lid.ac -eq 0 -and $after.lid.dc -eq 0)))
$battery=[bool](Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
@{hostname=$env:COMPUTERNAME;verified=$ok;has_battery=$battery;before=$before;after=$after;backup=$backup}|ConvertTo-Json -Depth 6 -Compress
if(-not $ok){exit 3}
