param([switch]$AdoptPrototype)
$ErrorActionPreference = 'Stop'
$mandateRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $mandateRoot
$mandatePython = Join-Path $mandateRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $mandatePython)) {
    throw 'Create .venv and install the locked API dependencies first. See README.md.'
}
if ($AdoptPrototype) {
    & $mandatePython -m mandate.migrate --adopt-prototype
} else {
    & $mandatePython -m mandate.migrate
}
exit $LASTEXITCODE
