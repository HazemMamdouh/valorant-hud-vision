# Build the overlay if needed and serve the sample round as if it were the screen.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path "overlay/dist/index.html")) {
  Push-Location overlay; npm install; npm run build; Pop-Location
}
Write-Host "Overlay: http://127.0.0.1:8000/   (press D for raw JSON)"
valovision serve --source samples/sample_2022q1_30s.mp4 @args
