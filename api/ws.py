"""
WebSocket connection manager.

WebSockets are used for four things and nothing else. Real-time transport is
a cost, not a feature, and a field app on a 2G connection should not hold a
socket open to render a list.

  1. consent.requested   -> the patient's phone lights up the moment a doctor asks
  2. consent.decided     -> the doctor's dashboard populates, or does not
  3. consent.revoked     -> the doctor's view greys out mid-session
  4. patient.updated     -> the doctor's queue re-sorts as new symptoms arrive

Delivery is best-effort. Nothing clinical depends on a socket being open:
every event here has a REST equivalent that the client polls on reconnect. A
missed WebSocket frame must never be the reason a red flag goes unseen.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._sockets[user_id].add(ws)

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._sockets[user_id].discard(ws)
            if not self._sockets[user_id]:
                self._sockets.pop(user_id, None)

    async def send(self, user_id: str, event: str, payload: dict[str, Any]) -> int:
        """Returns how many sockets received it. Zero is normal and fine."""
        async with self._lock:
            targets = list(self._sockets.get(user_id, ()))

        message = {"event": event, "payload": payload}
        delivered = 0
        for ws in targets:
            try:
                await ws.send_json(message)
                delivered += 1
            except Exception:
                await self.disconnect(user_id, ws)
        return delivered

    def online(self, user_id: str) -> bool:
        return bool(self._sockets.get(user_id))

    def stats(self) -> dict[str, int]:
        return {uid: len(socks) for uid, socks in self._sockets.items()}


manager = ConnectionManager()

# ─────────────────────────────────────────────────────────────────────────────
# Bridge from synchronous route handlers to the async socket layer.
#
# FastAPI runs `def` endpoints in a worker thread, so they cannot await. Rather
# than making every database call async - which with a blocking MySQL driver
# would stall the event loop and be strictly worse - sync handlers hand the
# notification to the loop here and return immediately.
# ─────────────────────────────────────────────────────────────────────────────

_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def notify(user_id: str, event: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget. Safe to call from a sync endpoint, and safe to call
    when nobody is listening."""
    if _loop is None or _loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.send(user_id, event, payload), _loop)
    except RuntimeError:
        pass
