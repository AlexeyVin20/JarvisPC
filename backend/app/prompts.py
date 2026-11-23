"""System-instruction builder — 1:1 port of VoxRelay's
``buildEffectiveSystemInstruction``.

Assembles: persona line + profile system prompt + active-tools line +
memory block + continuation context.
"""

from app.models import MAX_MEMORY_TOKENS, Profile, TranscriptEntry, TranscriptRole

CONTINUATION_ENTRIES = 12


def tool_names_for(profile: Profile) -> list[str]:
    names = []
    if profile.enable_web_search:
        names.append("web_search (локальный метапоиск 4get + извлечение контекста)")
    if profile.enable_memory:
        names.append(f"update_memory (полуавтоматическая память до {MAX_MEMORY_TOKENS} токенов)")
    # profile.enable_tasks -> Devin task tools plug in here later.
    return names


def build_system_instruction(
    profile: Profile,
    continuation_context: str = "",
    extra_sections: str = "",
) -> str:
    enabled = tool_names_for(profile)
    if not enabled:
        tools_line = "Инструменты отключены — ты просто свободный дружелюбный собеседник."
    else:
        search_rule = ""
        if profile.enable_web_search:
            search_rule = (
                " Для любых свежих новостей, фактов, цен, погоды, релизов и "
                "актуальной информации обязательно вызывай инструмент `web_search`."
            )
        tools_line = f"Активные инструменты этого профиля: {', '.join(enabled)}.{search_rule}"

    if profile.enable_memory:
        body = profile.memory_text.strip() or (
            "(память пока пуста — проактивно записывай важные проекты, ситуации, "
            "планы и темы через update_memory без спроса)"
        )
        memory_block = (
            f"Долговременная память профиля «{profile.display_name}» "
            f"(~{profile.estimated_tokens} / {MAX_MEMORY_TOKENS} токенов):\n{body}\n\n"
            "ВАЖНО ПО ПАМЯТИ (ПОЛУАВТОМАТИЧЕСКИЙ РЕЖИМ):\n"
            "Если пользователь рассказывает о своём проекте, задаче, жизненной "
            "ситуации, идее, предпочтениях или важной интересной теме, которой "
            "ещё нет в памяти выше — СРАЗУ вызывай "
            '`update_memory(operation="append", content="...")` без спроса и не '
            "дожидаясь команды «запомни». Продолжай разговор максимально естественно."
        )
    else:
        memory_block = "Память отключена для этого профиля."

    parts = [
        f"Активная персона: {profile.display_name} ({profile.role_tag} · голос {profile.gemini_voice}).",
        profile.system_prompt.strip(),
        "",
        tools_line,
        memory_block,
    ]
    if continuation_context.strip():
        parts += [
            "",
            "Контекст текущего диалога (учитывай историю и продолжай естественно):\n"
            + continuation_context.strip(),
        ]
    if extra_sections.strip():
        parts += ["", extra_sections.strip()]
    return "\n".join(parts).strip()


def continuation_context(entries: list[TranscriptEntry]) -> str:
    """VoxRelay's getDialogueContextForContinuation(): last N non-system lines."""
    meaningful = [e for e in entries if e.role != TranscriptRole.SYSTEM][-CONTINUATION_ENTRIES:]
    lines = []
    for e in meaningful:
        if e.role == TranscriptRole.USER:
            lines.append(f"Пользователь: {e.text}")
        elif e.role == TranscriptRole.AGENT:
            lines.append(f"Агент: {e.text}")
        elif e.role == TranscriptRole.TOOL:
            lines.append(f"Инструмент [{e.tool_name or 'tool'}]: {e.text}")
    return "\n".join(lines)


def session_title_from(entries: list[TranscriptEntry], fallback: str = "Диалог") -> str:
    """Short title from the first user utterance."""
    for e in entries:
        if e.role == TranscriptRole.USER and e.text.strip():
            return e.text.strip()[:60]
    return fallback
