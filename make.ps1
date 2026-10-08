param([string]$Task = "test")
$Backend = Join-Path $PSScriptRoot "backend"
switch ($Task) {
  "install" { Set-Location $Backend; python -m pip install -e . }
  "run" { python (Join-Path $PSScriptRoot "app.py"); exit $LASTEXITCODE }
  "test" { Set-Location $Backend; python -m pytest }
  "lint" { Set-Location $Backend; python -m compileall app tests }
  default { Write-Error "Unknown task: $Task"; exit 1 }
}
