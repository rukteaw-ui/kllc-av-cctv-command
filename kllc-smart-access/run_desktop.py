"""
KLLC Smart Access Lite - Standalone Windows Desktop Launcher
Double-click KLLC_Smart_Access.exe -> Auto-starts server & opens browser.
"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
import uvicorn

from app.config import HOST, PORT
from app.main import app


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_browser_when_ready(port: int):
    url = f"http://localhost:{port}"
    health_url = f"http://127.0.0.1:{port}/api/status"
    for _ in range(30):
        try:
            with urllib.request.urlopen(health_url, timeout=1) as resp:
                if resp.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.5)
    webbrowser.open(url)


def main():
    print("=" * 72)
    print("  KLLC SMART ACCESS LITE (Standalone Edition)")
    print("  Hikvision DeepinMind Pro (iDS-7716NXI-M4/X) ISAPI Face Access System")
    print("=" * 72)

    if is_port_in_use(PORT):
        print(f"\n[INFO] KLLC Smart Access Lite is already running on port {PORT}.")
        print(f"[INFO] Opening http://localhost:{PORT} in your browser...")
        if os.environ.get("KLLC_NO_BROWSER") != "1":
            webbrowser.open(f"http://localhost:{PORT}")
        time.sleep(2)
        return

    if os.environ.get("KLLC_NO_BROWSER") != "1":
        threading.Thread(target=open_browser_when_ready, args=(PORT,), daemon=True).start()

    print(f"\n[READY] Server running at http://localhost:{PORT}")
    print("[TIP]   Keep this window open while using the system. Close it to stop.\n")

    try:
        uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    except Exception as exc:
        print(f"\n[ERROR] Failed to start server: {exc}")
        input("Press Enter to close...")


if __name__ == "__main__":
    main()
