param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"

# Build in an isolated environment so a different system Qt/PySide6 install
# cannot be mixed into the frozen application. User data remains in
# %LOCALAPPDATA%\CutData AI.
$buildVenv = Join-Path (Get-Location) ".venv-build"
$buildPython = Join-Path $buildVenv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $buildPython)) {
    py -3 -m venv $buildVenv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the isolated build environment." }
}

if (-not $SkipDependencyInstall) {
    & $buildPython -m pip install --disable-pip-version-check --upgrade -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install the build dependencies." }
}

& $buildPython -m PyInstaller --noconfirm --clean "CutData AI.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Write-Host "Built dist\CutData AI\CutData AI.exe"
