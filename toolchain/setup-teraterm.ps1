[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $PSScriptRoot "teraterm.lock"
$toolchainRoot = Join-Path $repoRoot ".toolchain"

function Read-TeraTermLock {
    param([string]$Path)

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^([a-z0-9_]+)\s*=\s*"([^"]*)"\s*$') {
            $values[$Matches[1]] = $Matches[2]
        }
        elseif ($line -match '^([a-z0-9_]+)\s*=\s*([0-9]+)\s*$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }

    foreach ($required in "version", "asset", "url", "sha256", "size") {
        if (-not $values.ContainsKey($required)) {
            throw "Missing '$required' in $Path"
        }
    }
    return $values
}

function Assert-Archive {
    param(
        [string]$Path,
        [long]$ExpectedSize,
        [string]$ExpectedSha256
    )

    $actualSize = (Get-Item -LiteralPath $Path).Length
    if ($actualSize -ne $ExpectedSize) {
        throw "Size mismatch for ${Path}: expected $ExpectedSize, got $actualSize"
    }

    $actualSha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $ExpectedSha256) {
        throw "SHA-256 mismatch for ${Path}: expected $ExpectedSha256, got $actualSha256"
    }
}

$lock = Read-TeraTermLock -Path $lockPath
$installRoot = Join-Path $toolchainRoot "teraterm-$($lock.version)-x64"
$executablePath = Join-Path $installRoot "ttermpro.exe"

if (Test-Path -LiteralPath $executablePath) {
    Write-Output $executablePath
    exit 0
}
if (Test-Path -LiteralPath $installRoot) {
    throw "Incomplete Tera Term installation already exists at $installRoot"
}

$downloadRoot = Join-Path $toolchainRoot "downloads"
New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null
$archivePath = Join-Path $downloadRoot $lock.asset

if (-not (Test-Path -LiteralPath $archivePath)) {
    $partialPath = "$archivePath.partial"
    if (Test-Path -LiteralPath $partialPath) {
        throw "Incomplete download already exists at $partialPath"
    }
    Invoke-WebRequest -Uri $lock.url -OutFile $partialPath
    Assert-Archive -Path $partialPath -ExpectedSize ([long]$lock.size) -ExpectedSha256 $lock.sha256
    Move-Item -LiteralPath $partialPath -Destination $archivePath
}

Assert-Archive -Path $archivePath -ExpectedSize ([long]$lock.size) -ExpectedSha256 $lock.sha256

$extractRoot = Join-Path $toolchainRoot ("extract-" + [guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $extractRoot | Out-Null
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot

    $executables = @(
        Get-ChildItem -LiteralPath $extractRoot -Filter "ttermpro.exe" -File -Recurse
    )
    if ($executables.Count -ne 1) {
        throw "Archive contains $($executables.Count) ttermpro.exe files; expected exactly one"
    }

    $extractedDistribution = Split-Path -Parent $executables[0].FullName
    $resolvedExtractRoot = [IO.Path]::GetFullPath($extractRoot).TrimEnd('\')
    $resolvedDistribution = [IO.Path]::GetFullPath($extractedDistribution)
    if (
        $resolvedDistribution -ne $resolvedExtractRoot -and
        -not $resolvedDistribution.StartsWith(
            $resolvedExtractRoot + '\',
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Refusing to install archive content outside $extractRoot"
    }

    Move-Item -LiteralPath $resolvedDistribution -Destination $installRoot
    if (-not (Test-Path -LiteralPath $executablePath)) {
        throw "Installed Tera Term is missing ttermpro.exe at $executablePath"
    }
}
finally {
    if (Test-Path -LiteralPath $extractRoot) {
        $resolvedToolchainRoot = [IO.Path]::GetFullPath($toolchainRoot).TrimEnd('\') + '\'
        $resolvedExtractRoot = [IO.Path]::GetFullPath($extractRoot)
        if (-not $resolvedExtractRoot.StartsWith(
            $resolvedToolchainRoot,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to remove extraction path outside $toolchainRoot"
        }
        Remove-Item -LiteralPath $resolvedExtractRoot -Recurse -Force
    }
}

Write-Output $executablePath
