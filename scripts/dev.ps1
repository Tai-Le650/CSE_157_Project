$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "Python environment not found at $python. See docs\setup-windows.md."
}

$frontend = Join-Path $root 'frontend'
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Push-Location $frontend
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
    }
    finally {
        Pop-Location
    }
}

$runPy = Join-Path $root 'backend\run.py'
$backend = Start-Process -FilePath $python -ArgumentList @("`"$runPy`"", '--port', '8000', '--no-frontend') -WorkingDirectory $root -NoNewWindow -PassThru
try {
    Push-Location $frontend
    npm run dev
}
finally {
    Pop-Location
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id
    }
}
