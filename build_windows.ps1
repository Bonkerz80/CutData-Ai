param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$buildVenv = Join-Path $projectRoot ".venv-build"
$buildPython = Join-Path $buildVenv "Scripts\python.exe"
$existingBuildPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$newEnvironment = -not (Test-Path -LiteralPath $buildPython)
if ($newEnvironment -and (Test-Path -LiteralPath $existingBuildPython)) {
    $buildPython = $existingBuildPython
    $newEnvironment = $false
}
if (-not (Test-Path -LiteralPath $buildPython)) {
    py -3 -m venv $buildVenv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the isolated build environment." }
}

if ($newEnvironment -or -not $SkipDependencyInstall) {
    & $buildPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw "Could not install the build dependencies." }
}

# Fresh staging directories avoid OneDrive read-only placeholders and leave the
# last bundle available if a build fails. Never merge DLLs into an old bundle.
$runRoot = Join-Path $projectRoot ('build\packaging\' + [guid]::NewGuid().ToString('N'))
$workPath = Join-Path $runRoot 'work'
$stagingDist = Join-Path $runRoot 'dist'
New-Item -ItemType Directory -Path $workPath,$stagingDist -Force | Out-Null
Push-Location $projectRoot
try {
    & $buildPython -m PyInstaller --noconfirm --workpath $workPath --distpath $stagingDist 'CutData AI.spec'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

    $newBundle = Join-Path $stagingDist 'CutData AI'
    & $buildPython (Join-Path $projectRoot 'scripts\verify_windows_bundle.py') (Join-Path $newBundle 'CutData AI.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Native dependency validation failed.' }

    $finalDist = Join-Path $projectRoot 'dist'
    New-Item -ItemType Directory -Path $finalDist -Force | Out-Null
    $finalBundle = Join-Path $finalDist 'CutData AI'
    $previousBundle = Join-Path $runRoot 'previous-bundle'
    foreach ($path in @($newBundle, $finalBundle, $previousBundle)) {
        $absolute = [IO.Path]::GetFullPath($path)
        if (-not $absolute.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unexpected bundle path: $absolute"
        }
    }
    if (Test-Path -LiteralPath $finalBundle) {
        Move-Item -LiteralPath $finalBundle -Destination $previousBundle
    }
    try {
        Move-Item -LiteralPath $newBundle -Destination $finalBundle
    } catch {
        if (Test-Path -LiteralPath $previousBundle) {
            Move-Item -LiteralPath $previousBundle -Destination $finalBundle
        }
        throw
    }
} finally {
    Pop-Location
}

Write-Host "Built dist\CutData AI\CutData AI.exe"
