@echo off
setlocal
pushd "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
    echo uv was not found. Install uv from https://docs.astral.sh/uv/getting-started/installation/
    goto failed
)
if not exist ".venv-decal-lab\Scripts\python.exe" (
    uv --cache-dir build\uv-cache venv --python 3.12 .venv-decal-lab
    if errorlevel 1 goto failed
)
uv --cache-dir build\uv-cache pip install --python .venv-decal-lab\Scripts\python.exe -r tools\decal_lab\requirements-gui.txt
if errorlevel 1 goto failed
".venv-decal-lab\Scripts\python.exe" tools\decal_gui.py %*
if errorlevel 1 goto failed
popd
exit /b 0
:failed
pause
popd
exit /b 1
