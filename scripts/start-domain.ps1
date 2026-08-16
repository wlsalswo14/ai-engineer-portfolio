param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("chess", "cache", "coding", "reasoning_tools")]
    [string]$Domain,
    [ValidateRange(1, 1000)]
    [int]$Rounds = 1
)
$ErrorActionPreference = "Stop"
$PrimusRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $PrimusRoot
primus doctor
primus loop start $Domain --rounds $Rounds
