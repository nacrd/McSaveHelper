@echo off
setlocal enabledelayedexpansion

:: Change to script's directory
cd /d "%~dp0"

:: 1. Check Python installation
echo [1/4] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.9+ and ensure it's available in PATH.
    pause
    exit /b 1
)

:: 2. Smart virtual environment handling
set VENV_DIR=.venv
set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe
set VENV_PIP=%VENV_DIR%\Scripts\pip.exe
set NEED_CREATE=0

if not exist "%VENV_PYTHON%" (
    set NEED_CREATE=1
) else (
    "%VENV_PYTHON%" -c "import sys; sys.exit(0)" >nul 2>&1
    if errorlevel 1 (
        echo [WARNING] Virtual environment is broken. Recreating...
        rmdir /s /q "%VENV_DIR%"
        set NEED_CREATE=1
    ) else (
        echo [INFO] Existing virtual environment is healthy.
    )
)

if "!NEED_CREATE!"=="1" (
    echo [2/4] Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Virtual environment is ready.
)

:: 3. Activate and install dependencies
call "%VENV_DIR%\Scripts\activate.bat"
echo [3/4] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: 4. Launch main application
echo [4/4] Starting application...
python main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with error code %errorlevel%.
    pause
)