@echo off
REM ============================================================
REM  JarvisPC backend - first-time setup
REM    1. uv venv + deps
REM    2. docker compose up -d  (postgres + 4get)
REM ============================================================
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv not found. Install: winget install astral-sh.uv
    pause
    exit /b 1
)

if not exist .venv\Scripts\python.exe (
    echo Creating .venv ...
    uv venv
)

echo Installing dependencies ...
uv sync

cd ..
if not exist .env (
    copy .env.example .env >nul
    echo.
    echo [ACTION REQUIRED] Edit .env and set GEMINI_API_KEY
)

echo.
echo Starting postgres + 4get via docker compose ...
docker compose up -d
if errorlevel 1 (
    echo [WARN] docker compose failed - start Docker Desktop and run: docker compose up -d
)

echo.
echo Done. Run backend:  backend\run.bat
echo Frontend:         cd web ^&^& npm install ^&^& npm run dev
pause
