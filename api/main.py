"""
AIRA API.

    py -3.11 -m uvicorn api.main:app --reload --port 8000

Docs at http://localhost:8000/docs
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db, init_db, ping
from .routers import (
    admin,
    auth,
    chat,
    consent,
    doctor,
    documents,
    fhir,
    notes,
    patient,
    voice,
)
from .security import decode_access_token
from .service import rules
from .ws import bind_loop, manager

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Fail fast and loudly if the rules are malformed. A server that boots
    # with a broken ruleset is far more dangerous than one that refuses to.
    rs = rules()
    bind_loop(asyncio.get_running_loop())
    print(f"AIRA ready  |  ruleset v{rs.version}  |  {len(rs.symptoms)} symptoms  |  MySQL {ping()}")
    yield


app = FastAPI(
    title="AIRA",
    description=(
        "AI Risk & Awareness Assistant. Longitudinal symptom tracking and "
        "automated safety netting for early cancer detection.\n\n"
        "Architecture: **rules decide, models rank, the LLM only phrases what "
        "the rules already decided.**"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(consent.router)
app.include_router(patient.router)
app.include_router(doctor.router)
app.include_router(voice.router)
app.include_router(admin.router)
app.include_router(fhir.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(notes.router)


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    rs = rules()
    return {
        "status": "ok",
        "mysql": ping(),
        "ruleset_version": rs.version,
        "symptoms": len(rs.symptoms),
        "red_flags": len(rs.red_flags),
        "sarvam_mode": settings.sarvam_mode,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = ""):
    """Real-time channel.

    Authenticated by access token in the query string, because browsers cannot
    set headers on a WebSocket handshake. The token is short-lived (15
    minutes) which is what makes that acceptable.

    Nothing clinical depends on this socket. Every event delivered here has a
    REST equivalent the client polls on reconnect - a dropped frame must never
    be the reason a red flag goes unseen.
    """
    payload = decode_access_token(token)
    if payload is None:
        await ws.close(code=4401)
        return

    user_id = payload["sub"]
    await manager.connect(user_id, ws)
    try:
        await ws.send_json(
            {"event": "connected", "payload": {"user_id": user_id, "role": payload["role"]}}
        )
        while True:
            # The client sends heartbeats; the server has nothing to read.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user_id, ws)


@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})
