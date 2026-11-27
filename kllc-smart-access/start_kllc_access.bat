@echo off
title KLLC Smart Access Lite
cd /d "%~dp0"

echo ==============================================================================
echo    KLLC SMART ACCESS LITE
echo    Hikvision DeepinMind Pro (iDS-7716NXI-M4/X) ISAPI Face Access System
echo ==============================================================================
echo.

REM 1. Check if extracted properly (not running directly inside ZIP)
if not exist "requirements.txt" (
    echo [ERROR] Project files not found in this folder!
    echo.
    echo Please EXTRACT the ZIP file first:
    echo   1. Right-click the downloaded .zip file
    echo   2. Select "Extract All..."
    echo   3. Open the extracted folder and double-click start_kllc_access.bat
    echo.
    pause
    exit /b 1
)

REM 2. Detect real Python installation (avoid Windows Store stub)
set "PY_CMD="
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py -3"
) else (
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=python"
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] Python is not installed on this computer.
    echo.
    echo Opening Python download page in your browser...
    echo   1. Click "Download Windows installer (64-bit)" (.exe)
    echo   2. IMPORTANT: Check "Add python.exe to PATH" at the bottom
    echo   3. Click "Install Now", then double-click start_kllc_access.bat again
    echo.
    start "" "https://www.python.org/downloads/windows/"
    pause
    exit /b 1
)

echo [OK] Found Python:
%PY_CMD% --version
echo.

REM 3. Create .env from .env.example if missing
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] Creating initial .env configuration file...
        copy ".env.example" ".env" >nul
    )
)

REM 4. Create Virtual Environment (.venv) if missing
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Setting up Python environment for first-time use...
    %PY_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM 5. Install / verify required packages
echo [INFO] Checking and installing required packages (please wait)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Package installation failed. Please check your internet connection.
    pause
    exit /b 1
)

REM 6. Free port 8000 if an older instance is still running
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [INFO] Stopping older KLLC Access server (PID %%a)...
    taskkill /F /PID %%a >nul 2>&1
)

REM 7. Launch Browser (after 3s delay so server is ready) & Start Server
echo.
echo ==============================================================================
echo  [READY] Starting KLLC Smart Access Lite at http://localhost:8000
echo  Keep this black window open while using the system.
echo  Press Ctrl+C to stop.
echo ==============================================================================
echo.

start /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo [INFO] Server stopped.
pause
