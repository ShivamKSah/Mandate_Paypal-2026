$ErrorActionPreference = 'Stop'
$mandateRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $mandateRoot
$mandatePython = Join-Path $mandateRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $mandatePython)) {
    throw 'Create .venv and install apps/api dependencies first. See README.md.'
}
& $mandatePython -m uvicorn mandate.main:app --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
