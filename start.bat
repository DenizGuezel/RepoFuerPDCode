@echo off
cd /d "%~dp0" || exit /b 1

where py >nul 2>&1
if errorlevel 1 (
    python run.py --with-ollama --open %*
) else (
    py -3 run.py --with-ollama --open %*
)
if errorlevel 1 pause
