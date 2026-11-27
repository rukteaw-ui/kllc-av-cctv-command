import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import HOST, PORT, DEBUG, BASE_DIR, BUNDLE_DIR
from app.database import init_db, insert_access_event
from app.isapi_client import HikvisionISAPIClient
from app.routes.api import router as api_router
from app.routes.ws import router as ws_router, ConnectionManager

# Logging configuration
logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("kllc_access_main")

broadcaster = ConnectionManager()
isapi_client = HikvisionISAPIClient()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Initializing KLLC Smart Access Lite...")
    await init_db()

    app.state.broadcaster = broadcaster
    app.state.isapi_client = isapi_client

    async def on_stream_event(event: dict):
        """Callback when an event arrives from ISAPI alertStream."""
        logger.info(f"Received alert event: {event.get('event_type')} on {event.get('camera_name')}")
        # Insert to database for all face recognition / detection events
        if "match_status" in event:
            event_id = await insert_access_event(event)
            event["id"] = event_id

        # Broadcast via WebSocket
        await broadcaster.broadcast_json({
            "type": "ACCESS_EVENT",
            "data": event
        })

    async def on_status_change(status: dict):
        """Callback when NVR connection status changes."""
        logger.info(f"NVR Status change: {status.get('status')} - {status.get('message')}")
        await broadcaster.broadcast_json({
            "type": "NVR_STATUS",
            "data": status
        })

    async def restart_stream():
        """Stop current alertStream task and start a new one with updated credentials."""
        isapi_client.stop_alert_stream()
        old_task = isapi_client.running_stream_task
        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass
        new_task = asyncio.create_task(
            isapi_client.start_alert_stream(on_stream_event, on_status_change)
        )
        isapi_client.running_stream_task = new_task

    app.state.restart_stream = restart_stream

    # Launch background alert stream listener
    await restart_stream()

    logger.info("KLLC Smart Access Lite initialized successfully.")
    yield

    # --- Shutdown ---
    logger.info("Shutting down KLLC Smart Access Lite...")
    isapi_client.stop_alert_stream()
    task = isapi_client.running_stream_task
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="KLLC Smart Access Lite",
    description="ระบบตรวจจับและบันทึกประวัติการเข้า-ออกด้วยใบหน้า สำนักการเรียนรู้ตลอดชีวิต (KLLC) สจล.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(api_router)
app.include_router(ws_router)

# Mount Static Files
static_dir = BUNDLE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def serve_index():
    """Serve main Single Page Application dashboard."""
    index_file = BUNDLE_DIR / "static" / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "KLLC Smart Access Lite API is running. UI not found in static/."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=DEBUG)
