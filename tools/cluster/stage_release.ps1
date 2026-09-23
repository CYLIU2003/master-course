param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$Sha256
)
$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
$destinationPath = [IO.Path]::GetFullPath($Destination)
$archivePath = [IO.Path]::GetFullPath($Archive)
foreach ($target in @($destinationPath, $archivePath)) {
    if (-not $target.StartsWith($rootPath, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe staging path' }
}
if (Test-Path -LiteralPath $destinationPath) { throw 'Immutable release already exists' }
$stream = [IO.File]::OpenRead($archivePath)
$hasher = [Security.Cryptography.SHA256]::Create()
try { $actualHash = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
finally { $stream.Dispose(); $hasher.Dispose() }
if ($actualHash -ne $Sha256) { throw 'Release hash mismatch' }
$temporary = $destinationPath + '.partial-' + [Guid]::NewGuid().ToString('N')
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    $expandedBytes = 0L
    $names = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $zip.Entries) {
        $name = $entry.FullName
        $parts = $name.Split('/')
        if ($name.Contains('\') -or $name.Contains(':') -or $name.StartsWith('/') -or
            ($parts | Where-Object { $_ -eq '..' -or $_ -eq '.' -or $_.EndsWith('.') -or $_.EndsWith(' ') })) { throw 'Unsafe ZIP entry' }
        $entryPath = [IO.Path]::GetFullPath((Join-Path $temporary $name))
        if (-not $entryPath.StartsWith($temporary + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'ZIP entry escaped release' }
        if (-not $names.Add($entryPath)) { throw 'Colliding ZIP paths' }
        $unixType = ($entry.ExternalAttributes -shr 16) -band 61440
        if ($unixType -eq 40960) { throw 'Linked ZIP entry' }
        $expandedBytes += $entry.Length
        if ($expandedBytes -gt 20GB) { throw 'Expanded release exceeds 20 GiB limit' }
    }
} finally { $zip.Dispose() }
# All move targets have been checked against the named root. Keep failed
# staging directories for diagnosis; never recursively remove existing code.
[IO.Compression.ZipFile]::ExtractToDirectory($archivePath, $temporary)
Move-Item -LiteralPath $temporary -Destination $destinationPath
Write-Output 'STAGED'
