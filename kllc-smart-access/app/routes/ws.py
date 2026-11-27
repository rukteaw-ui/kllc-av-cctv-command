import logging
from typing import List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("websocket")
router = APIRouter(tags=["WebSocket"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast_json(self, message: dict):
        """Broadcast JSON payload to all connected clients."""
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                self.disconnect(connection)

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager: ConnectionManager = websocket.app.state.broadcaster
    await manager.connect(websocket)

    # Send initial connection handshake
    isapi_client = getattr(websocket.app.state, "isapi_client", None)
    await websocket.send_json({
        "type": "CONNECTION_INIT",
        "data": {
            "connected": isapi_client.is_connected if isapi_client else False,
            "message": "Connected to KLLC Smart Access WebSocket stream."
        }
    })

    try:
        while True:
            data = await websocket.receive_text()
            # Client can send ping
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
