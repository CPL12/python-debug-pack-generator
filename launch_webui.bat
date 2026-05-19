@echo off
setlocal

cd /d "%~dp0"

if not defined PORT set "PORT=8000"
set "URL=http://127.0.0.1:%PORT%/"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create .venv. Make sure Python is installed and available on PATH.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate .venv.
    pause
    exit /b 1
)

echo Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo Starting Python Debug Pack Generator at %URL%
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process '%URL%'"

python -m uvicorn app.main:app --reload --host 127.0.0.1 --port %PORT%

echo.
echo WebUI server stopped.
pause
