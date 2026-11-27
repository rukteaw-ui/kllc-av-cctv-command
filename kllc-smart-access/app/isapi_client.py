import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Callable, AsyncGenerator
import httpx

from app.config import (
    NVR_BASE_URL, NVR_USER, NVR_PASS, TARGET_LIBRARIES,
    SAFE_ENDPOINTS, SIMULATION_MODE
)
from app.parser import parse_alert_payload, clean_tag, parse_xml_tree

logger = logging.getLogger("isapi_client")

class HikvisionISAPIClient:
    def __init__(self):
        self.base_url = NVR_BASE_URL.rstrip("/")
        self.auth = httpx.DigestAuth(NVR_USER, NVR_PASS)
        self.is_connected = False
        self.device_info = {}
        self.running_stream_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def _get_client(self, timeout: float = 10.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=self.auth,
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
        """Fetch NVR device info (GET /ISAPI/System/deviceInfo)."""
        endpoint = SAFE_ENDPOINTS["device_info"]
        url = f"{self.base_url}{endpoint}"

        try:
            async with await self._get_client(timeout=5.0) as client:
                resp = await client.get(url)
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
                    return {
                        "status": "online",
                        "deviceName": info.get("deviceName", "Hikvision NVR"),
                        "model": info.get("model", "iDS-7716NXI-M4/X"),
                        "serialNumber": info.get("serialNumber", "-"),
                        "firmwareVersion": info.get("firmwareVersion", "-"),
                    }
                else:
                    self.is_connected = False
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
                        for fd_el in root.findall(".//FDLib"):
                            fdid_el = fd_el.find(".//FDID")
                            name_el = fd_el.find(".//name")
                            cap_el = fd_el.find(".//faceLibCapacity") or fd_el.find(".//recordCount")
                            
                            fdid = fdid_el.text.strip() if fdid_el is not None and fdid_el.text else ""
                            name = name_el.text.strip() if name_el is not None and name_el.text else ""
                            cap = int(cap_el.text.strip()) if cap_el is not None and cap_el.text and cap_el.text.isdigit() else 0

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

        xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<FDSearchDescription xmlns="http://www.hikvision.com/ver20/XMLSchema" version="2.0">
    <searchID>1</searchID>
    <FDID>{fdid}</FDID>
    <searchResultPosition>0</searchResultPosition>
    <maxResults>{max_results}</maxResults>
</FDSearchDescription>"""

        results = []
        try:
            async with await self._get_client(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    content=xml_payload.encode("utf-8"),
                    headers={"Content-Type": "application/xml; charset=UTF-8"}
                )
                if resp.status_code == 200:
                    root = parse_xml_tree(resp.text)
                    if root is not None:
                        for item in root.findall(".//searchResult") or root.findall(".//FDSearchResult"):
                            pid_el = item.find(".//PID")
                            name_el = item.find(".//name")
                            code_el = item.find(".//customInfo") or item.find(".//personCode")
                            model_status_el = item.find(".//modelStatus")

                            pid = pid_el.text.strip() if pid_el is not None and pid_el.text else ""
                            name = name_el.text.strip() if name_el is not None and name_el.text else ""
                            code = code_el.text.strip() if code_el is not None and code_el.text else ""

                            if not code and name and "_" in name:
                                parts = name.split("_", 1)
                                if parts[0].isdigit():
                                    code = parts[0]

                            results.append({
                                "pid": pid,
                                "person_code": code or pid,
                                "full_name": name or "Unknown",
                                "fdid": fdid,
                                "model_status": model_status_el.text.strip() if model_status_el is not None and model_status_el.text else "unknown"
                            })
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

    async def start_alert_stream(
        self,
        event_callback: Callable[[Dict[str, Any]], Any],
        status_callback: Callable[[Dict[str, Any]], Any]
    ):
        """
        Long-lived HTTP Alert Stream listener (/ISAPI/Event/notification/alertStream)
        with automatic reconnection and exponential backoff.
        """
        self._stop_event.clear()
        endpoint = SAFE_ENDPOINTS["alert_stream"]
        url = f"{self.base_url}{endpoint}"

        backoff_seconds = 2
        max_backoff = 30

        logger.info(f"Starting ISAPI alert stream listener at {url}")

        while not self._stop_event.is_set():
            try:
                await status_callback({"connected": False, "status": "connecting", "message": f"Connecting to NVR ({self.base_url})..."})
                
                # Check device online first
                dev_info = await self.get_device_info()
                if dev_info.get("status") != "online":
                    raise ConnectionError(f"NVR offline or unreachable: {dev_info.get('error', 'Auth/Network Error')}")

                async with httpx.AsyncClient(auth=self.auth, timeout=None, verify=False) as client:
                    async with client.stream("GET", url) as stream_resp:
                        if stream_resp.status_code != 200:
                            raise ConnectionError(f"alertStream returned HTTP {stream_resp.status_code}")

                        self.is_connected = True
                        backoff_seconds = 2  # Reset backoff on successful connect
                        await status_callback({
                            "connected": True,
                            "status": "connected",
                            "message": f"Connected to NVR ({dev_info.get('model', 'iDS-7716NXI-M4/X')})"
                        })

                        buffer = ""
                        async for chunk in stream_resp.aiter_text():
                            if self._stop_event.is_set():
                                break

                            buffer += chunk
                            # Split by boundary lines (e.g. --MIME_boundary, --boundary)
                            if "--" in buffer:
                                parts = buffer.split("--")
                                # Keep the last incomplete part in buffer
                                buffer = parts[-1]

                                for part in parts[:-1]:
                                    part = part.strip()
                                    if not part:
                                        continue

                                    # Extract body (skip MIME headers)
                                    body = part
                                    if "\r\n\r\n" in part:
                                        body = part.split("\r\n\r\n", 1)[1]
                                    elif "\n\n" in part:
                                        body = part.split("\n\n", 1)[1]

                                    parsed_event = parse_alert_payload(body)
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
