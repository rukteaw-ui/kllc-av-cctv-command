import io
import csv
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Query, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from app.database import (
    get_access_events, get_daily_stats, get_persons,
    upsert_person, get_cameras, insert_access_event,
    get_current_time_str
)
from app.config import CAMERA_CHANNELS, SIMULATION_MODE, BASE_DIR

router = APIRouter(prefix="/api", tags=["API"])

class NVRSettingsPayload(BaseModel):
    nvr_ip: str
    nvr_port: int = 80
    nvr_user: str = "admin"
    nvr_pass: Optional[str] = None

@router.get("/status")
async def get_system_status(request: Request):
    """Retrieve NVR connection status, device model, and active camera channels."""
    isapi_client = getattr(request.app.state, "isapi_client", None)
    nvr_status = {
        "connected": isapi_client.is_connected if isapi_client else False,
        "device_info": isapi_client.device_info if isapi_client else {},
        "simulation_mode": SIMULATION_MODE
    }
    cameras = await get_cameras()
    return {
        "status": "ok",
        "nvr": nvr_status,
        "cameras": cameras,
        "timestamp": get_current_time_str()
    }

@router.get("/stats/daily")
async def get_statistics(date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format")):
    """Get aggregated daily statistics for the dashboard."""
    stats = await get_daily_stats(date)
    return stats

@router.get("/events")
async def list_access_events(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Search by person code or full name"),
    channel_id: Optional[int] = Query(None, description="Filter by camera channel ID"),
    match_status: Optional[str] = Query(None, description="Filter by MATCHED or UNKNOWN"),
    library_name: Optional[str] = Query(None, description="Filter by library name"),
    collapse_unknowns: bool = Query(False, description="Collapse consecutive unknown events"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """List access events with comprehensive filtering and unknown collapse."""
    data = await get_access_events(
        start_date=start_date,
        end_date=end_date,
        search=search,
        channel_id=channel_id,
        match_status=match_status,
        library_name=library_name,
        collapse_unknowns=collapse_unknowns,
        limit=limit,
        offset=offset
    )
    return data

@router.get("/persons")
async def list_personnel(
    search: Optional[str] = Query(None),
    library_name: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """List personnel registered and synced from NVR."""
    return await get_persons(search=search, library_name=library_name, limit=limit, offset=offset)

@router.post("/persons/sync")
async def sync_personnel_from_nvr(request: Request):
    """Trigger manual sync of personnel from NVR FDLib (KLLC STAFF & KLLC Access)."""
    isapi_client = getattr(request.app.state, "isapi_client", None)
    if not isapi_client:
        raise HTTPException(status_code=500, detail="ISAPI client not initialized")

    sync_result = await isapi_client.sync_all_target_libraries()
    persons_synced = sync_result.get("persons", [])

    for p in persons_synced:
        await upsert_person(p)

    # If NVR offline and no personnel in DB, seed sample demonstration data
    if len(persons_synced) == 0:
        db_persons = await get_persons(limit=5)
        if db_persons["total"] == 0:
            sample_staff = [
                {"person_code": "130001", "full_name": "130001_Somchai Jaidee", "library_name": "KLLC STAFF", "fdid": "1", "pid": "1001", "consent_status": "CONSENTED"},
                {"person_code": "130009", "full_name": "130009_Yupin Lo", "library_name": "KLLC STAFF", "fdid": "1", "pid": "1009", "consent_status": "CONSENTED"},
                {"person_code": "130015", "full_name": "130015_Wiphas On-nom", "library_name": "KLLC STAFF", "fdid": "1", "pid": "1015", "consent_status": "CONSENTED"},
                {"person_code": "ACC2001", "full_name": "ACC2001_VIP Guest Researcher", "library_name": "KLLC Access", "fdid": "2", "pid": "2001", "consent_status": "CONSENTED"},
            ]
            for s in sample_staff:
                await upsert_person(s)
            return {
                "success": True,
                "message": f"NVR offline - Loaded {len(sample_staff)} initial template personnel records into database.",
                "total_synced": len(sample_staff),
                "libraries_found": ["KLLC STAFF (Local)", "KLLC Access (Local)"]
            }

    return {
        "success": True,
        "message": f"Successfully synced {len(persons_synced)} personnel from NVR.",
        "total_synced": len(persons_synced),
        "libraries_found": sync_result.get("libraries_found", [])
    }

@router.get("/export/excel")
async def export_excel(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    channel_id: Optional[int] = None,
    match_status: Optional[str] = None,
    library_name: Optional[str] = None,
    collapse_unknowns: bool = False
):
    """Export filtered access history to professional styled Excel workbook (.xlsx)."""
    # Fetch all records matching the filter (no pagination)
    data = await get_access_events(
        start_date=start_date,
        end_date=end_date,
        search=search,
        channel_id=channel_id,
        match_status=match_status,
        library_name=library_name,
        collapse_unknowns=collapse_unknowns,
        limit=10000,
        offset=0
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "KLLC Access Log"

    # Styling definitions
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Segoe UI", size=10)
    matched_font = Font(name="Segoe UI", size=10, bold=True, color="047857")
    unknown_font = Font(name="Segoe UI", size=10, color="64748B")
    border_thin = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    headers = [
        "ลำดับ", "วันและเวลา (Event Time)", "ช่องกล้อง", "จุดติดตั้ง (Camera Name)",
        "สถานะ (Status)", "รหัสบุคคล (Person Code)", "ชื่อ-นามสกุล (Full Name)",
        "สังกัด/คลัง (Library)", "% ความเหมือน (Similarity)", "ทิศทาง (Direction)"
    ]

    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border_thin
    ws.row_dimensions[1].height = 28

    # Populate rows
    for idx, item in enumerate(data["items"], start=1):
        is_matched = item["match_status"] == "MATCHED"
        row_vals = [
            idx,
            item["event_time"],
            f"D{item['channel_id']}",
            item["camera_name"],
            "ระบุตัวตนได้ (MATCHED)" if is_matched else "ไม่ทราบตัวตน (UNKNOWN)",
            item["person_code"] or "-",
            item["full_name"] or "-",
            item["library_name"] or "-",
            f"{item['similarity']:.1f}%" if is_matched else "-",
            "เข้า (IN)" if item["direction"] == "IN" else "ออก (OUT)"
        ]
        ws.append(row_vals)
        current_row = idx + 1
        ws.row_dimensions[current_row].height = 20

        for col_idx in range(1, len(row_vals) + 1):
            cell = ws.cell(row=current_row, column=col_idx)
            cell.border = border_thin
            cell.alignment = Alignment(vertical="center")

            if col_idx in [1, 3, 9, 10]:
                cell.alignment = Alignment(horizontal="center", vertical="center")

            if col_idx == 5:
                cell.font = matched_font if is_matched else unknown_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.font = data_font

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 14)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"kllc_access_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/export/csv")
async def export_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    channel_id: Optional[int] = None,
    match_status: Optional[str] = None,
    library_name: Optional[str] = None,
    collapse_unknowns: bool = False
):
    """Export filtered access history to CSV with UTF-8 BOM for Thai Excel compatibility."""
    data = await get_access_events(
        start_date=start_date,
        end_date=end_date,
        search=search,
        channel_id=channel_id,
        match_status=match_status,
        library_name=library_name,
        collapse_unknowns=collapse_unknowns,
        limit=10000,
        offset=0
    )

    output = io.StringIO()
    # Write UTF-8 BOM so Excel opens Thai characters without garbled text
    output.write('\ufeff')

    writer = csv.writer(output)
    writer.writerow([
        "ลำดับ", "วันและเวลา", "ช่องกล้อง", "จุดติดตั้ง", "สถานะ",
        "รหัสบุคคล", "ชื่อ-นามสกุล", "สังกัด/คลัง", "% ความเหมือน", "ทิศทาง"
    ])

    for idx, item in enumerate(data["items"], start=1):
        is_matched = item["match_status"] == "MATCHED"
        writer.writerow([
            idx,
            item["event_time"],
            f"D{item['channel_id']}",
            item["camera_name"],
            "MATCHED" if is_matched else "UNKNOWN",
            item["person_code"] or "",
            item["full_name"] or "",
            item["library_name"] or "",
            f"{item['similarity']:.1f}%" if is_matched else "",
            item["direction"]
        ])

    csv_bytes = output.getvalue().encode('utf-8-sig')
    filename = f"kllc_access_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/snapshot/proxy")
async def proxy_snapshot(url: str, request: Request):
    """Secure proxy for camera snapshots directly from NVR without storing to local disk."""
    isapi_client = getattr(request.app.state, "isapi_client", None)
    if not isapi_client:
        raise HTTPException(status_code=500, detail="ISAPI client unavailable")

    image_bytes = await isapi_client.get_snapshot_bytes(url)
    if not image_bytes:
        raise HTTPException(status_code=404, detail="Snapshot not found on NVR")

    return Response(content=image_bytes, media_type="image/jpeg")

@router.get("/cameras/{channel_id}/snapshot")
async def get_camera_live_snapshot(channel_id: int, request: Request):
    """Stream live JPEG frame from Hikvision NVR camera channel (read-only, no disk storage)."""
    isapi_client = getattr(request.app.state, "isapi_client", None)
    if not isapi_client:
        raise HTTPException(status_code=500, detail="ISAPI client unavailable")

    image_bytes = await isapi_client.get_camera_live_picture(channel_id)
    if not image_bytes:
        raise HTTPException(status_code=503, detail=f"Camera D{channel_id} stream unavailable")

    return Response(
        content=image_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )

@router.post("/test/simulate-event")
async def simulate_event(
    request: Request,
    match_status: str = Query("MATCHED", pattern="^(MATCHED|UNKNOWN)$"),
    channel_id: int = Query(2, description="Channel ID (1, 2, 3, or 9)")
):
    """Simulate a face recognition event for preview or testing."""
    cam = CAMERA_CHANNELS.get(channel_id, CAMERA_CHANNELS[2])
    now_str = get_current_time_str()

    if match_status == "MATCHED":
        # Random pick among staff
        persons = await get_persons(limit=5)
        person = persons["items"][0] if persons["items"] else {
            "person_code": "130009",
            "full_name": "130009_Yupin Lo",
            "library_name": "KLLC STAFF"
        }
        event = {
            "event_type": "faceMatch",
            "event_time": now_str,
            "channel_id": channel_id,
            "camera_name": cam["name"],
            "match_status": "MATCHED",
            "person_code": person.get("person_code", "130009"),
            "full_name": person.get("full_name", "130009_Yupin Lo"),
            "library_name": person.get("library_name", "KLLC STAFF"),
            "similarity": 95.8,
            "direction": "IN" if channel_id in (2, 3) else "OUT",
            "snapshot_url": None
        }
    else:
        event = {
            "event_type": "faceSnap",
            "event_time": now_str,
            "channel_id": channel_id,
            "camera_name": cam["name"],
            "match_status": "UNKNOWN",
            "person_code": None,
            "full_name": None,
            "library_name": None,
            "similarity": 0.0,
            "direction": "IN" if channel_id in (2, 3) else "OUT",
            "snapshot_url": None
        }

    event_id = await insert_access_event(event)
    event["id"] = event_id

    # Broadcast to WebSocket clients
    broadcaster = getattr(request.app.state, "broadcaster", None)
    if broadcaster:
        await broadcaster.broadcast_json({
            "type": "ACCESS_EVENT",
            "data": event
        })

    return {"success": True, "event": event}

@router.get("/settings")
async def get_nvr_settings(request: Request):
    """Return current NVR connection settings (excluding raw password)."""
    isapi_client = getattr(request.app.state, "isapi_client", None)
    if not isapi_client:
        raise HTTPException(status_code=500, detail="ISAPI client unavailable")
    return {
        "nvr_ip": isapi_client.nvr_ip,
        "nvr_port": isapi_client.nvr_port,
        "nvr_user": isapi_client.nvr_user,
        "has_password": bool(isapi_client.nvr_pass),
        "connected": isapi_client.is_connected,
        "device_info": isapi_client.device_info
    }

@router.post("/settings")
async def update_nvr_settings(payload: NVRSettingsPayload, request: Request):
    """Save NVR settings to .env, test connection, and reconnect alertStream."""
    isapi_client = getattr(request.app.state, "isapi_client", None)
    if not isapi_client:
        raise HTTPException(status_code=500, detail="ISAPI client unavailable")

    # Update in-memory credentials
    isapi_client.update_credentials(
        ip=payload.nvr_ip,
        port=payload.nvr_port,
        user=payload.nvr_user,
        password=payload.nvr_pass
    )

    # Persist to .env file so Windows restarts remember the settings
    env_path = BASE_DIR / ".env"
    env_content = (
        "# KLLC Smart Access Lite - Saved via Web Settings\n"
        f"NVR_IP={isapi_client.nvr_ip}\n"
        f"NVR_PORT={isapi_client.nvr_port}\n"
        f"NVR_USER={isapi_client.nvr_user}\n"
        f"NVR_PASS={isapi_client.nvr_pass}\n"
        "HOST=0.0.0.0\n"
        "PORT=8000\n"
        "DEBUG=False\n"
        "DB_PATH=kllc_access.db\n"
    )
    try:
        env_path.write_text(env_content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ไม่สามารถบันทึกไฟล์ .env ได้: {e}")

    # Test connection immediately
    dev_info = await isapi_client.get_device_info()

    # Restart background stream listener with new credentials
    restart_fn = getattr(request.app.state, "restart_stream", None)
    if restart_fn:
        await restart_fn()

    is_online = dev_info.get("status") == "online"
    if is_online:
        msg = f"บันทึกและเชื่อมต่อ NVR ({dev_info.get('model', 'Hikvision')}) สำเร็จ!"
    elif dev_info.get("code") == 401:
        msg = "บันทึกค่าแล้ว แต่ชื่อผู้ใช้หรือรหัสผ่าน NVR ไม่ถูกต้อง (HTTP 401)"
    elif dev_info.get("code"):
        msg = f"บันทึกค่าแล้ว แต่ NVR ตอบกลับ HTTP {dev_info.get('code')}"
    else:
        msg = f"บันทึกค่าเรียบร้อยแล้ว แต่ยังไม่พบเครื่อง NVR ที่ {isapi_client.nvr_ip}:{isapi_client.nvr_port} ในวงแลนนี้"

    return {
        "success": True,
        "connected": is_online,
        "device_info": dev_info,
        "message": msg
    }

@router.get("/diagnose")
async def diagnose_nvr(request: Request):
    """Run live ISAPI connectivity diagnostics (DeviceInfo, D2 Picture, FDLib)."""
    isapi_client = getattr(request.app.state, "isapi_client", None)
    if not isapi_client:
        raise HTTPException(status_code=500, detail="ISAPI client unavailable")
    return await isapi_client.run_diagnostics()


