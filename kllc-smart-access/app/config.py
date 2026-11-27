import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Resolve directories for both normal Python and PyInstaller single-file .exe
if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parent.parent
    BASE_DIR = BUNDLE_DIR

# Load .env file from alongside the executable / project folder
load_dotenv(dotenv_path=BASE_DIR / ".env")

# NVR Connection Settings (Never auto-login with placeholder password!)
NVR_IP = os.getenv("NVR_IP", "10.37.2.97")
NVR_PORT = int(os.getenv("NVR_PORT", "80"))
NVR_USER = os.getenv("NVR_USER", "")
NVR_PASS = os.getenv("NVR_PASS", "")
NVR_BASE_URL = f"http://{NVR_IP}:{NVR_PORT}"

# Application Settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")

# Database Path
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "kllc_access.db"))

# Simulation mode (generates mock events when physical NVR is disconnected)
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "False").lower() in ("true", "1", "yes")

# Target Face Libraries on NVR
TARGET_LIBRARIES = ["KLLC STAFF", "KLLC Access"]

# Default Camera Channel Map (D1, D2, D3, D9)
CAMERA_CHANNELS = {
    1: {
        "channel_id": 1,
        "code": "D1",
        "name": "Co-working",
        "location_label": "ชั้น 1 โซน Co-working Space",
        "is_active": True
    },
    2: {
        "channel_id": 2,
        "code": "D2",
        "name": "Main Entrance",
        "location_label": "ทางเข้าหลัก อาคาร KLLC",
        "is_active": True
    },
    3: {
        "channel_id": 3,
        "code": "D3",
        "name": "Sky Walk Door",
        "location_label": "ประตูทางเชื่อม Sky Walk",
        "is_active": True
    },
    9: {
        "channel_id": 9,
        "code": "D9",
        "name": "Main Information",
        "location_label": "เคาน์เตอร์ประชาสัมพันธ์หลัก",
        "is_active": True
    }
}

# ISAPI Safe Read Endpoints (Strict Guardrail)
SAFE_ENDPOINTS = {
    "device_info": "/ISAPI/System/deviceInfo",
    "channels": "/ISAPI/ContentMgmt/InputProxy/channels",
    "fd_lib": "/ISAPI/Intelligent/FDLib",
    "fd_search": "/ISAPI/Intelligent/FDLib/FDSearch",
    "alert_stream": "/ISAPI/Event/notification/alertStream",
    "snapshot_track": "/picture/Streaming/tracks/",
    "live_picture": "/ISAPI/Streaming/channels/"
}
