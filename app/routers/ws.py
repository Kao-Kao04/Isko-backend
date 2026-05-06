from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError

from app.utils.security import decode_token
from app.websocket import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket, token: str = Query(...)):
    """
    Connect: ws://host/ws/notifications?token=<access_token>
    Receives: { "type": "notification", "id": 1, "title": "...", "body": "...", "application_id": null }
    """
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token type")
            return
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            # Keep connection alive — client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id)
