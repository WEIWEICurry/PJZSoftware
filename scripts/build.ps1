$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    Push-Location frontend
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
    uv run pyinstaller --noconfirm --clean --onedir --name PJZSoftware --paths backend --add-data 'frontend/out:frontend' --collect-submodules uvicorn launcher/entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Package build failed' }
    & '.\dist\PJZSoftware\PJZSoftware.exe' --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Packaged acceptance check failed' }
} finally { Pop-Location }
