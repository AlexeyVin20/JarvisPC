"""Local ACP (Agent Client Protocol) client + background task manager.

Spawns an ACP-capable agent CLI on this PC — Cursor ``cursor-agent acp``,
Devin CLI ``devin acp``, Gemini CLI, etc. — and speaks JSON-RPC 2.0 over
stdio with newline-delimited JSON, the same dialect as VoxRelay's
``LocalAcpClient`` (minus the WS bridge: JarvisPC already runs on the PC).

Flow per task: spawn -> ``initialize`` -> ``authenticate`` (only if the
agent advertises auth methods) -> ``session/new`` -> ``session/prompt``
(long-running, in a background asyncio task). ``session/update``
notifications stream progress into the task record; the agent's
``session/request_permission`` calls are auto-answered per
``settings.acp_permission`` so tasks run unattended.
"""

import asyncio
import json
import os
import secrets
import shlex
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# Callbacks into the dialogue session that dispatched the task.
TraceCallback = Callable[[str, str], Awaitable[None]]
NotifyCallback = Callable[[str], Awaitable[None]]

HANDSHAKE_TIMEOUT = 30.0
RESULT_SNIPPET_LEN = 800


def agent_argv() -> list[str]:
    """Configured ACP agent command split into argv (Windows-safe quoting)."""
    argv = shlex.split(settings.acp_agent_cmd, posix=(os.name != "nt"))
    # shlex(posix=False) leaves quotes inside tokens — strip them per-arg.
    return [a[1:-1] if len(a) > 1 and a[0] == '"' and a[-1] == '"' else a for a in argv]


class AcpError(Exception):
    pass


@dataclass
class AcpTask:
    """One dispatched coding task = one agent process + one ACP session."""

    id: str
    title: str
    cwd: str
    status: str = "starting"  # starting|running|completed|error|cancelled|timeout
    session_id: str = ""
    last_update: str = ""
    result_text: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    conn: Optional["AcpConnection"] = None
    runner: Optional[asyncio.Task] = None
    trace_cb: Optional[TraceCallback] = None
    notify_cb: Optional[NotifyCallback] = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "task_id": self.id,
            "title": self.title,
            "cwd": self.cwd,
            "status": self.status,
            "session_id": self.session_id,
            "last_update": self.last_update,
            "result": self.result_text[:RESULT_SNIPPET_LEN],
            "error": self.error,
            "age_sec": int((self.finished_at or time.time()) - self.created_at),
        }


