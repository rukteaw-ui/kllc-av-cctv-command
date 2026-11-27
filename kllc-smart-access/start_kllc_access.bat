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

REM 2. Detect real Python installation directly from standard folders first (ignores stale PATH)
set "PY_EXE="

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%~D\python.exe" set "PY_EXE=%%~D\python.exe"
)
if not defined PY_EXE (
    for /d %%D in ("C:\Program Files\Python3*") do (
        if exist "%%~D\python.exe" set "PY_EXE=%%~D\python.exe"
    )
)
if not defined PY_EXE (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        echo "%%~P" | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if not defined PY_EXE set "PY_EXE=%%~P"
        )
    )
)

if not defined PY_EXE (
    echo [ERROR] Python is not installed on this computer.
    echo.
    echo Please install Python 64-bit (.exe) from:
    echo   https://www.python.org/downloads/windows/
    echo.
    pause
    exit /b 1
)

echo [OK] Found Python: "%PY_EXE%"
"%PY_EXE%" --version
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
    "%PY_EXE%" -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM 5. Install / verify required packages
echo [INFO] Checking and installing required packages (please wait)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
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
