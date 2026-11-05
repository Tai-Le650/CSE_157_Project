param(
    [int]$Port = 8000,
    [switch]$Build,
    [switch]$Open
)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "Python environment not found at $python. See docs\setup-windows.md."
}

$frontend = Join-Path $root 'frontend'
if ($Build -or -not (Test-Path (Join-Path $frontend 'dist\index.html'))) {
    Push-Location $frontend
    try {
        if (-not (Test-Path 'node_modules')) {
            npm install
            if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    }
    finally {
        Pop-Location
    }
}

$arguments = @((Join-Path $root 'backend\run.py'), '--port', $Port)
if ($Open) { $arguments += '--open' }
Push-Location $root
try {
    & $python @arguments
}
finally {
    Pop-Location
}
