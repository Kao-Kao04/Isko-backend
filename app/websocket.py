import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # user_id -> WebSocket
        self._connections: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        self._connections[user_id] = websocket
        logger.info("WS connected: user_id=%s", user_id)

    def disconnect(self, user_id: int) -> None:
        self._connections.pop(user_id, None)
        logger.info("WS disconnected: user_id=%s", user_id)

    async def send(self, user_id: int, payload: dict) -> None:
        ws = self._connections.get(user_id)
        if not ws:
            return
        try:
            await ws.send_json(payload)
        except Exception:
            self.disconnect(user_id)


manager = ConnectionManager()
