"""ACP coding-task tools — dispatch engineering tasks to a local agent CLI.

Voice-facing tools (VoxRelay's codingToolDeclarations, adapted for a PC agent
that talks to Cursor/Devin over ACP directly — no WS bridge). Dispatch is
fire-and-forget: the agent runs in the background and the completion event
comes back through ToolContext.notify (voice speaks it / transcript gets it).
"""

from typing import Any

from app.acp import acp_tasks
from app.tools.registry import ToolContext, ToolSpec, register, _str_arg

AGENT_LABEL = "кодинг-агент на этом ПК (Cursor/Devin по протоколу ACP)"

DISPATCH_DECLARATION = {
    "name": "dispatch_coding_task",
    "description": (
        f"Отправляет инженерную задачу {AGENT_LABEL}: написать/починить код, "
        "разобрать репозиторий, сделать фичу. Задача выполняется В ФОНЕ — "
        "сразу подтверди пользователю отправку, а итог придёт отдельным "
        "событием и будет озвучен. Не вызывай без явной просьбы пользователя."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Полные технические инструкции для кодинг-агента: что сделать, где, критерии готовности",
            },
            "project_dir": {
                "type": "string",
                "description": "Абсолютный путь к папке проекта на ПК (например C:\\dev\\myapp). Уточни у пользователя, если неизвестна.",
            },
            "title": {
                "type": "string",
                "description": "Короткое название задачи (до 80 символов)",
            },
        },
        "required": ["task"],
    },
}

STATUS_DECLARATION = {
    "name": "coding_task_status",
    "description": (
        "Проверяет статус фоновых кодинг-задач (ACP): running/completed/error, "
        "последний инструмент и итог. Без task_id — список последних задач."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "ID задачи или слова из её названия (пусто — все последние)",
            }
        },
    },
}

REPLY_DECLARATION = {
    "name": "reply_to_coding_task",
    "description": (
        "Отправляет уточнение, ответ или подтверждение пользователя в "
        "активную ACP-сессию кодинг-агента (продолжает задачу)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "ID задачи или слова из названия (пусто — последняя активная)",
            },
            "message": {
                "type": "string",
                "description": "Точный текст ответа/уточнения для кодинг-агента",
            },
        },
        "required": ["message"],
    },
}

CANCEL_DECLARATION = {
    "name": "cancel_coding_task",
    "description": "Останавливает фоновую кодинг-задачу (убивает ACP-сессию и процесс агента).",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "ID задачи или слова из её названия",
            }
        },
        "required": ["task_id"],
    },
}


async def handle_dispatch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    task_text = _str_arg(args, "task") or ctx.last_user_utterance
    if not task_text:
        return {"status": "error", "message": "Пустой текст задачи."}
    return await acp_tasks.dispatch(
        task_text=task_text,
        cwd=_str_arg(args, "project_dir"),
        title=_str_arg(args, "title"),
        trace_cb=ctx.trace,
        notify_cb=ctx.notify,
    )


async def handle_status(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return acp_tasks.snapshot(_str_arg(args, "task_id"))


async def handle_reply(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    message = _str_arg(args, "message")
    if not message:
        return {"status": "error", "message": "Пустой текст ответа."}
    return await acp_tasks.reply(_str_arg(args, "task_id"), message)


async def handle_cancel(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return await acp_tasks.cancel(_str_arg(args, "task_id"))


_enabled = lambda p: p.enable_tasks  # noqa: E731

for spec in (
    ToolSpec("dispatch_coding_task", DISPATCH_DECLARATION, handle_dispatch, _enabled),
    ToolSpec("coding_task_status", STATUS_DECLARATION, handle_status, _enabled),
    ToolSpec("reply_to_coding_task", REPLY_DECLARATION, handle_reply, _enabled),
    ToolSpec("cancel_coding_task", CANCEL_DECLARATION, handle_cancel, _enabled),
):
    register(spec)
