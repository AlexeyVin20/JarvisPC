"""Gemini generateContent REST client (non-Live).

Used for:
- headless / text chat turns with function-calling loop (web chat, REST API,
  CLI — same tools as the voice channel)
- the semi-automatic memory extractor (JSON-schema response)

No SDK dependency — plain HTTPS via httpx, mirroring the Kotlin calls in
VoxRelay (which went through Firebase AI to the same endpoints).
"""

from typing import Any, Awaitable, Callable, Optional

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class GeminiError(Exception):
    pass


async def generate_content(
    model: str,
    contents: list[dict[str, Any]],
    *,
    system_instruction: Optional[str] = None,
    tools: Optional[list[dict[str, Any]]] = None,
    generation_config: Optional[dict[str, Any]] = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Single generateContent call. Returns the parsed response JSON."""
    from app.oauth import gemini_auth

    auth = await gemini_auth()
    if auth is None:
        raise GeminiError(
            "Gemini credentials are not configured — set GEMINI_API_KEY or sign in with Google"
        )

    body: dict[str, Any] = {"contents": contents}
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    if generation_config:
        body["generationConfig"] = generation_config

    url = f"{API_BASE}/{model}:generateContent"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, **auth)
    if resp.status_code != 200:
        raise GeminiError(f"Gemini {model} HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "error" in data:
        raise GeminiError(f"Gemini {model} error: {data['error'].get('message', data['error'])}")
    return data


def _candidate_parts(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = data.get("candidates") or []
    if not candidates:
        return []
    return (candidates[0].get("content") or {}).get("parts") or []


def extract_text(data: dict[str, Any]) -> str:
    return "".join(p.get("text", "") for p in _candidate_parts(data)).strip()


async def run_chat_turn(
    history: list[dict[str, Any]],
    user_text: str,
    *,
    system_instruction: str,
    tools: list[dict[str, Any]],
    tool_executor: Optional[ToolExecutor] = None,
    model: Optional[str] = None,
    max_tool_rounds: int = 6,
) -> dict[str, Any]:
    """One chat turn: append user text, run the function-calling loop.

    ``history`` is the REST-format contents list (mutated in place): user and
    model turns are appended so the caller can persist/reuse it.

    Returns {"text": str, "traces": [{name, summary}], "contents_added": int}.
    """
    model = model or settings.text_model
    contents = history
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    added = 1
    traces: list[dict[str, str]] = []

    for _round in range(max_tool_rounds + 1):
        data = await generate_content(
            model,
            contents,
            system_instruction=system_instruction,
            tools=tools or None,
        )
        parts = _candidate_parts(data)
        if not parts:
            return {"text": "", "traces": traces, "contents_added": added, "finish": "empty"}

        contents.append({"role": "model", "parts": parts})
        added += 1

        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not calls:
            return {
                "text": "".join(p.get("text", "") for p in parts).strip(),
                "traces": traces,
                "contents_added": added,
                "finish": "stop",
            }

        # Execute every requested call, send all responses as one user turn.
        response_parts = []
        for call in calls:
            name = call.get("name", "")
            args = call.get("args") or {}
            if tool_executor is None:
                result: dict[str, Any] = {"error": "no tool executor"}
            else:
                try:
                    result = await tool_executor(name, args)
                except Exception as e:
                    logger.warning("Tool executor failed", name=name, error=str(e))
                    result = {"error": str(e)}
            if not isinstance(result, dict):
                result = {"value": result}
            summary = str(result.get("summary") or result.get("status") or "")[:160]
            traces.append({"name": name, "summary": summary})
            response_parts.append(
                {"functionResponse": {"name": name, "response": result}}
            )
        contents.append({"role": "user", "parts": response_parts})
        added += 1

    return {"text": "", "traces": traces, "contents_added": added, "finish": "tool_rounds_exceeded"}
