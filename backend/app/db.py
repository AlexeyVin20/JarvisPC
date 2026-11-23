"""PostgreSQL connection pool and schema bootstrap (asyncpg).

Schema: one row per persona profile, dialogue sessions, and transcript
messages — the Postgres counterpart of VoxRelay's Firestore layout
(users/{uid}/profiles, users/{uid}/sessions + messages).
"""

import asyncpg
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id                 TEXT PRIMARY KEY,          -- voice id: FENRIR/KORE/PUCK/AOEDE
    voice_id           TEXT NOT NULL,
    display_name       TEXT NOT NULL,
    role_tag           TEXT NOT NULL DEFAULT '',
    system_prompt      TEXT NOT NULL DEFAULT '',
    memory_text        TEXT NOT NULL DEFAULT '',
    enable_web_search  BOOLEAN NOT NULL DEFAULT TRUE,
    enable_memory      BOOLEAN NOT NULL DEFAULT TRUE,
    enable_tasks       BOOLEAN NOT NULL DEFAULT TRUE,
    orb_style          TEXT NOT NULL DEFAULT 'sphere',
    created_at         DOUBLE PRECISION NOT NULL,
    updated_at         DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  DOUBLE PRECISION NOT NULL,
    updated_at  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    entry_id    TEXT NOT NULL,
    role        TEXT NOT NULL,               -- USER | AGENT | TOOL | SYSTEM
    tool_name   TEXT,
    text        TEXT NOT NULL,
    ts          DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, ts);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=8)
        async with _pool.acquire() as conn:
            await conn.execute(SCHEMA)
        logger.info("Postgres connected", dsn=settings.database_url.split("@")[-1])
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    assert _pool is not None, "DB pool not initialised"
    return _pool
