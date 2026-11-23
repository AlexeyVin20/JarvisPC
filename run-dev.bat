@echo off
REM ============================================================
REM  JarvisPC: one-command start (Windows)
REM    1) Docker Desktop (auto-start if needed)
REM    2) docker compose up -d --wait  (postgres + 4get)
REM    3) backend  http://localhost:8787
REM    4) web      http://localhost:3000
REM ============================================================
cd /d "%~dp0"

echo [1/4] Docker engine...
docker info >nul 2>&1
if errorlevel 1 (
    echo    Docker Desktop is not running - starting it, please wait...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    :wait_docker
    ping -n 4 127.0.0.1 >nul
    docker info >nul 2>&1
    if errorlevel 1 goto wait_docker
)
echo    Docker engine is up.

echo [2/4] docker compose up -d --wait (postgres + 4get)...
docker compose up -d --wait
if errorlevel 1 (
    echo [ERROR] docker compose failed - see output above.
    pause
    exit /b 1
)

echo [3/4] Backend  http://localhost:8787  (docs: /docs)
start "Jarvis backend" cmd /k "backend\run.bat"

echo [4/4] Web      http://localhost:3000
start "Jarvis web" cmd /k "cd web && npm run dev"

echo.
echo Done. Backend: http://localhost:8787   Web: http://localhost:3000
