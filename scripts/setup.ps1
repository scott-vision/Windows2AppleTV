$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repo

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/ and run this script again.'
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python 3.12 is required. Install it from https://www.python.org/downloads/ and run this script again.'
}

uv sync
Write-Host "pycast is ready in $repo\.venv"
Write-Host 'Next: .\scripts\mirror.ps1 -ReceiverName "Scott’s TV"'
