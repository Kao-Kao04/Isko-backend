import hashlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError
from sqlalchemy import select

from app.utils.security import decode_token
from app.token_blacklist import is_revoked
from app.websocket import manager
from app.database import AsyncSessionLocal
from app.models.user import User

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

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if is_revoked(token_hash):
        await websocket.close(code=4003, reason="Token has been revoked")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))  # noqa: E712
        if not result.scalar_one_or_none():
            await websocket.close(code=4003, reason="Account is inactive")
            return

    await manager.connect(websocket, user_id)
    try:
        while True:
            # Keep connection alive — client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id)
