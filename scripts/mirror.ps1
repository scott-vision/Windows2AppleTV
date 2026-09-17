param(
    [Parameter(Mandatory = $true)]
    [string]$ReceiverName,
    [int]$Display = 0,
    [int]$Fps = 30,
    [double]$Seconds
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repo
$pycast = Join-Path $repo '.venv\Scripts\pycast.exe'

if (-not (Test-Path -LiteralPath $pycast)) {
    throw "Virtual environment not found at $pycast. Run .\scripts\setup.ps1 first."
}

$args = @('mirror', $ReceiverName, '--display', $Display, '--fps', $Fps)
if ($PSBoundParameters.ContainsKey('Seconds')) {
    $args += @('--seconds', $Seconds)
}
& $pycast @args
exit $LASTEXITCODE
