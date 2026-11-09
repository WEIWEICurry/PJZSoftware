$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    Push-Location frontend
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
    uv run pyinstaller --noconfirm --clean --onedir --name PJZSoftware --paths backend --add-data 'frontend/out:frontend' --collect-data rapidocr --copy-metadata rapidocr --hidden-import rapidocr.inference_engine.onnxruntime --collect-submodules uvicorn --collect-submodules alembic.ddl --exclude-module alembic.testing --exclude-module pytest --add-data 'backend/pjz/migrations:pjz/migrations' launcher/entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Package build failed' }
    uv run pyinstaller --noconfirm --clean --onefile --windowed --name PJZStart --paths backend --distpath dist/PJZSoftware --workpath build/bootstrap launcher/bootstrap.py
    if ($LASTEXITCODE -ne 0) { throw 'Stable launcher build failed' }
    uv run python scripts/make_release.py dist/PJZSoftware
    if ($LASTEXITCODE -ne 0) { throw 'Release manifest verification failed' }
    & '.\dist\PJZSoftware\PJZSoftware.exe' --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Packaged acceptance check failed' }
} finally { Pop-Location }
