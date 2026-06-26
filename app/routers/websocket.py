"""WebSocket endpoint for EC2/ECS deployments.

Maintains an in-memory set of active WebSocket connections and provides
a server-push-only endpoint at /ws. Clients connect to receive real-time
broadcast messages (vote updates, visibility changes) but do not send
meaningful messages — any received messages are ignored.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# In-memory set of active WebSocket connections.
# Exported so the broadcast service can iterate and push messages.
active_connections: set[WebSocket] = set()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Accept a WebSocket connection and hold it open for server-push broadcasts.

    On connect: accept and add to active_connections set.
    On disconnect: remove from active_connections set.
    On message: ignore (this is a server-push-only endpoint).
    """
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True:
            # Keep connection alive by waiting for messages.
            # Any received messages are ignored — server-push only.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(websocket)
