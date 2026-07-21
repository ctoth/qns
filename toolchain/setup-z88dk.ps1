[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $PSScriptRoot "z88dk.lock"
$toolchainRoot = Join-Path $repoRoot ".toolchain"

function Read-Z88dkLock {
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

$lock = Read-Z88dkLock -Path $lockPath
$installRoot = Join-Path $toolchainRoot "z88dk-$($lock.version)"
$zccPath = Join-Path $installRoot "bin\zcc.exe"
$assemblerPath = Join-Path $installRoot "bin\z88dk-z80asm.exe"

if ((Test-Path -LiteralPath $zccPath) -and (Test-Path -LiteralPath $assemblerPath)) {
    Write-Output $installRoot
    exit 0
}
if (Test-Path -LiteralPath $installRoot) {
    throw "Incomplete z88dk installation already exists at $installRoot"
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

    $extractedDistribution = Join-Path $extractRoot "z88dk"
    $extractedBin = Join-Path $extractedDistribution "bin"
    if (-not (Test-Path -LiteralPath (Join-Path $extractedBin "zcc.exe"))) {
        throw "Archive does not contain z88dk\bin\zcc.exe"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $extractedBin "z88dk-z80asm.exe"))) {
        throw "Archive does not contain bin\z88dk-z80asm.exe beside zcc.exe"
    }

    Move-Item -LiteralPath $extractedDistribution -Destination $installRoot

    if (-not ((Test-Path -LiteralPath $zccPath) -and (Test-Path -LiteralPath $assemblerPath))) {
        throw "Installed z88dk is missing required executables at $installRoot"
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

Write-Output $installRoot
