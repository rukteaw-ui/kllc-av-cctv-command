#!/usr/bin/env bash
set -e

echo "=============================================================================="
echo "   KLLC SMART ACCESS LITE // ระบบตรวจจับและบันทึกประวัติการเข้า-ออกด้วยใบหน้า"
echo "   Hikvision DeepinMind Pro (iDS-7716NXI-M4/X) ISAPI Integration"
echo "   สำนักการเรียนรู้ตลอดชีวิต (KLLC) สถาบันเทคโนโลยีพระจอมเกล้าเจ้าคุณทหารลาดกระบัง"
echo "=============================================================================="

# Check and copy .env
if [ ! -f ".env" ]; then
    echo "[INFO] Copying .env.example to .env..."
    cp .env.example .env
fi

echo "[INFO] Starting FastAPI server on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
