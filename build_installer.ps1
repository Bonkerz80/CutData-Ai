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
if (-not (Test-Path -LiteralPath $appExe)) {
    $buildArguments = @{}
    if (Test-Path -LiteralPath (Join-Path $projectRoot '.venv-build\Scripts\python.exe')) {
        $buildArguments = @{ SkipDependencyInstall = $true }
    }
    & (Join-Path $projectRoot 'build_windows.ps1') @buildArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'The application build failed.'
    }
}

$outputDir = Join-Path $projectRoot 'installer'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

& (Join-Path $projectRoot '.venv-build\Scripts\python.exe') (Join-Path $projectRoot 'scripts\verify_windows_bundle.py') $appExe
if ($LASTEXITCODE -ne 0) { throw 'Native dependency validation failed; refusing to package this bundle.' }

& $iscc "/Qp" (Join-Path $projectRoot 'installer.iss')
if ($LASTEXITCODE -ne 0) {
    throw 'The Inno Setup installer build failed.'
}

$installerName = 'CutData-AI-Setup-0.1.8.exe'
Write-Host ("Built installer\{0}" -f $installerName)
