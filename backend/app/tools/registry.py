"""Tool registry — the plugin point for agent skills.

Each tool = a Gemini functionDeclaration + an async handler + a profile flag
that gates it. Adding the future Devin/ACP task tools means registering more
specs here (gated on ``profile.enable_tasks``); no other code changes needed.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from app.models import Profile

ToolHandler = Callable[[dict[str, Any], "ToolContext"], Awaitable[dict[str, Any]]]


@dataclass
class ToolContext:
    """Everything a tool handler needs about the running session."""

    profile: Profile
    session_id: str
    user_id: str = "local"
    # Trace callback (name, summary) -> shown in UI and persisted as TOOL line
    trace: Optional[Callable[[str, str], Awaitable[None]]] = None
    # Completion callback for background tools (ACP tasks): persists a TOOL
    # line and, when a voice session is live, makes the agent speak the text.
    notify: Optional[Callable[[str], Awaitable[None]]] = None
    # Last user utterance — tools like memory/search use it as fallback query
    last_user_utterance: str = ""


@dataclass
class ToolSpec:
    name: str
    declaration: dict[str, Any]
    handler: ToolHandler
    enabled_for: Callable[[Profile], bool]


_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    _REGISTRY[spec.name] = spec


def declarations_for(profile: Profile) -> list[dict[str, Any]]:
    """functionDeclarations list for the Gemini setup/generateContent call."""
    return [s.declaration for s in _REGISTRY.values() if s.enabled_for(profile)]


async def execute(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    spec = _REGISTRY.get(name)
    if spec is None or not spec.enabled_for(ctx.profile):
        return {"status": "error", "message": f"Unknown or disabled tool: {name}"}
    return await spec.handler(args, ctx)


def _str_arg(args: dict[str, Any], key: str) -> str:
    val = args.get(key)
    return str(val).strip() if val is not None else ""
