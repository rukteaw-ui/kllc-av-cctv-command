@echo off
chcp 65001 >nul
title KLLC Smart Access Lite - สำนักการเรียนรู้ตลอดชีวิต สจล.
cls

echo ==============================================================================
echo    KLLC SMART ACCESS LITE // ระบบตรวจจับและบันทึกประวัติการเข้า-ออกด้วยใบหน้า
echo    Hikvision DeepinMind Pro (iDS-7716NXI-M4/X) ISAPI Integration
echo    สำนักการเรียนรู้ตลอดชีวิต (KLLC) สถาบันเทคโนโลยีพระจอมเกล้าเจ้าคุณทหารลาดกระบัง
echo ==============================================================================
echo.

:: 1. Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] ไม่พบ Python ในระบบ กรุณาติดตั้ง Python 3.11 หรือสูงกว่าจาก python.org
    echo [TIP] อย่าลืมติ๊กเลือก "Add Python to PATH" ระหว่างการติดตั้ง
    pause
    exit /b 1
)

:: 2. Check and copy .env
if not exist ".env" (
    echo [INFO] กำลังสร้างไฟล์ .env จาก .env.example...
    copy .env.example .env >nul
    echo [TIP] บอสสามารถแก้ไข IP และรหัสผ่าน NVR ได้ในไฟล์ .env
    echo.
)

:: 3. Setup Virtual Environment
if not exist ".venv" (
    echo [INFO] กำลังสร้าง Python Virtual Environment (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] สร้าง venv ไม่สำเร็จ
        pause
        exit /b 1
    )
)

:: 4. Activate venv & Install dependencies
echo [INFO] กำลังเรียกใช้งาน Python Virtual Environment...
call .venv\Scripts\activate.bat

echo [INFO] ตรวจสอบและติดตั้ง Packages...
pip install -r requirements.txt --quiet

:: 5. Launch Browser & Server
echo.
echo ==============================================================================
echo  [SUCCESS] กำลังเปิดระบบ KLLC Smart Access Lite ที่ http://localhost:8000
echo  กด Ctrl+C ในหน้าต่างนี้เพื่อหยุดการทำงาน
echo ==============================================================================
echo.

start "" http://localhost:8000
uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
