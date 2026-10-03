param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '..\script\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Training venv not found. See terry/docs/eeg-waveform-model-integration-progress-2026-09-29.md for environment setup.'
}
$previousLocation = Get-Location
$previousPythonPath = $env:PYTHONPATH
try {
    Set-Location $PSScriptRoot
    $env:PYTHONPATH = "$PSScriptRoot\src;$PSScriptRoot;$previousPythonPath"
    & $python -c "from channel_mapping import CAP_ORDER; from waveform_classifier import WaveformClassifier; [WaveformClassifier(CAP_ORDER,250,n) for n in (2,4,6,8,16)]; print('cap2/cap4/cap6/cap8/cap16 checkpoints validated. Research-only LIVE inference, CPU runtime.')"
    if ($LASTEXITCODE -ne 0) { throw 'Model preflight failed; server was not started.' }
    & $python -m uvicorn app:app --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Backend exited with an error. Check dependencies and port availability.' }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    Set-Location $previousLocation
}
