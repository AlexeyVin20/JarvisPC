"""update_memory tool — port of VoxRelay's semi-automatic memory tool."""

from typing import Any

from app import memory as memory_mod
from app import store
from app.models import MAX_MEMORY_TOKENS, estimate_memory_tokens
from app.tools.registry import ToolContext, ToolSpec, register, _str_arg

DECLARATION = {
    "name": "update_memory",
    "description": (
        "ПОЛУАВТОМАТИЧЕСКАЯ ПАМЯТЬ (лимит 4000 токенов). Вызывай ПРОАКТИВНО БЕЗ "
        "СПРОСА каждый раз, когда пользователь обсуждает свой проект, жизненную "
        "или рабочую ситуацию, планы, предпочтения или важную интересную тему. "
        "Используй 'append' для добавления фактов и 'replace' для сжатия/"
        "переработки памяти."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["append", "replace"],
                "description": "append (добавить новый факт) или replace (перезаписать всю память компактнее)",
            },
            "content": {
                "type": "string",
                "description": "Сжатый, чёткий факт о пользователе, проекте, ситуации или теме",
            },
        },
        "required": ["operation", "content"],
    },
}


async def handle(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    profile = ctx.profile
    if not profile.enable_memory:
        return {"status": "error", "message": f"Память отключена для профиля «{profile.display_name}»."}

    operation = _str_arg(args, "operation") or "append"
    content = _str_arg(args, "content")
    if not content:
        return {"status": "error", "message": "Пустой текст для обновления памяти."}

    updated = memory_mod.apply_update(profile.memory_text, operation, content)
    await store.update_profile_memory(profile.id, updated)
    profile.memory_text = updated  # keep the in-session copy fresh

    tokens = estimate_memory_tokens(updated)
    op_label = "Перезаписана" if operation.lower() == "replace" else "Дополнена"
    summary = f"{op_label} память «{profile.display_name}» (~{tokens} / {MAX_MEMORY_TOKENS} ток.)"
    return {"status": "ok", "summary": summary, "memory_tokens": tokens}


register(
    ToolSpec(
        name="update_memory",
        declaration=DECLARATION,
        handler=handle,
        enabled_for=lambda p: p.enable_memory,
    )
)
