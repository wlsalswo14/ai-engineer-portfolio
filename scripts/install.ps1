$ErrorActionPreference = "Stop"
$PrimusRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $PrimusRoot
python -m pip install -e .
primus init
primus doctor
primus smoke
python -m pytest
