@echo off
setlocal enabledelayedexpansion


cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    set "PYTHONW_EXE=.venv\Scripts\pythonw.exe"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python 3.11+ or create the .venv.
        pause
        exit /b 1
    )
    set "PYTHON_EXE=python"
    set "PYTHONW_EXE=pythonw"
)

if not "%~1"=="" (
    "%PYTHON_EXE%" run.py %*
    exit /b %errorlevel%
)

echo Starting Context Vault Desktop...
start "" "%PYTHONW_EXE%" run.py desktop

if errorlevel 1 (
    echo [WARNING] Background launch failed, launching with console...
    "%PYTHON_EXE%" run.py desktop
    pause
)
