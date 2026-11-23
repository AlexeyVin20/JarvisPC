"""Google sign-in (OAuth 2.0) and runtime Gemini credential resolution.

VoxRelay signs the user in with a Google account through Firebase; here the
equivalent is a direct OAuth 2.0 flow with the ``generative-language`` scope —
the consent grants this app access to the Gemini API on the user's behalf,
no manually copied API key required.

Credential priority (same for REST and Live WS):
1. ``GEMINI_API_KEY`` from the environment / .env
2. a key pasted in the UI (stored in Postgres ``settings``)
3. a Google OAuth access token, refreshed automatically

The OAuth client id/secret come from ``GOOGLE_OAUTH_CLIENT_ID`` /
``GOOGLE_OAUTH_CLIENT_SECRET`` (.env). For a "Desktop app" client Google treats
the secret as public — it is required in the token exchange, not confidential.
"""

import json
import secrets
import time
from typing import Any, Optional

import httpx
import structlog

from app import store
from app.config import settings

logger = structlog.get_logger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"



# In-memory CSRF states: single-user local app, fine to keep in process.
_states: dict[str, float] = {}
_STATE_TTL = 600.0

K_OAUTH_REFRESH = "oauth_refresh_token"
K_OAUTH_ACCESS = "oauth_access_token"
K_OAUTH_EXPIRES = "oauth_expires_at"
K_OAUTH_EMAIL = "oauth_email"
K_STORED_KEY = "stored_api_key"


def oauth_configured() -> bool:
    return bool(settings.google_oauth_client_id)


def build_auth_url() -> tuple[str, str]:
    """(authorize_url, state). Caller redirects the user to the URL."""
    state = secrets.token_urlsafe(16)
    _states[state] = time.time()
    for s, ts in list(_states.items()):  # GC
        if time.time() - ts > _STATE_TTL:
            _states.pop(s, None)
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": settings.oauth_scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    from urllib.parse import urlencode

    return f"{AUTHORIZE_URL}?{urlencode(params)}", state


async def exchange_code(code: str, state: str) -> Optional[str]:
    """Swap the code for tokens, persist them, return the account email."""
    ts = _states.pop(state, None)
    if ts is None or time.time() - ts > _STATE_TTL:
        raise ValueError("invalid or expired oauth state")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if resp.status_code != 200:
            raise ValueError(f"token exchange failed: HTTP {resp.status_code} {resp.text[:200]}")
        tok = resp.json()

        await store.set_setting(K_OAUTH_ACCESS, tok.get("access_token", ""))
        await store.set_setting(
            K_OAUTH_EXPIRES, str(time.time() + int(tok.get("expires_in", 3600)))
        )
        if tok.get("refresh_token"):
            await store.set_setting(K_OAUTH_REFRESH, tok["refresh_token"])

        email = ""
        try:
            ui = await client.get(
                USERINFO_URL, headers={"Authorization": f"Bearer {tok['access_token']}"}
            )
            if ui.status_code == 200:
                email = ui.json().get("email", "")
        except Exception:
            pass
        await store.set_setting(K_OAUTH_EMAIL, email)
    logger.info("Google account connected", email=email or "?")
    return email or None


async def get_access_token() -> Optional[str]:
    """Valid OAuth access token, refreshing when needed. None if not signed in."""
    refresh = await store.get_setting(K_OAUTH_REFRESH)
    if not refresh:
        return None
    token = await store.get_setting(K_OAUTH_ACCESS)
    try:
        expires = float(await store.get_setting(K_OAUTH_EXPIRES) or 0)
    except ValueError:
        expires = 0
    if token and expires - 90 > time.time():
        return token
    if not oauth_configured():
        return None
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code != 200:
        logger.warning("OAuth refresh failed", status=resp.status_code)
        return None
    tok = resp.json()
    token = tok.get("access_token", "")
    await store.set_setting(K_OAUTH_ACCESS, token)
    await store.set_setting(
        K_OAUTH_EXPIRES, str(time.time() + int(tok.get("expires_in", 3600)))
    )
    return token or None


async def gemini_auth() -> Optional[dict[str, Any]]:
    """httpx kwargs authenticating a generateContent call (key param or bearer)."""
    key = settings.gemini_api_key or await store.get_setting(K_STORED_KEY)
    if key:
        return {"params": {"key": key}}
    token = await get_access_token()
    if token:
        return {"headers": {"Authorization": f"Bearer {token}"}}
    return None


async def gemini_ws_auth() -> tuple[str, dict[str, str]]:
    """(url_query_suffix, extra_headers) for the Gemini Live WebSocket."""
    key = settings.gemini_api_key or await store.get_setting(K_STORED_KEY)
    if key:
        return f"?key={key}", {}
    token = await get_access_token()
    if token:
        return "", {"Authorization": f"Bearer {token}"}
    raise ValueError(
        "Gemini credentials not configured — set GEMINI_API_KEY or sign in with Google"
    )


async def auth_status() -> dict[str, Any]:
    """Which credential is active, for the UI."""
    if settings.gemini_api_key:
        return {"method": "env_key", "email": None, "oauth_ready": oauth_configured()}
    if await store.get_setting(K_STORED_KEY):
        return {"method": "stored_key", "email": None, "oauth_ready": oauth_configured()}
    if await store.get_setting(K_OAUTH_REFRESH):
        email = await store.get_setting(K_OAUTH_EMAIL)
        return {"method": "oauth", "email": email or None, "oauth_ready": oauth_configured()}
    return {"method": None, "email": None, "oauth_ready": oauth_configured()}


async def save_api_key(key: str) -> None:
    await store.set_setting(K_STORED_KEY, key.strip())


async def disconnect() -> None:
    """Sign out of Google and forget the stored key."""
    for k in (K_OAUTH_REFRESH, K_OAUTH_ACCESS, K_OAUTH_EXPIRES, K_OAUTH_EMAIL, K_STORED_KEY):
        await store.set_setting(k, "")
