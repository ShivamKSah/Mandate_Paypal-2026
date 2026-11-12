$ErrorActionPreference = 'Stop'
$mandateRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath (Join-Path $mandateRoot 'apps\web')
& npm.cmd run dev -- --host 127.0.0.1
exit $LASTEXITCODE
