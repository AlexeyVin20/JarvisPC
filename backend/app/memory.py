"""Long-term persona memory — port of VoxRelay's semi-automatic memory.

Two mechanisms, same as the Android app:
1. The model's ``update_memory`` tool (append/replace, 4000-token cap).
2. A background extractor: after each completed turn a cheap text model
   reviews the last few transcript lines and decides whether a new fact about
   the user/project/situation is worth saving — without asking.
"""

from typing import Any, Optional

import structlog

from app.config import settings
from app.gemini.text import generate_content
from app.models import MAX_MEMORY_CHARS, MAX_MEMORY_TOKENS, Profile

logger = structlog.get_logger(__name__)


def apply_update(memory_text: str, operation: str, content: str) -> str:
    """Apply an append/replace memory update (port of onUpdateMemory)."""
    addition = content.strip()
    if operation.lower() == "replace":
        return addition[:MAX_MEMORY_CHARS]

    existing = memory_text.strip()
    combined = f"- {addition}" if not existing else f"{existing}\n- {addition}"
    if len(combined) <= MAX_MEMORY_CHARS:
        return combined

    # Drop oldest lines from the top until within the cap.
    lines = combined.splitlines()
    while len(lines) > 1 and len("\n".join(lines)) > MAX_MEMORY_CHARS:
        lines.pop(0)
    return "\n".join(lines)[-MAX_MEMORY_CHARS:]


_MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "should_save": {
            "type": "boolean",
            "description": (
                "true, если в диалоге есть новый важный факт о проекте, ситуации, "
                "цели, предпочтении или интересной теме пользователя, которого ещё нет в памяти"
            ),
        },
        "operation": {
            "type": "string",
            "enum": ["append", "replace"],
            "description": (
                "Обычно append; replace — только если память переполнена и требует "
                "компактного переписывания"
            ),
        },
        "fact": {
            "type": "string",
            "description": (
                "1–2 кратких структурированных пункта на русском языке для записи "
                "в память (или пусто, если should_save=false)"
            ),
        },
    },
    "required": ["should_save", "operation", "fact"],
}


async def extract_from_dialogue(profile: Profile, recent_dialogue: str) -> Optional[dict[str, Any]]:
    """VoxRelay's extractMemoryFromConversation — background save decision."""
    if not profile.enable_memory or not recent_dialogue.strip():
        return None
    prompt = f"""Ты — тихий фоновый модуль полуавтоматической памяти для персоны «{profile.display_name}».
Проанализируй свежий фрагмент диалога и реши, появилось ли в нём что-то важное о пользователе, что стоит запомнить автоматически без спроса:
- проект, над которым он работает, идеи, стек, задачи
- жизненная или рабочая ситуация, планы, события
- личные предпочтения, вкусы, стиль общения, увлечения
- важная или интересная тема, к которой стоит вернуться позже

НЕ сохраняй пустую болтовню («привет», «ок», «как дела», разовые запросы погоды) и НЕ дублируй то, что уже есть в текущей памяти.
Текущая память (~{profile.estimated_tokens}/{MAX_MEMORY_TOKENS} токенов):
{profile.memory_text or "(пусто)"}

Свежий фрагмент диалога:
{recent_dialogue}"""
    try:
        import json

        data = await generate_content(
            settings.memory_model,
            [{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={
                "responseMimeType": "application/json",
                "responseSchema": _MEMORY_SCHEMA,
                "temperature": 0.2,
            },
            timeout=30.0,
        )
        from app.gemini.text import extract_text

        raw = extract_text(data)
        if not raw:
            return None
        parsed = json.loads(raw)
        if (
            parsed.get("should_save")
            and len(str(parsed.get("fact", "")).strip()) >= 6
        ):
            op = parsed.get("operation") if parsed.get("operation") in ("append", "replace") else "append"
            return {"should_save": True, "operation": op, "fact": str(parsed["fact"]).strip()}
        return None
    except Exception as e:
        logger.info("Auto memory extraction skipped", error=str(e))
        return None
