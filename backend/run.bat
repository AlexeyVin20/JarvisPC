@echo off
REM ============================================================
REM  JarvisPC backend
REM    run.bat          API + WS server on http://localhost:8787
REM    run.bat cli      headless chat in this terminal
REM ============================================================
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo [ERROR] .venv not found - run setup.bat first.
    pause
    exit /b 1
)

if /i "%~1"=="cli" (
    .venv\Scripts\python.exe -m app.cli %2 %3
) else (
    echo Jarvis backend: http://localhost:8787  (docs: /docs)
    .venv\Scripts\python.exe -m app.main
)
pause
