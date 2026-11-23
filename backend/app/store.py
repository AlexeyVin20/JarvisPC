"""Persistence layer over Postgres: profiles, sessions, transcript messages."""

import time
from typing import Optional

import structlog

from app import db
from app.models import DialogueSession, Profile, TranscriptEntry, TranscriptRole
from app.presets import default_profiles

logger = structlog.get_logger(__name__)


def _row_to_profile(r) -> Profile:
    return Profile(
        id=r["id"],
        voice_id=r["voice_id"],
        display_name=r["display_name"],
        role_tag=r["role_tag"],
        system_prompt=r["system_prompt"],
        memory_text=r["memory_text"],
        enable_web_search=r["enable_web_search"],
        enable_memory=r["enable_memory"],
        enable_tasks=r["enable_tasks"],
        orb_style=r["orb_style"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


async def seed_defaults() -> None:
    """Insert the four built-in profiles on first run."""
    p = db.pool()
    async with p.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM profiles")
        if count:
            return
        now = time.time()
        for prof in default_profiles():
            await conn.execute(
                """INSERT INTO profiles (id, voice_id, display_name, role_tag,
                       system_prompt, memory_text, enable_web_search,
                       enable_memory, enable_tasks, orb_style, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,'',$6,$7,$8,$9,$10,$10)""",
                prof.id, prof.voice_id, prof.display_name, prof.role_tag,
                prof.system_prompt, prof.enable_web_search, prof.enable_memory,
                prof.enable_tasks, prof.orb_style, now,
            )
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('active_profile', 'FENRIR') "
            "ON CONFLICT (key) DO NOTHING"
        )
    logger.info("Seeded default profiles", count=4)


# ---------------------------------------------------------------- profiles

async def list_profiles() -> list[Profile]:
    rows = await db.pool().fetch("SELECT * FROM profiles ORDER BY id")
    return [_row_to_profile(r) for r in rows]


async def get_profile(profile_id: str) -> Optional[Profile]:
    r = await db.pool().fetchrow("SELECT * FROM profiles WHERE id = $1", profile_id)
    return _row_to_profile(r) if r else None


async def get_setting(key: str) -> str:
    return (await db.pool().fetchval("SELECT value FROM settings WHERE key = $1", key)) or ""


async def set_setting(key: str, value: str) -> None:
    if value == "":
        await db.pool().execute("DELETE FROM settings WHERE key = $1", key)
    else:
        await db.pool().execute(
            "INSERT INTO settings (key, value) VALUES ($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            key,
            value,
        )


async def get_active_profile() -> Profile:
    p = db.pool()
    active_id = await p.fetchval("SELECT value FROM settings WHERE key = 'active_profile'")
    prof = await get_profile(active_id) if active_id else None
    if prof is None:
        prof = await get_profile("FENRIR")
    if prof is None:  # DB freshly wiped — reseed
        await seed_defaults()
        prof = await get_profile("FENRIR")
    assert prof is not None
    return prof


async def set_active_profile(profile_id: str) -> Optional[Profile]:
    prof = await get_profile(profile_id)
    if prof is None:
        return None
    await db.pool().execute(
        "INSERT INTO settings (key, value) VALUES ('active_profile', $1) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        profile_id,
    )
    return prof


async def save_profile(prof: Profile) -> Profile:
    prof.updated_at = time.time()
    if not prof.created_at:
        prof.created_at = prof.updated_at
    await db.pool().execute(
        """INSERT INTO profiles (id, voice_id, display_name, role_tag,
               system_prompt, memory_text, enable_web_search, enable_memory,
               enable_tasks, orb_style, created_at, updated_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
           ON CONFLICT (id) DO UPDATE SET
               voice_id = EXCLUDED.voice_id,
               display_name = EXCLUDED.display_name,
               role_tag = EXCLUDED.role_tag,
               system_prompt = EXCLUDED.system_prompt,
               memory_text = EXCLUDED.memory_text,
               enable_web_search = EXCLUDED.enable_web_search,
               enable_memory = EXCLUDED.enable_memory,
               enable_tasks = EXCLUDED.enable_tasks,
               orb_style = EXCLUDED.orb_style,
               updated_at = EXCLUDED.updated_at""",
        prof.id, prof.voice_id, prof.display_name, prof.role_tag,
        prof.system_prompt, prof.memory_text, prof.enable_web_search,
        prof.enable_memory, prof.enable_tasks, prof.orb_style,
        prof.created_at, prof.updated_at,
    )
    return prof


async def update_profile_memory(profile_id: str, memory_text: str) -> None:
    await db.pool().execute(
        "UPDATE profiles SET memory_text = $2, updated_at = $3 WHERE id = $1",
        profile_id, memory_text, time.time(),
    )


async def create_profile(
    display_name: str,
    voice_id: str,
    role_tag: str = "",
    system_prompt: str = "",
    orb_style: str = "sphere",
) -> Profile:
    """Create a user-defined persona profile (own id, selectable voice)."""
    import uuid

    from app.models import VOICE_GEMINI_NAMES
    from app.presets import custom_prompt

    voice_id = voice_id.upper()
    if voice_id not in VOICE_GEMINI_NAMES:
        voice_id = "FENRIR"
    name = display_name.strip()[:48] or "Ассистент"
    prof = Profile(
        id=uuid.uuid4().hex[:12].upper(),
        voice_id=voice_id,
        display_name=name,
        role_tag=role_tag.strip()[:64],
        system_prompt=system_prompt.strip() or custom_prompt(name, role_tag.strip()),
        orb_style=orb_style,
    )
    prof.created_at = prof.updated_at = time.time()
    return await save_profile(prof)


async def delete_profile(profile_id: str) -> Optional[Profile]:
    """Delete a profile and its sessions (FK cascade)."""
    prof = await get_profile(profile_id)
    if prof is None:
        return None
    await db.pool().execute("DELETE FROM profiles WHERE id = $1", profile_id)
    # If the deleted profile was active, fall back to Fenrir (or first left).
    active = await db.pool().fetchval(
        "SELECT value FROM settings WHERE key = 'active_profile'"
    )
    if active == profile_id:
        fallback = await get_profile("FENRIR")
        if fallback is None:
            rows = await db.pool().fetch("SELECT id FROM profiles LIMIT 1")
            fallback_id = rows[0]["id"] if rows else None
        else:
            fallback_id = fallback.id
        if fallback_id:
            await set_active_profile(fallback_id)
    return prof


async def reset_profile(profile_id: str) -> Optional[Profile]:
    """Reset a profile to its built-in default, keeping its memory (VoxRelay behavior)."""
    current = await get_profile(profile_id)
    if current is None:
        return None
    default = {p.id: p for p in default_profiles()}.get(profile_id)
    if default is None:
        return None
    default.memory_text = current.memory_text
    default.created_at = current.created_at or time.time()
    return await save_profile(default)


# ---------------------------------------------------------------- sessions

def _row_to_session(r) -> DialogueSession:
    return DialogueSession(
        id=r["id"],
        profile_id=r["profile_id"],
        title=r["title"],
        summary=r["summary"],
        status=r["status"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


async def create_session(profile_id: str, title: str = "") -> DialogueSession:
    s = DialogueSession(profile_id=profile_id, title=title)
    await db.pool().execute(
        """INSERT INTO sessions (id, profile_id, title, summary, status, created_at, updated_at)
           VALUES ($1,$2,$3,'','active',$4,$4)""",
        s.id, s.profile_id, s.title, s.created_at,
    )
    return s


async def ensure_session(s: DialogueSession) -> DialogueSession:
    """Materialize a session row if absent (lazy persistence).

    Sessions are only written when the first transcript entry is recorded, so
    page reloads and empty WS connections don't leave phantom dialogs.
    """
    await db.pool().execute(
        """INSERT INTO sessions (id, profile_id, title, summary, status, created_at, updated_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (id) DO NOTHING""",
        s.id, s.profile_id, s.title, s.summary, s.status, s.created_at, s.updated_at,
    )
    return s


async def get_session(session_id: str) -> Optional[DialogueSession]:
    r = await db.pool().fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
    return _row_to_session(r) if r else None


async def list_sessions(limit: int = 50, status: str = "active") -> list[DialogueSession]:
    rows = await db.pool().fetch(
        """SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS n
           FROM sessions s WHERE ($1 = '' OR s.status = $1)
           ORDER BY s.updated_at DESC LIMIT $2""",
        status, limit,
    )
    return [_row_to_session(r) for r in rows]


async def touch_session(session_id: str, title: Optional[str] = None) -> None:
    if title:
        await db.pool().execute(
            "UPDATE sessions SET updated_at = $2, title = $3 WHERE id = $1 AND title = ''",
            session_id, time.time(), title,
        )
    await db.pool().execute(
        "UPDATE sessions SET updated_at = $2 WHERE id = $1", session_id, time.time()
    )


async def set_session_status(session_id: str, status: str) -> None:
    await db.pool().execute(
        "UPDATE sessions SET status = $2, updated_at = $3 WHERE id = $1",
        session_id, status, time.time(),
    )


async def delete_session(session_id: str) -> None:
    await db.pool().execute("DELETE FROM sessions WHERE id = $1", session_id)


# ---------------------------------------------------------------- messages

async def append_message(session_id: str, entry: TranscriptEntry) -> None:
    await db.pool().execute(
        """INSERT INTO messages (session_id, entry_id, role, tool_name, text, ts)
           VALUES ($1,$2,$3,$4,$5,$6)""",
        session_id, entry.id, entry.role.name, entry.tool_name, entry.text, entry.timestamp,
    )


async def get_messages(session_id: str, limit: int = 500) -> list[TranscriptEntry]:
    rows = await db.pool().fetch(
        "SELECT * FROM messages WHERE session_id = $1 ORDER BY ts LIMIT $2",
        session_id, limit,
    )
    return [
        TranscriptEntry(
            id=r["entry_id"],
            role=TranscriptRole.__members__.get(r["role"], TranscriptRole.SYSTEM),
            tool_name=r["tool_name"],
            text=r["text"],
            timestamp=r["ts"],
        )
        for r in rows
    ]


async def session_message_count(session_id: str) -> int:
    return await db.pool().fetchval(
        "SELECT COUNT(*) FROM messages WHERE session_id = $1", session_id
    )
