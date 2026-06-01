import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # user_id -> set of active WebSocket connections (multiple tabs supported)
        self._connections: dict[int, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, set()).add(websocket)
        logger.info("WS connected: user_id=%s total=%s", user_id, len(self._connections[user_id]))

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(user_id)
        if sockets:
            sockets.discard(websocket)
            if not sockets:
                del self._connections[user_id]
        logger.info("WS disconnected: user_id=%s", user_id)

    async def send(self, user_id: int, payload: dict) -> None:
        sockets = self._connections.get(user_id)
        if not sockets:
            return
        dead: set[WebSocket] = set()
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(user_id, ws)


manager = ConnectionManager()
