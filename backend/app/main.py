"""Jarvis PC — FastAPI backend.

REST API (headless access): profiles, dialogue sessions, text chat.
WebSocket /ws: the live channel — JSON control + binary PCM16 audio both ways,
mirroring VoxRelay's voice + text-to-voice modes in the browser.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, Optional

import structlog
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import agent as agent_mod
from app import store
from app.config import settings
from app.db import close_pool, init_pool
from app.models import DialogueSession, Profile, TranscriptRole
from app.presets import PROMPT_PRESETS

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await store.seed_defaults()
    logger.info("Jarvis backend ready", port=settings.port)
    yield
    await close_pool()


app = FastAPI(title="Jarvis PC", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ schemas

class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    role_tag: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_id: Optional[str] = None
    enable_web_search: Optional[bool] = None
    enable_memory: Optional[bool] = None
    enable_tasks: Optional[bool] = None
    orb_style: Optional[str] = None


class ProfileCreate(BaseModel):
    display_name: str
    role_tag: str = ""
    voice_id: str = "FENRIR"
    system_prompt: str = ""
    orb_style: str = "sphere"


class MemoryUpdate(BaseModel):
    memory_text: str = ""
    mode: str = "replace"  # "replace" | "append"


class SessionCreate(BaseModel):
    profile_id: Optional[str] = None
    title: str = ""


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    profile_id: Optional[str] = None


# ------------------------------------------------------------------ helpers


async def _require_profile(profile_id: str) -> Profile:
    prof = await store.get_profile(profile_id)
    if prof is None:
        from fastapi import HTTPException

        raise HTTPException(404, f"profile '{profile_id}' not found")
    return prof


async def _get_or_create_session(session_id: Optional[str], profile_id: str):
    if session_id:
        s = await store.get_session(session_id)
        if s is not None:
            return s
    # Lazy: the row is created on the first persisted message (store.ensure_session)
    return DialogueSession(profile_id=profile_id)


# ------------------------------------------------------------------ REST


@app.get("/api/health")
async def health() -> dict[str, Any]:
    from app.oauth import auth_status

    auth = await auth_status()
    return {
        "ok": True,
        "live_model": settings.live_model,
        "text_model": settings.text_model,
        "search_endpoint": settings.websearch_endpoint,
        "gemini_key_set": bool(settings.gemini_api_key),
        "auth": auth["method"],
    }


# ------------------------------------------------------------- Google auth

from fastapi import HTTPException  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402


@app.get("/api/auth/status")
async def api_auth_status():
    from app.oauth import auth_status

    return await auth_status()


@app.get("/api/auth/google")
async def api_auth_google():
    from app.oauth import build_auth_url, oauth_configured

    if not oauth_configured():
        raise HTTPException(
            400,
            "GOOGLE_OAUTH_CLIENT_ID is not configured — create an OAuth client "
            "in Google Cloud Console first (see README)",
        )
    url, _state = build_auth_url()
    return {"url": url}


@app.get("/api/auth/google/callback")
async def api_auth_callback(code: str = "", state: str = "", error: str = ""):
    """Google redirects here after consent; exchange then bounce to the web UI."""
    from app.oauth import exchange_code

    if error or not code:
        return RedirectResponse(f"{settings.web_origin}/?auth=error")
    try:
        await exchange_code(code, state)
    except Exception as e:
        logger.warning("OAuth callback failed", error=str(e))
        return RedirectResponse(f"{settings.web_origin}/?auth=error")
    return RedirectResponse(f"{settings.web_origin}/?auth=ok")


class ApiKeyBody(BaseModel):
    key: str


@app.post("/api/auth/key")
async def api_auth_key(body: ApiKeyBody):
    from app.oauth import save_api_key

    if not body.key.strip():
        raise HTTPException(400, "empty key")
    await save_api_key(body.key)
    return {"ok": True}


@app.post("/api/auth/disconnect")
async def api_auth_disconnect():
    from app.oauth import disconnect

    await disconnect()
    return {"ok": True}


@app.get("/api/profiles")
async def api_list_profiles():
    return [p.to_dict() for p in await store.list_profiles()]


@app.get("/api/profiles/presets")
async def api_presets():
    return PROMPT_PRESETS


@app.get("/api/voices")
async def api_voices():
    from app.models import VOICE_OPTIONS

    return VOICE_OPTIONS


@app.post("/api/profiles")
async def api_create_profile(body: ProfileCreate):
    prof = await store.create_profile(
        display_name=body.display_name,
        voice_id=body.voice_id,
        role_tag=body.role_tag,
        system_prompt=body.system_prompt,
        orb_style=body.orb_style,
    )
    return prof.to_dict()


@app.delete("/api/profiles/{profile_id}")
async def api_delete_profile(profile_id: str):
    prof = await store.delete_profile(profile_id)
    if prof is None:
        from fastapi import HTTPException

        raise HTTPException(404, "profile not found")
    return {"ok": True, "deleted": profile_id}


@app.get("/api/profiles/active")
async def api_active_profile():
    return (await store.get_active_profile()).to_dict()


@app.post("/api/profiles/{profile_id}/activate")
async def api_activate_profile(profile_id: str):
    prof = await store.set_active_profile(profile_id)
    if prof is None:
        from fastapi import HTTPException

        raise HTTPException(404, "profile not found")
    return prof.to_dict()


@app.put("/api/profiles/{profile_id}")
async def api_update_profile(profile_id: str, body: ProfileUpdate):
    prof = await _require_profile(profile_id)
    data = body.model_dump(exclude_none=True)
    if "voice_id" in data:
        from app.models import VOICE_GEMINI_NAMES

        data["voice_id"] = data["voice_id"].upper()
        if data["voice_id"] not in VOICE_GEMINI_NAMES:
            data.pop("voice_id")
    for field, value in data.items():
        setattr(prof, field, value)
    prof.display_name = prof.display_name.strip()[:48] or prof.display_name
    prof.role_tag = prof.role_tag.strip()[:64]
    await store.save_profile(prof)
    return prof.to_dict()


@app.post("/api/profiles/{profile_id}/reset")
async def api_reset_profile(profile_id: str):
    prof = await store.reset_profile(profile_id)
    if prof is None:
        from fastapi import HTTPException

        raise HTTPException(404, "profile not found")
    return prof.to_dict()


@app.put("/api/profiles/{profile_id}/memory")
async def api_set_memory(profile_id: str, body: MemoryUpdate):
    prof = await _require_profile(profile_id)
    if body.mode == "append":
        from app.memory import apply_update

        new_text = apply_update(prof.memory_text, "append", body.memory_text)
    else:
        new_text = body.memory_text.strip()
    await store.update_profile_memory(profile_id, new_text)
    return {"ok": True}


@app.delete("/api/profiles/{profile_id}/memory")
async def api_clear_memory(profile_id: str):
    await _require_profile(profile_id)
    await store.update_profile_memory(profile_id, "")
    return {"ok": True}


@app.get("/api/sessions")
async def api_list_sessions(status: str = "", limit: int = 50):
    sessions = await store.list_sessions(limit=limit, status=status)
    return [s.to_dict() for s in sessions]


@app.post("/api/sessions")
async def api_create_session(body: SessionCreate):
    profile_id = body.profile_id or (await store.get_active_profile()).id
    await _require_profile(profile_id)
    s = await store.create_session(profile_id, title=body.title)
    return s.to_dict()


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str):
    s = await store.get_session(session_id)
    if s is None:
        from fastapi import HTTPException

        raise HTTPException(404, "session not found")
    messages = await store.get_messages(session_id)
    return s.to_dict(messages=messages)


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str):
    await store.delete_session(session_id)
    return {"ok": True}


@app.post("/api/chat")
async def api_chat(body: ChatRequest):
    """Headless chat turn: same instruction, tools and memory as the voice UI."""
    if not body.message.strip():
        return {"error": "empty message"}
    profile = (
        await _require_profile(body.profile_id)
        if body.profile_id
        else await store.get_active_profile()
    )
    session = await _get_or_create_session(body.session_id, profile.id)

    traces: list[dict] = []

    async def collect(payload: dict[str, Any]) -> None:
        if payload.get("type") == "tool_trace":
            traces.append(payload["entry"])

    agent_session = agent_mod.AgentSession(session, profile, emit=collect)
    # Seed in-memory transcript so continuation/memory see prior turns.
    agent_session.entries = await store.get_messages(session.id)
    agent_session._title_pending = False

    result = await agent_mod.chat_turn(agent_session, body.message)
    return {
        "session_id": session.id,
        "profile_id": profile.id,
        "text": result.get("text", ""),
        "traces": result.get("traces", traces),
        "error": result.get("error"),
    }


# ------------------------------------------------------------------ WS live


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """One browser live channel.

    Client -> server:
      JSON  {"type":"init","session_id":?,"profile_id":?}
            {"type":"start_voice"} / {"type":"stop_voice"}
            {"type":"chat","text":...}
            {"type":"set_profile","profile_id":...}
      binary PCM16 frames @ WEB_SAMPLE_RATE (while voice is on)

    Server -> client:
      JSON  {"type":"ready","session":{...},"profile":{...},"messages":[...]}
            {"type":"state","state":"LISTENING",...}
            {"type":"transcript","entry":{...}}          (final user/agent/tool)
            {"type":"transcript_partial","role":...,"text":...}
            {"type":"tool_trace","entry":{...}}
            {"type":"barge_in"} / {"type":"memory_updated"}
      binary PCM16 @ WEB_SAMPLE_RATE                     (agent voice)
    """
    await ws.accept()
    agent_session: Optional[agent_mod.AgentSession] = None
    voice: Optional[agent_mod.VoiceSession] = None
    send_lock = asyncio.Lock()

    async def emit(payload: dict[str, Any]) -> None:
        data = payload.get("data")
        try:
            async with send_lock:
                if isinstance(data, (bytes, bytearray)):
                    await ws.send_bytes(bytes(data))
                else:
                    await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    try:
        async for raw in _ws_iter(ws):
            if isinstance(raw, (bytes, bytearray)):
                if voice is not None:
                    await voice.send_audio(bytes(raw))
                continue

            try:
                msg = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            mtype = msg.get("type")

            if mtype == "init":
                profile = (
                    await store.get_profile(msg["profile_id"])
                    if msg.get("profile_id")
                    else await store.get_active_profile()
                )
                if profile is None:
                    profile = await store.get_active_profile()
                session = await _get_or_create_session(msg.get("session_id"), profile.id)
                agent_session = agent_mod.AgentSession(session, profile, emit=emit)
                agent_session.entries = await store.get_messages(session.id)
                agent_session._title_pending = not any(
                    e.role == TranscriptRole.USER for e in agent_session.entries
                )
                await emit(
                    {
                        "type": "ready",
                        "session": session.to_dict(),
                        "profile": profile.to_dict(),
                        "messages": [e.to_dict() for e in agent_session.entries],
                    }
                )

            elif mtype == "start_voice" and agent_session is not None:
                if voice is not None:
                    await voice.stop()
                voice = agent_mod.VoiceSession(agent_session)
                try:
                    await voice.start()
                except Exception as e:
                    logger.warning("Voice start failed", error=str(e))
                    await emit({"type": "state", "state": "ERROR", "error": str(e)})
                    voice = None

            elif mtype == "stop_voice":
                if voice is not None:
                    await voice.stop()
                    voice = None

            elif mtype == "chat" and agent_session is not None:
                asyncio.create_task(
                    agent_mod.chat_turn(agent_session, msg.get("text", ""), voice=voice)
                )

            elif mtype == "set_profile" and agent_session is not None:
                prof = await store.get_profile(msg.get("profile_id", ""))
                if prof is not None:
                    agent_session.profile = prof
                    await store.set_active_profile(prof.id)
                    if voice is not None:
                        await voice.stop()
                        voice = None
                    await emit({"type": "profile", "profile": prof.to_dict()})
                    await emit(
                        {
                            "type": "state",
                            "state": "STANDBY",
                            "notice": f"Профиль «{prof.display_name}» выбран — перезапустите голос",
                        }
                    )

            elif mtype == "ping":
                await emit({"type": "pong"})

    except WebSocketDisconnect:
        pass
    finally:
        if voice is not None:
            await voice.stop()


async def _ws_iter(ws: WebSocket):
    """Yield WS payloads: str for text frames, bytes for binary frames."""
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            raise WebSocketDisconnect()
        if msg.get("bytes") is not None:
            yield msg["bytes"]
        elif msg.get("text") is not None:
            yield msg["text"]


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
