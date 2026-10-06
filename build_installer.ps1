$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$isccCandidates = @(
    (Join-Path $projectRoot '.tools\InnoSetup\ISCC.exe'),
    'C:\Program Files\Inno Setup 7\ISCC.exe',
    'C:\Program Files (x86)\Inno Setup 7\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe',
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iscc) {
    throw 'Inno Setup ISCC.exe was not found. Install Inno Setup or place it in .tools\InnoSetup.'
}

$appExe = Join-Path $projectRoot 'dist\CutData AI\CutData AI.exe'
$pythonCandidates = @(
    (Join-Path $projectRoot '.venv-build\Scripts\python.exe'),
    (Join-Path $projectRoot '.venv\Scripts\python.exe')
)
$buildPython = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$buildArguments = @{}
if ($buildPython) {
    $buildArguments = @{ SkipDependencyInstall = $true }
}
# Always rebuild from the current source tree; a pre-existing dist folder may
# be from an older release and must never silently enter the new installer.
& (Join-Path $projectRoot 'build_windows.ps1') @buildArguments
if ($LASTEXITCODE -ne 0) {
    throw 'The application build failed.'
}
if (-not (Test-Path -LiteralPath $appExe)) {
    throw 'The current application build did not produce the expected executable.'
}

$buildPython = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $buildPython) {
    throw 'Python build environment was not found after the application build.'
}

$outputDir = Join-Path $projectRoot 'installer'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$installerName = 'CutData-AI-Setup-0.2.7.exe'
$installerPath = Join-Path $outputDir $installerName
if (Test-Path -LiteralPath $installerPath) {
    throw "Refusing to overwrite an existing installer: $installerPath"
}
& $buildPython (Join-Path $projectRoot 'scripts\verify_windows_bundle.py') $appExe
if ($LASTEXITCODE -ne 0) { throw 'Native dependency validation failed; refusing to package this bundle.' }

& $iscc "/Qp" (Join-Path $projectRoot 'installer.iss')
if ($LASTEXITCODE -ne 0) {
    throw 'The Inno Setup installer build failed.'
}

Write-Host ("Built installer\{0}" -f $installerName)
