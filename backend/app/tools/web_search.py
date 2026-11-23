"""web_search tool — wraps the vendored 4get pipeline from the PC VoiceAgent."""

from typing import Any

import structlog

from app.config import settings
from app.tools.registry import ToolContext, ToolSpec, register, _str_arg
from app.websearch.search import web_search as run_search

logger = structlog.get_logger(__name__)

DECLARATION = {
    "name": "web_search",
    "description": (
        "ОБЯЗАТЕЛЬНО вызывай для актуального поиска в интернете (свежие новости, "
        "курсы, погода, даты, релизы, факты, документация, обзоры, события 2025-2026). "
        "Поиск идёт через локальный метапоиск 4get и занимает 2–5 секунд."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Чёткий поисковый запрос на русском или английском языке",
            }
        },
        "required": ["query"],
    },
}

MAX_PASSAGES_IN_ANSWER = 4


async def handle(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    query = _str_arg(args, "query") or ctx.last_user_utterance
    if not query:
        return {"status": "error", "message": "Пустой поисковый запрос."}

    result = await run_search(query, endpoint=settings.websearch_endpoint)

    if result.get("status") != "ok":
        message = result.get("message") or "Поиск не вернул результатов."
        if result.get("status") == "empty" and result.get("passages") == []:
            message += " (возможно, локальный 4get не запущен — docker compose up -d)"
        return {"status": result.get("status", "error"), "query": query, "message": message}

    passages = result["passages"][:MAX_PASSAGES_IN_ANSWER]
    parts = [p["text"] for p in passages]
    sources = [p["source"] for p in passages if p.get("source")]
    text = "\n\n".join(parts)
    if sources:
        text += "\n\nИсточники: " + " · ".join(sources[:3])
    return {
        "status": "ok",
        "query": query,
        "result": text,
        "latency_ms": result.get("latency_ms"),
    }


register(
    ToolSpec(
        name="web_search",
        declaration=DECLARATION,
        handler=handle,
        enabled_for=lambda p: p.enable_web_search,
    )
)
