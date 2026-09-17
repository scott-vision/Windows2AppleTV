$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $PSScriptRoot 'source'

if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    throw 'Go 1.25 or newer is required to rebuild the native helper. Normal users do not need Go because the checked-in EXE is ready to run.'
}

Set-Location -LiteralPath $source
go build -trimpath -o (Join-Path $repo 'native\pycast-airplay.exe') .\cmd\airplayprobe
Write-Host "Built $repo\native\pycast-airplay.exe"