class AcpConnection:
    """JSON-RPC 2.0 over a spawned agent's stdio (one ndjson message per line)."""

    def __init__(self, argv: list[str], cwd: str) -> None:
        self.argv = argv
        self.cwd = cwd
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._write_lock = asyncio.Lock()
        self.on_notification: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None
        self.on_exit: Optional[Callable[[], None]] = None
        self.agent_info: dict[str, Any] = {}

    async def start(self) -> None:
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd or None,
            )
        except FileNotFoundError:
            raise AcpError(
                f"ACP-агент не найден: «{self.argv[0]}». Установите Cursor CLI "
                "(agent/cursor-agent) или задайте другую команду в ACP_AGENT_CMD."
            )
        except Exception as e:
            raise AcpError(f"Не удалось запустить ACP-агента: {e}")
        self._reader_task = asyncio.create_task(self._read_loop(), name="acp-reader")
        self._stderr_task = asyncio.create_task(self._stderr_loop(), name="acp-stderr")

    async def _read_loop(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            async for raw in self.proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(msg)
        finally:
            self._fail_all(AcpError("ACP-агент завершил работу"))
            if self.on_exit:
                self.on_exit()

    async def _stderr_loop(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        async for raw in self.proc.stderr:
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                logger.debug("acp agent stderr", line=text[:300])

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        has_id = "id" in msg and msg["id"] is not None
        has_method = "method" in msg and msg["method"] is not None
        if has_id and not has_method:
            fut = self._pending.pop(int(msg["id"]), None)
            if fut is None or fut.done():
                return
            if msg.get("error"):
                err = msg["error"]
                fut.set_exception(
                    AcpError(f"ACP ошибка {err.get('code')}: {err.get('message')}")
                )
            else:
                fut.set_result(msg.get("result") or {})
        elif has_id and has_method:
            await self._handle_server_request(msg)
        elif has_method and self.on_notification is not None:
            try:
                await self.on_notification(msg)
            except Exception as e:
                logger.debug("acp notification handler failed", error=str(e))

    async def _handle_server_request(self, msg: dict[str, Any]) -> None:
        """Agent -> client calls: permissions get an auto-answer, the rest -32601."""
        req_id = msg["id"]
        if msg.get("method") == "session/request_permission":
            params = msg.get("params") or {}
            option = self._pick_permission_option(params.get("options") or [])
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "outcome": {
                            "outcome": "selected",
                            "optionId": option or "allow-once",
                        }
                    },
                }
            )
            return
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not handled by JarvisPC: {msg.get('method')}",
                },
            }
        )

    @staticmethod
    def _pick_permission_option(options: list[dict[str, Any]]) -> str:
        policy = settings.acp_permission
        wanted = {"allow_always": ("always", "allow"), "reject": ("reject", "deny")}.get(
            policy, ("allow_once", "allow", "once")
        )

        def haystack(o: dict[str, Any]) -> str:
            return " ".join(
                str(o.get(k, "")) for k in ("optionId", "id", "name", "kind")
            ).lower()

        if policy == "reject":
            for o in options:
                if any(w in haystack(o) for w in ("reject", "deny", "cancel")):
                    return str(o.get("optionId") or o.get("id") or "")
        for w in wanted:
            for o in options:
                if w in haystack(o):
                    return str(o.get("optionId") or o.get("id") or "")
        if options:
            return str(options[0].get("optionId") or options[0].get("id") or "")
        return {"allow_always": "allow-always", "reject": "reject-once"}.get(
            policy, "allow-once"
        )

    async def _send(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise AcpError("ACP-агент не запущен")
        async with self._write_lock:
            self.proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            await self.proc.stdin.drain()

    async def request(
        self, method: str, params: dict[str, Any], timeout: float = HANDSHAKE_TIMEOUT
    ) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[req_id] = fut
        await self._send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise AcpError(f"Тайм-аут ожидания ответа ACP на {method}")
        finally:
            self._pending.pop(req_id, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def handshake(self) -> dict[str, Any]:
        """initialize (+ authenticate if the agent advertises auth methods)."""
        result = await self.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": "JarvisPC", "version": "1.0"},
            },
        )
        self.agent_info = result.get("agentInfo") or {}
        auth_methods = result.get("authMethods") or []
        if auth_methods:
            method_id = settings.acp_auth_method or str(
                auth_methods[0].get("id") or auth_methods[0].get("methodId") or ""
            )
            if method_id:
                params: dict[str, Any] = {"methodId": method_id}
                if settings.acp_api_key:
                    params["meta"] = {"api_key": settings.acp_api_key}
                try:
                    await self.request("authenticate", params)
                except AcpError as e:
                    # Pre-authenticated CLIs (agent login, devin config) may
                    # legitimately reject or ignore this — session/new decides.
                    logger.warning("acp authenticate failed, continuing", error=str(e))
        return self.agent_info

    async def new_session(self) -> str:
        result = await self.request(
            "session/new", {"cwd": self.cwd, "mcpServers": []}
        )
        return str(result.get("sessionId") or "")

    async def prompt(
        self, session_id: str, text: str, timeout: float
    ) -> dict[str, Any]:
        return await self.request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            timeout=timeout,
        )

    async def cancel_session(self, session_id: str) -> None:
        try:
            await self.notify("session/cancel", {"sessionId": session_id})
        except Exception:
            pass

    async def close(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), 3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        for t in (self._reader_task, self._stderr_task):
            if t is not None:
                t.cancel()
        self._fail_all(AcpError("ACP-соединение закрыто"))

    def _fail_all(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()


# ------------------------------------------------------------------ manager


class AcpTaskManager:
    """Tracks dispatched tasks; runs each on its own agent process."""

    KEEP_FINISHED = 20

    def __init__(self) -> None:
        self._tasks: dict[str, AcpTask] = {}

    def _find(self, query: str) -> Optional[AcpTask]:
        q = (query or "").strip().lower()
        if not q:
            active = [t for t in self._tasks.values() if t.status in ("starting", "running")]
            if len(active) == 1:
                return active[0]
            return max(self._tasks.values(), key=lambda t: t.created_at, default=None)
        if q in self._tasks:
            return self._tasks[q]
        for t in self._tasks.values():
            if t.id.lower().startswith(q) or (t.session_id and t.session_id.lower().startswith(q)):
                return t
        for t in self._tasks.values():
            if q in t.title.lower():
                return t
        return None

    def available(self) -> tuple[bool, str]:
        argv = agent_argv()
        if not argv:
            return False, "ACP_AGENT_CMD не задан."
        exe = argv[0]
        has_sep = os.sep in exe or (os.altsep is not None and os.altsep in exe)
        exists = os.path.isfile(exe) if has_sep else shutil.which(exe) is not None
        if not exists:
            return (
                False,
                f"ACP-агент «{exe}» не найден. Установите Cursor CLI "
                "(https://cursor.com/docs/cli) или укажите ACP_AGENT_CMD.",
            )
        return True, ""

    async def dispatch(
        self,
        task_text: str,
        cwd: str,
        title: str,
        trace_cb: Optional[TraceCallback],
        notify_cb: Optional[NotifyCallback],
    ) -> dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            return {"status": "error", "message": reason}
        cwd = cwd.strip() or settings.acp_default_cwd
        if not cwd or not os.path.isdir(cwd):
            return {
                "status": "error",
                "message": (
                    "Не указана рабочая папка проекта (project_dir) — спроси у "
                    "пользователя, в какой папке работать, или задай ACP_DEFAULT_CWD."
                ),
            }
        task = AcpTask(
            id=secrets.token_hex(2),
            title=title.strip() or task_text.strip()[:80],
            cwd=cwd,
            trace_cb=trace_cb,
            notify_cb=notify_cb,
        )
        self._tasks[task.id] = task
        self._prune()
        task.runner = asyncio.create_task(
            self._run(task, task_text), name=f"acp-task-{task.id}"
        )
        return {
            "status": "ok",
            "task_id": task.id,
            "message": (
                f"Задача «{task.title}» отправлена кодинг-агенту "
                f"({settings.acp_agent_cmd}) в фоне. Итог придёт отдельным событием; "
                f"статус — через coding_task_status."
            ),
        }

    async def _run(self, task: AcpTask, prompt_text: str) -> None:
        conn = AcpConnection(agent_argv(), task.cwd)
        task.conn = conn
        conn.on_exit = lambda: self._on_exit(task)
        conn.on_notification = lambda msg: self._on_notification(task, msg)
        try:
            await conn.start()
            info = await conn.handshake()
            agent_name = info.get("name") or "ACP-агент"
            task.session_id = await conn.new_session()
            task.status = "running"
            await self._trace(task, f"{agent_name}: сессия {task.session_id[:12]}…")
            await self._prompt_and_finish(task, prompt_text)
        except asyncio.CancelledError:
            task.status = "cancelled"
            task.finished_at = time.time()
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.finished_at = time.time()
            await self._notify(task, f"Кодинг-задача «{task.title}» упала с ошибкой: {e}")
            await conn.close()

    async def _prompt_and_finish(self, task: AcpTask, prompt_text: str) -> None:
        """One session/prompt turn; handles all terminal states internally."""
        assert task.conn is not None and task.session_id
        try:
            result = await task.conn.prompt(
                task.session_id, prompt_text, timeout=settings.acp_prompt_timeout
            )
        except asyncio.CancelledError:
            return
        except AcpError as e:
            if "Тайм-аут" in str(e):
                task.status = "timeout"
                await task.conn.cancel_session(task.session_id)
                await self._finish(
                    task, f"Кодинг-задача «{task.title}» превысила тайм-аут — остановлена."
                )
                return
            task.status = "error"
            task.error = str(e)
            await self._finish(
                task, f"Кодинг-задача «{task.title}» упала с ошибкой: {e}"
            )
            return
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            await self._finish(
                task, f"Кодинг-задача «{task.title}» упала с ошибкой: {e}"
            )
            return
        stop = str(result.get("stopReason") or "end_turn")
        if stop in ("cancelled",):
            task.status = "cancelled"
        else:
            task.status = "completed"
        summary = task.result_text.strip()[-RESULT_SNIPPET_LEN:] or "(агент не вернул текст)"
        await self._finish(
            task,
            f"Кодинг-задача «{task.title}» завершена ({stop}). Итог: {summary}",
        )

    async def reply(self, query: str, message: str) -> dict[str, Any]:
        task = self._find(query)
        if task is None:
            return {"status": "error", "message": f"Задача «{query}» не найдена."}
        if task.conn is None or task.conn.proc is None or task.conn.proc.returncode is not None:
            return {
                "status": "error",
                "message": f"Сессия задачи «{task.title}» уже завершена — отправь новую задачу.",
            }
        if not task.session_id:
            return {"status": "error", "message": "Сессия ещё не создана — задача запускается."}
        if task.status == "running":
            return {
                "status": "error",
                "message": f"Задача «{task.title}» ещё выполняется — дождитесь итога или остановите её.",
            }
        task.status = "running"
        task.runner = asyncio.create_task(
            self._prompt_and_finish(task, message), name=f"acp-reply-{task.id}"
        )
        return {
            "status": "ok",
            "task_id": task.id,
            "message": f"Ответ отправлен в задачу «{task.title}».",
        }

    async def cancel(self, query: str) -> dict[str, Any]:
        task = self._find(query)
        if task is None:
            return {"status": "error", "message": f"Задача «{query}» не найдена."}
        if task.conn is not None:
            if task.session_id:
                await task.conn.cancel_session(task.session_id)
            await task.conn.close()
        if task.runner is not None:
            task.runner.cancel()
        task.status = "cancelled"
        task.finished_at = time.time()
        return {"status": "ok", "task_id": task.id, "message": f"Задача «{task.title}» остановлена."}

    def snapshot(self, query: str = "") -> dict[str, Any]:
        if query.strip():
            task = self._find(query)
            if task is None:
                return {"status": "error", "message": f"Задача «{query}» не найдена."}
            return {"status": "ok", "tasks": [task.snapshot()]}
        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        if not tasks:
            return {"status": "ok", "tasks": [], "message": "Активных задач нет."}
        return {"status": "ok", "tasks": [t.snapshot() for t in tasks[:10]]}

    # ------------------------------------------------------------ internals

    def _on_exit(self, task: AcpTask) -> None:
        if task.status in ("starting", "running"):
            task.status = "error"
            task.error = "процесс агента завершился"
            task.finished_at = time.time()
            try:
                asyncio.get_running_loop().create_task(
                    self._notify(
                        task,
                        f"Кодинг-агент завершился во время задачи «{task.title}».",
                    )
                )
            except RuntimeError:
                pass

    async def _on_notification(self, task: AcpTask, msg: dict[str, Any]) -> None:
        if msg.get("method") != "session/update":
            return
        params = msg.get("params") or {}
        update = params.get("update") or params
        kind = update.get("sessionUpdate") or update.get("type") or ""
        if kind == "agent_message_chunk":
            text = _content_text(update.get("content"))
            if text:
                task.result_text += text
        elif kind in ("tool_call", "tool_call_update"):
            title = update.get("title") or update.get("name") or update.get("kind") or ""
            status = update.get("status") or ""
            label = f"{title} ({status})" if status else title
            if label and label != task.last_update:
                task.last_update = label
                await self._trace(task, f"→ {label}")
        elif kind == "plan":
            entries = update.get("entries") or update.get("steps") or []
            task.last_update = f"план: {len(entries)} шагов"
        elif kind == "current_mode_update":
            task.last_update = f"режим: {update.get('currentModeId') or update.get('modeId')}"

    async def _trace(self, task: AcpTask, summary: str) -> None:
        if task.trace_cb is not None:
            try:
                await task.trace_cb("acp_task", summary[:160])
            except Exception:
                pass

    async def _notify(self, task: AcpTask, text: str) -> None:
        # notify_cb (agent._background_notify) persists the TOOL line itself —
        # falling back to a bare trace only when no callback is attached.
        if task.notify_cb is not None:
            try:
                await task.notify_cb(text)
                return
            except Exception as e:
                logger.debug("acp notify failed", error=str(e))
        await self._trace(task, text)

    async def _finish(self, task: AcpTask, text: str) -> None:
        task.finished_at = time.time()
        await self._notify(task, text)

    def _prune(self) -> None:
        finished = [
            t for t in self._tasks.values() if t.status not in ("starting", "running")
        ]
        if len(finished) <= self.KEEP_FINISHED:
            return
        for t in sorted(finished, key=lambda t: t.finished_at)[: -self.KEEP_FINISHED]:
            self._tasks.pop(t.id, None)
            if t.conn is not None:
                asyncio.get_running_loop().create_task(t.conn.close())

    async def shutdown(self) -> None:
        """Kill every live agent process — called on backend shutdown."""
        for t in self._tasks.values():
            if t.conn is not None:
                await t.conn.close()
            if t.runner is not None:
                t.runner.cancel()


def _content_text(content: Any) -> str:
    if isinstance(content, dict):
        return str(content.get("text") or "")
    if isinstance(content, list):
        return "".join(
            str(c.get("text") or "") for c in content if isinstance(c, dict)
        )
    return ""


acp_tasks = AcpTaskManager()
