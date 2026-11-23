"""Async voice-facing wrapper around the vendored web-search pipeline.

``run_pipeline`` is synchronous and calls ``asyncio.run`` internally, so it
must be executed in a worker thread via ``asyncio.to_thread``.
"""

import asyncio
import time
from typing import Any

import structlog

from .config import CONFIG
from .pipeline import run_pipeline

logger = structlog.get_logger(__name__)

# Token budget passed to run_pipeline (~4 chars/token); keeps the voice answer
# short and within a single response turn.
MAX_CONTEXT_TOKENS = 900

# Below this many remaining chars a leftover passage is dropped entirely —
# a tiny fragment carries no usable information for a spoken answer.
_MIN_FRAGMENT_CHARS = 200


def _truncate_at_sentence(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` chars on a sentence/line boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n", "\n", " "):
        idx = cut.rfind(sep)
        if idx >= limit // 3:
            return cut[: idx + 1].rstrip()
    return cut.rstrip()


def _empty_result(query: str, result: dict[str, Any], latency_ms: float) -> dict[str, Any]:
    """Build the response for a pipeline run that produced no passages."""
    stats = result.get("stats") or {}
    if stats.get("snippets_found", 0) == 0:
        message = (
            "The search engine returned no results — the local 4get service "
            "may be unreachable. Tell the caller you could not search the web."
        )
    else:
        message = "Search results were found but no relevant passages could be extracted."
    return {
        "status": "empty",
        "query": query,
        "fallback_mode": result.get("fallback_mode"),
        "passages": [],
        "message": message,
        "latency_ms": latency_ms,
    }


async def web_search(
    query: str,
    *,
    max_chars: int = 3500,
    top_urls: int = 4,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Run the full web-search pipeline and return compact voice-ready passages.

    Never raises: any failure is reported as ``{"status": "error", ...}``.

    Args:
        query: Natural-language search query.
        max_chars: Total character budget across all returned passages.
        top_urls: How many diverse result URLs to fetch and extract.
        endpoint: 4get endpoint override (defaults to WEBSEARCH_ENDPOINT env).

    Returns:
        Dict with ``status`` (``"ok"``/``"empty"``/``"error"``), ``query``,
        ``fallback_mode``, ``passages`` (list of ``text``/``source``/``title``)
        and ``latency_ms``.
    """
    query = (query or "").strip()
    if not query:
        return {
            "status": "error",
            "query": query,
            "message": "Empty search query.",
            "passages": [],
            "latency_ms": 0.0,
        }

    endpoint = endpoint or CONFIG["search"]["endpoint"]
    t0 = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            run_pipeline,
            query,
            top_urls=top_urls,
            search_endpoint=endpoint,
            max_context_tokens=MAX_CONTEXT_TOKENS,
        )
    except Exception as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.warning("web_search pipeline failed", query=query, error=str(e))
        return {
            "status": "error",
            "query": query,
            "message": f"Web search failed: {e}",
            "passages": [],
            "latency_ms": latency_ms,
        }

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    if not result.get("passages"):
        return _empty_result(query, result, latency_ms)

    # Keep best-ranked passages first (run_pipeline sorts by score desc) and
    # trim the total to max_chars on passage/sentence boundaries.
    passages: list[dict[str, str]] = []
    total = 0
    for p in result["passages"]:
        text = (getattr(p, "text", "") or "").strip()
        if not text:
            continue
        remaining = max_chars - total
        if remaining < _MIN_FRAGMENT_CHARS and passages:
            break
        if len(text) > remaining:
            text = _truncate_at_sentence(text, remaining)
        if not text:
            break
        passages.append(
            {
                "text": text,
                "source": getattr(p, "url", "") or "",
                "title": getattr(p, "header", "") or "",
            }
        )
        total += len(text)
        if total >= max_chars:
            break

    return {
        "status": "ok",
        "query": query,
        "fallback_mode": result.get("fallback_mode"),
        "passages": passages,
        "latency_ms": latency_ms,
    }
