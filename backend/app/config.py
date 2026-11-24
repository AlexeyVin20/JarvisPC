"""Runtime configuration for the Jarvis PC backend.

Values are read from environment variables; the project-root ``.env`` (next to
docker-compose.yml) and ``backend/.env`` are both loaded if present.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent

# Root .env first (shared with docker-compose), backend/.env can override.
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(_BACKEND_DIR / ".env", override=True)


@dataclass(frozen=True)
class Settings:
    # Gemini
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    live_model: str = field(default_factory=lambda: os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live"))
    text_model: str = field(default_factory=lambda: os.getenv("GEMINI_TEXT_MODEL", "gemini-3.8-flash"))
    memory_model: str = field(default_factory=lambda: os.getenv("GEMINI_MEMORY_MODEL", "gemini-3.8-flash"))

    # Database
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql://jarvis:jarvis@localhost:5433/jarvis"
        )
    )

    # HTTP/WebSocket server
    host: str = field(default_factory=lambda: os.getenv("JARVIS_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("JARVIS_PORT", "8787")))

    # Browser voice channel sample rate (Gemini native output is 24kHz)
    web_sample_rate: int = field(default_factory=lambda: int(os.getenv("WEB_SAMPLE_RATE", "24000")))

    # Web search pipeline (4get metasearch, see docker-compose.yml)
    websearch_endpoint: str = field(
        default_factory=lambda: os.getenv("WEBSEARCH_ENDPOINT", "http://localhost/web")
    )

    # ACP coding agent (local Cursor/Devin CLI over Agent Client Protocol).
    # ACP_AGENT_CMD is spawned per task: "cursor-agent acp", "agent acp",
    # "devin acp --model swe-2", "gemini --acp", a full .exe path, ...
    acp_agent_cmd: str = field(
        default_factory=lambda: os.getenv("ACP_AGENT_CMD", "cursor-agent acp")
    )
    # Default project dir for tasks when the tool call doesn't pass project_dir
    acp_default_cwd: str = field(default_factory=lambda: os.getenv("ACP_DEFAULT_CWD", ""))
    # authenticate meta.api_key (Devin cog_... key); empty = rely on CLI login
    acp_api_key: str = field(default_factory=lambda: os.getenv("ACP_API_KEY", ""))
    # Force an auth methodId instead of the first advertised one
    acp_auth_method: str = field(default_factory=lambda: os.getenv("ACP_AUTH_METHOD", ""))
    # Auto-answer for session/request_permission: allow_once|allow_always|reject
    acp_permission: str = field(
        default_factory=lambda: os.getenv("ACP_PERMISSION", "allow_once")
    )
    # session/prompt timeout — coding turns run long
    acp_prompt_timeout: float = field(
        default_factory=lambda: float(os.getenv("ACP_PROMPT_TIMEOUT_SEC", "1800"))
    )

    # Google OAuth sign-in (Gemini API access without a manual key)
    google_oauth_client_id: str = field(
        default_factory=lambda: os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    )
    google_oauth_client_secret: str = field(
        default_factory=lambda: os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    )
    oauth_redirect_uri: str = field(
        default_factory=lambda: os.getenv(
            "OAUTH_REDIRECT_URI", "http://localhost:8787/api/auth/google/callback"
        )
    )
    oauth_scopes: str = field(
        default_factory=lambda: os.getenv(
            "OAUTH_SCOPES",
            "https://www.googleapis.com/auth/generative-language openid email",
        )
    )

    # Where the OAuth callback redirects the browser after sign-in
    web_origin: str = field(default_factory=lambda: os.getenv("WEB_ORIGIN", "http://localhost:3000"))

    # Frontend origin(s) allowed to call the API (Next.js dev server)
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in os.getenv(
                "JARVIS_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(",")
            if o.strip()
        )
    )


settings = Settings()
