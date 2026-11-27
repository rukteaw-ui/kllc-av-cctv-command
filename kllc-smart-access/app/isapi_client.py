import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Callable
import httpx

from app.config import (
    NVR_IP, NVR_PORT, NVR_BASE_URL, NVR_USER, NVR_PASS, TARGET_LIBRARIES,
    SAFE_ENDPOINTS, SIMULATION_MODE
)
from app.parser import parse_alert_payload, clean_tag, parse_xml_tree, find_first_text

logger = logging.getLogger("isapi_client")

class HikvisionISAPIClient:
    def __init__(self):
        self.nvr_ip = NVR_IP
        self.nvr_port = NVR_PORT
        self.nvr_user = NVR_USER
        self.nvr_pass = NVR_PASS
        self.base_url = NVR_BASE_URL.rstrip("/")
        self.is_connected = False
        self.device_info = {}
        self.running_stream_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._use_basic_auth = False
        self._stream_id_cache: Dict[int, int] = {}
        self._auth_failed = False

    def has_credentials(self) -> bool:
        """Return True only when IP, username, and password are all explicitly configured."""
        return bool(self.nvr_ip and self.nvr_user and self.nvr_pass)

    def _make_auth(self, force_basic: bool = False):
        """Create a fresh auth instance per client (httpx.DigestAuth is NOT concurrency-safe when shared)."""
        if force_basic or self._use_basic_auth:
            return httpx.BasicAuth(self.nvr_user, self.nvr_pass)
        return httpx.DigestAuth(self.nvr_user, self.nvr_pass)

    def update_credentials(self, ip: str, port: int, user: str, password: Optional[str] = None):
        """Update NVR connection credentials at runtime without restarting the server."""
        self.nvr_ip = ip.strip()
        self.nvr_port = int(port)
        self.nvr_user = user.strip()
        if password is not None and password != "":
            self.nvr_pass = password
        self.base_url = f"http://{self.nvr_ip}:{self.nvr_port}".rstrip("/")
        self.is_connected = False
        self._use_basic_auth = False
        self._auth_failed = False
        self._stream_id_cache.clear()

    async def _get_client(self, timeout: float = 10.0, force_basic: bool = False) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=self._make_auth(force_basic=force_basic),
            timeout=timeout,
            verify=False
        )

    def is_safe_url(self, path: str) -> bool:
        """Enforce strict safe-read allowlist guardrail."""
        for safe_key, safe_path in SAFE_ENDPOINTS.items():
            if path.startswith(safe_path):
                return True
        return False

    async def get_device_info(self) -> Dict[str, Any]:
        """Fetch NVR device info (GET /ISAPI/System/deviceInfo) with anti-lockout circuit breaker."""
        if not self.has_credentials():
            self.is_connected = False
            return {"status": "unconfigured", "error": "ยังไม่ได้ตั้งค่าชื่อผู้ใช้และรหัสผ่าน NVR"}

        endpoint = SAFE_ENDPOINTS["device_info"]
        url = f"{self.base_url}{endpoint}"

        try:
            async with await self._get_client(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 401 and "basic" in resp.headers.get("www-authenticate", "").lower():
                    async with await self._get_client(timeout=5.0, force_basic=True) as basic_client:
                        resp = await basic_client.get(url)
                        if resp.status_code == 200:
                            self._use_basic_auth = True
                if resp.status_code == 200:
                    root = parse_xml_tree(resp.text)
                    if root is None:
                        return {"status": "error", "detail": "Failed to parse device info XML"}
                    info = {}
                    for child in root:
                        tag = clean_tag(child.tag)
                        info[tag] = child.text
                    self.device_info = info
                    self.is_connected = True
                    self._auth_failed = False
                    return {
                        "status": "online",
                        "deviceName": info.get("deviceName", "Hikvision NVR"),
                        "model": info.get("model", "iDS-7716NXI-M4/X"),
                        "serialNumber": info.get("serialNumber", "-"),
                        "firmwareVersion": info.get("firmwareVersion", "-"),
                    }
                else:
                    self.is_connected = False
                    if resp.status_code in (401, 403):
                        self._auth_failed = True
                    return {"status": "error", "code": resp.status_code, "detail": resp.text[:200]}
        except Exception as e:
            self.is_connected = False
            return {"status": "offline", "error": str(e)}

    async def get_face_libraries(self) -> List[Dict[str, Any]]:
        """Fetch face libraries from NVR (GET /ISAPI/Intelligent/FDLib)."""
        endpoint = SAFE_ENDPOINTS["fd_lib"]
        url = f"{self.base_url}{endpoint}"

        libraries = []
        try:
            async with await self._get_client(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    root = parse_xml_tree(resp.text)
                    if root is not None:
                        nodes = root.findall(".//FDLibBaseCfg") or root.findall(".//FDLib")
                        for fd_el in nodes:
                            fdid = find_first_text(fd_el, ".//FDID", ".//id") or ""
                            name = find_first_text(fd_el, ".//name", ".//Name") or ""
                            cap_str = find_first_text(fd_el, ".//faceLibCapacity", ".//recordCount") or "0"
                            cap = int(cap_str) if cap_str.isdigit() else 0

                            if fdid or name:
                                libraries.append({
                                    "fdid": fdid,
                                    "name": name,
                                    "count": cap
                                })
        except Exception as e:
            logger.error(f"Error fetching face libraries: {e}")
        return libraries

    async def search_faces_in_library(self, fdid: str, max_results: int = 500) -> List[Dict[str, Any]]:
        """Search face entries in a specific FDLib (POST /ISAPI/Intelligent/FDLib/FDSearch)."""
        endpoint = SAFE_ENDPOINTS["fd_search"]
        url = f"{self.base_url}{endpoint}"

        results = []
        position = 0
        page_size = min(max_results, 100)

        try:
            async with await self._get_client(timeout=15.0) as client:
                while len(results) < max_results:
                    xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<FDSearchDescription xmlns="http://www.hikvision.com/ver20/XMLSchema" version="2.0">
    <searchID>1</searchID>
    <FDID>{fdid}</FDID>
    <searchResultPosition>{position}</searchResultPosition>
    <maxResults>{page_size}</maxResults>
</FDSearchDescription>"""
                    resp = await client.post(
                        url,
                        content=xml_payload.encode("utf-8"),
                        headers={"Content-Type": "application/xml; charset=UTF-8"}
                    )
                    if resp.status_code != 200:
                        break

                    text = resp.text.strip()
                    batch = []
                    total_matches = 0

                    if text.startswith("{"):
                        data = json.loads(text)
                        total_matches = int(data.get("totalMatches", 0))
                        items = data.get("MatchList", data.get("searchResult", []))
                        for it in items:
                            pid = str(it.get("PID") or it.get("FPID") or "")
                            name = str(it.get("name") or "")
                            code = str(it.get("customInfo") or it.get("personCode") or it.get("certificateNumber") or "")
                            if not code and name and "_" in name and name.split("_", 1)[0].isdigit():
                                code = name.split("_", 1)[0]
                            batch.append({
                                "pid": pid,
                                "person_code": code or pid,
                                "full_name": name or "Unknown",
                                "fdid": fdid,
                                "model_status": str(it.get("modelStatus", "unknown"))
                            })
                    else:
                        root = parse_xml_tree(text)
                        if root is None:
                            break
                        total_str = find_first_text(root, ".//totalMatches") or "0"
                        total_matches = int(total_str) if total_str.isdigit() else 0
                        items = (
                            root.findall(".//MatchElement")
                            or root.findall(".//searchResult")
                            or root.findall(".//FDSearchResult")
                        )
                        for item in items:
                            pid = find_first_text(item, ".//PID", ".//FPID") or ""
                            name = find_first_text(item, ".//name", ".//personName") or ""
                            code = find_first_text(item, ".//customInfo", ".//personCode", ".//certificateNumber") or ""
                            model_status = find_first_text(item, ".//modelStatus") or "unknown"

                            if not code and name and "_" in name:
                                parts = name.split("_", 1)
                                if parts[0].isdigit():
                                    code = parts[0]

                            if pid or name or code:
                                batch.append({
                                    "pid": pid,
                                    "person_code": code or pid,
                                    "full_name": name or "Unknown",
                                    "fdid": fdid,
                                    "model_status": model_status
                                })

                    results.extend(batch)
                    if not batch or (total_matches > 0 and len(results) >= total_matches) or len(batch) < page_size:
                        break
                    position += len(batch)
        except Exception as e:
            logger.error(f"Error searching faces in library {fdid}: {e}")
        return results

    async def sync_all_target_libraries(self) -> Dict[str, Any]:
        """Fetch all face libraries matching 'KLLC STAFF' and 'KLLC Access' and return persons list."""
        libs = await self.get_face_libraries()
        matched_libs = [lib for lib in libs if any(target.lower() in lib["name"].lower() for target in TARGET_LIBRARIES)]

        total_synced = 0
        all_persons = []

        for lib in matched_libs:
            fdid = lib["fdid"]
            lib_name = lib["name"]
            faces = await self.search_faces_in_library(fdid)
            for f in faces:
                f["library_name"] = lib_name
                f["consent_status"] = "CONSENTED"
                all_persons.append(f)
            total_synced += len(faces)

        return {
            "total_synced": total_synced,
            "libraries_found": [lib["name"] for lib in matched_libs],
            "persons": all_persons
        }

    async def get_snapshot_bytes(self, track_or_snap_path: str) -> Optional[bytes]:
        """Proxy snapshot image from NVR without storing to disk (GET /picture/Streaming/tracks/...)."""
        if not track_or_snap_path:
            return None
            
        clean_path = track_or_snap_path.replace(self.base_url, "")
        if not clean_path.startswith("/"):
            clean_path = f"/{clean_path}"

        if not self.is_safe_url(clean_path) and not clean_path.startswith("/picture/"):
            logger.warning(f"Blocked unauthorized snapshot path: {clean_path}")
            return None

        url = f"{self.base_url}{clean_path}"
        try:
            async with await self._get_client(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.content
        except Exception as e:
            logger.error(f"Error fetching snapshot: {e}")
        return None

    async def get_camera_live_picture(self, channel_id: int) -> Optional[bytes]:
        """Fetch live JPEG snapshot for a camera channel without saving to disk. Never polls if unauthenticated."""
        if not self.is_connected or self._auth_failed or not self.has_credentials():
            return None

        cached = self._stream_id_cache.get(channel_id)
        candidate_streams = [cached] if cached else [channel_id * 100 + 2, channel_id * 100 + 1, channel_id]
        try:
            async with await self._get_client(timeout=4.0) as client:
                for stream_id in candidate_streams:
                    path = f"/ISAPI/Streaming/channels/{stream_id}/picture"
                    if not self.is_safe_url(path):
                        continue
                    url = f"{self.base_url}{path}"
                    resp = await client.get(url)
                    if resp.status_code in (401, 403):
                        self._auth_failed = True
                        self.is_connected = False
                        return None
                    if resp.status_code == 200 and resp.content and resp.content.startswith(b"\xff\xd8"):
                        self._stream_id_cache[channel_id] = stream_id
                        return resp.content
                # If cached stream stopped working, clear cache so next call re-probes
                if cached:
                    self._stream_id_cache.pop(channel_id, None)
        except Exception as e:
            logger.debug(f"Live picture unavailable for D{channel_id}: {e}")
        return None

    async def run_diagnostics(self) -> Dict[str, Any]:
        """Run 1-click end-to-end ISAPI connectivity diagnostics for troubleshooting."""
        report = {
            "nvr_url": self.base_url,
            "nvr_user": self.nvr_user,
            "auth_mode": "Basic" if self._use_basic_auth else "Digest",
            "auth_locked_protection": self._auth_failed,
            "device_info": await self.get_device_info(),
            "camera_d2_picture": False,
            "face_libraries": []
        }
        if report["device_info"].get("status") == "online":
            pic = await self.get_camera_live_picture(2)
            report["camera_d2_picture"] = bool(pic)
            libs = await self.get_face_libraries()
            report["face_libraries"] = [l["name"] for l in libs]
        return report

    async def start_alert_stream(
        self,
        event_callback: Callable[[Dict[str, Any]], Any],
        status_callback: Callable[[Dict[str, Any]], Any]
    ):
        """
        Long-lived HTTP Alert Stream listener (/ISAPI/Event/notification/alertStream)
        with automatic reconnection on network drops AND strict anti-lockout stop on HTTP 401/403.
        """
        self._stop_event.clear()
        endpoint = SAFE_ENDPOINTS["alert_stream"]

        if not self.has_credentials():
            self.is_connected = False
            await status_callback({
                "connected": False,
                "status": "unconfigured",
                "message": "รอตั้งค่า NVR (กดปุ่ม ⚙️ ตั้งค่า NVR เพื่อใส่ชื่อผู้ใช้และรหัสผ่าน)"
            })
            return

        backoff_seconds = 2
        max_backoff = 30

        logger.info(f"Starting ISAPI alert stream listener at {self.base_url}{endpoint}")

        while not self._stop_event.is_set():
            url = f"{self.base_url}{endpoint}"
            try:
                await status_callback({"connected": False, "status": "connecting", "message": f"กำลังเชื่อมต่อ NVR ({self.nvr_ip})..."})
                
                # Check device online first
                dev_info = await self.get_device_info()
                if dev_info.get("code") in (401, 403):
                    self._auth_failed = True
                    self.is_connected = False
                    logger.error("NVR authentication failed (HTTP 401/403). Stopping auto-retry to prevent NVR Illegal Login Lock.")
                    await status_callback({
                        "connected": False,
                        "status": "auth_error",
                        "message": "หยุดเชื่อมต่ออัตโนมัติ (รหัสผ่าน NVR ไม่ถูกต้อง — ป้องกันเครื่องล็อก)"
                    })
                    return

                if dev_info.get("status") != "online":
                    err_detail = f"HTTP {dev_info.get('code')}" if dev_info.get("code") else dev_info.get("error", "Network Error")
                    raise ConnectionError(f"NVR offline or unreachable: {err_detail}")

                async with httpx.AsyncClient(auth=self._make_auth(), timeout=None, verify=False) as client:
                    async with client.stream("GET", url) as stream_resp:
                        if stream_resp.status_code in (401, 403):
                            self._auth_failed = True
                            self.is_connected = False
                            await status_callback({
                                "connected": False,
                                "status": "auth_error",
                                "message": "หยุดเชื่อมต่ออัตโนมัติ (สิทธิ์ ISAPI ไม่ผ่าน HTTP 401 — ป้องกันเครื่องล็อก)"
                            })
                            return
                        if stream_resp.status_code != 200:
                            raise ConnectionError(f"alertStream returned HTTP {stream_resp.status_code}")

                        self.is_connected = True
                        backoff_seconds = 2  # Reset backoff on successful connect
                        await status_callback({
                            "connected": True,
                            "status": "connected",
                            "message": f"NVR เชื่อมต่อปกติ ({dev_info.get('model', 'iDS-7716NXI-M4/X')})"
                        })

                        # Detect MIME boundary from Content-Type header (e.g. multipart/mixed; boundary=boundary)
                        ct_header = stream_resp.headers.get("content-type", "")
                        b_match = re.search(r'boundary=([^;\s"]+)', ct_header, re.IGNORECASE)
                        boundary_str = b_match.group(1).strip('"') if b_match else "boundary"
                        if not boundary_str.startswith("--"):
                            boundary_bytes = f"--{boundary_str}".encode("ascii", errors="ignore")
                        else:
                            boundary_bytes = boundary_str.encode("ascii", errors="ignore")

                        buf = b""
                        async for chunk in stream_resp.aiter_bytes():
                            if self._stop_event.is_set():
                                break

                            buf += chunk
                            # Prevent unbounded memory growth on malformed streams (cap at 10 MB)
                            if len(buf) > 10 * 1024 * 1024:
                                buf = buf[-2 * 1024 * 1024:]

                            if boundary_bytes in buf:
                                parts = buf.split(boundary_bytes)
                                buf = parts[-1]

                                for part in parts[:-1]:
                                    if not part or len(part) < 10:
                                        continue

                                    # Split MIME headers and body
                                    if b"\r\n\r\n" in part:
                                        headers_raw, body_raw = part.split(b"\r\n\r\n", 1)
                                    elif b"\n\n" in part:
                                        headers_raw, body_raw = part.split(b"\n\n", 1)
                                    else:
                                        headers_raw, body_raw = b"", part

                                    headers_lower = headers_raw.decode("ascii", errors="ignore").lower()
                                    # Skip raw binary image attachments (JPEG/PNG) safely
                                    if "image/" in headers_lower or body_raw.startswith(b"\xff\xd8"):
                                        continue

                                    body_text = body_raw.decode("utf-8", errors="ignore").strip()
                                    if not body_text:
                                        continue

                                    parsed_event = parse_alert_payload(body_text)
                                    if parsed_event:
                                        await event_callback(parsed_event)

            except asyncio.CancelledError:
                logger.info("Alert stream task cancelled")
                break
            except Exception as e:
                self.is_connected = False
                logger.warning(f"alertStream disconnected: {e}. Retrying in {backoff_seconds}s...")
                await status_callback({
                    "connected": False,
                    "status": "reconnecting",
                    "message": f"Connection lost: {e}. Reconnecting in {backoff_seconds}s...",
                    "backoff": backoff_seconds
                })
                
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff_seconds)
                except asyncio.TimeoutError:
                    pass

                backoff_seconds = min(backoff_seconds * 2, max_backoff)

        self.is_connected = False
        await status_callback({"connected": False, "status": "stopped", "message": "Stream listener stopped"})

    def stop_alert_stream(self):
        """Signal the stream listener to stop."""
        self._stop_event.set()
        if self.running_stream_task and not self.running_stream_task.done():
            self.running_stream_task.cancel()
