"""Agent orchestration: voice sessions, text/headless chat, auto-memory.

Mirrors VoxRelay's GeminiLiveAgentController + ViewModel responsibilities:
- one DialogueSession per conversation, transcript persisted to Postgres
- the voice channel is a GeminiLiveClient (browser PCM16 <-> Gemini)
- the text channel routes into the live session when one is active, else it
  runs a generateContent tool-loop on the same instruction/tools (headless)
- after every completed turn the semi-automatic memory extractor runs in the
  background (VoxRelay's triggerSemiAutoMemoryExtraction)
"""

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

import structlog

from app import memory as memory_mod
from app import prompts, store
from app.config import settings
from app.gemini.duplex_base import AiEventType, is_barge_in_event
from app.gemini.live import GeminiLiveClient
from app.gemini.text import run_chat_turn
from app.models import (
    AgentState,
    DialogueSession,
    Profile,
    TranscriptEntry,
    TranscriptRole,
)
from app.tools import ToolContext, declarations_for, execute

logger = structlog.get_logger(__name__)

# Auto-memory: VoxRelay waits for >=2 dialogue entries, >=18 user chars, and
# reviews the last 6 entries.
AUTO_MEM_MIN_ENTRIES = 2
AUTO_MEM_SLICE = 6
AUTO_MEM_MIN_USER_CHARS = 18

# Text-chat history cache: session_id -> generateContent contents list.
_CHAT_HISTORIES: dict[str, list[dict[str, Any]]] = {}


class AgentSession:
    """One dialogue session bound to a profile, shared by voice and text."""

    def __init__(
        self,
        session: DialogueSession,
        profile: Profile,
        emit: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        self.session = session
        self.profile = profile
        self._emit = emit  # WS event sink; None in headless mode
        self.entries: list[TranscriptEntry] = []
        self.last_user_utterance = ""
        self._auto_mem_count = 0
        self._auto_mem_task: Optional[asyncio.Task] = None
        self._title_pending = True

    # ------------------------------------------------------------ events

    async def emit(self, payload: dict[str, Any]) -> None:
        if self._emit is not None:
            try:
                await self._emit(payload)
            except Exception as e:
                logger.debug("emit failed", error=str(e))

    async def set_state(self, state: AgentState, error: Optional[str] = None) -> None:
        await self.emit({"type": "state", "state": state.value, "error": error})

    async def trace(self, tool_name: str, summary: str) -> None:
        entry = TranscriptEntry(role=TranscriptRole.TOOL, text=summary, tool_name=tool_name)
        await self._record(entry)
        await self.emit(
            {"type": "tool_trace", "entry": entry.to_dict()}
        )

    # ------------------------------------------------------------ transcript

    async def _record(self, entry: TranscriptEntry) -> None:
        self.entries.append(entry)
        # The DB row appears with the first persisted entry — no messages, no session.
        await store.ensure_session(self.session)
        await store.append_message(self.session.id, entry)
        if self._title_pending and entry.role == TranscriptRole.USER:
            self._title_pending = False
            await store.touch_session(self.session.id, title=prompts.session_title_from(self.entries))
        else:
            await store.touch_session(self.session.id)

    async def user_text(self, text: str) -> TranscriptEntry:
        entry = TranscriptEntry(role=TranscriptRole.USER, text=text.strip())
        self.last_user_utterance = entry.text
        await self._record(entry)
        await self.emit({"type": "transcript", "entry": entry.to_dict()})
        return entry

    async def agent_text(self, text: str, streaming_id: Optional[str] = None) -> TranscriptEntry:
        entry = TranscriptEntry(role=TranscriptRole.AGENT, text=text.strip())
        if streaming_id:
            entry.id = streaming_id
        await self._record(entry)
        await self.emit({"type": "transcript", "entry": entry.to_dict()})
        return entry

    # ------------------------------------------------------------ memory

    def trigger_auto_memory(self) -> None:
        """VoxRelay's triggerSemiAutoMemoryExtraction — fire-and-forget."""
        if not self.profile.enable_memory:
            return
        dialogue = [
            e for e in self.entries
            if e.role in (TranscriptRole.USER, TranscriptRole.AGENT)
        ]
        if len(dialogue) < AUTO_MEM_MIN_ENTRIES or len(dialogue) <= self._auto_mem_count:
            return
        recent = dialogue[-AUTO_MEM_SLICE:]
        if sum(len(e.text) for e in recent if e.role == TranscriptRole.USER) < AUTO_MEM_MIN_USER_CHARS:
            return
        self._auto_mem_count = len(dialogue)

        if self._auto_mem_task and not self._auto_mem_task.done():
            self._auto_mem_task.cancel()
        self._auto_mem_task = asyncio.create_task(self._run_auto_memory(recent))

    async def _run_auto_memory(self, recent: list[TranscriptEntry]) -> None:
        snippet = "\n".join(
            f"{'Пользователь' if e.role == TranscriptRole.USER else self.profile.display_name}: {e.text}"
            for e in recent
        )
        try:
            decision = await memory_mod.extract_from_dialogue(self.profile, snippet)
        except asyncio.CancelledError:
            return
        if not decision:
            return
        updated = memory_mod.apply_update(
            self.profile.memory_text, decision["operation"], decision["fact"]
        )
        await store.update_profile_memory(self.profile.id, updated)
        self.profile.memory_text = updated
        await self.trace("auto_memory", f"Запомнил: {decision['fact'][:120]}")
        await self.emit({"type": "memory_updated", "profile_id": self.profile.id})

    # ------------------------------------------------------------ tools

    def tool_context(self) -> ToolContext:
        async def _trace(name: str, summary: str) -> None:
            await self.trace(name, summary)

        return ToolContext(
            profile=self.profile,
            session_id=self.session.id,
            trace=_trace,
            last_user_utterance=self.last_user_utterance,
        )

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        await self.set_state(AgentState.THINKING)
        ctx = self.tool_context()
        try:
            result = await execute(name, args, ctx)
        except Exception as e:
            logger.warning("Tool failed", name=name, error=str(e))
            result = {"status": "error", "message": str(e)}
        summary = str(result.get("summary") or result.get("message") or result.get("status", ""))[:160]
        await self.trace(name, summary or "done")
        return result


class VoiceSession:
    """Browser mic <-> Gemini Live bridge for one AgentSession."""

    FRAME_MS = 20

    def __init__(self, agent: AgentSession) -> None:
        self.agent = agent
        self._client: Optional[GeminiLiveClient] = None
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._agent_turn_id: Optional[str] = None
        self._pending = b""
        self._up_peak = 0
        self._up_frames = 0

    async def start(self) -> None:
        agent = self.agent
        profile = agent.profile
        await agent.set_state(AgentState.CONNECTING)

        continuation = prompts.continuation_context(agent.entries)
        instruction = prompts.build_system_instruction(profile, continuation)
        declarations = declarations_for(profile)

        from app.oauth import gemini_ws_auth

        self._client = GeminiLiveClient(
            api_key=settings.gemini_api_key or None,
            auth_provider=gemini_ws_auth,
            model=settings.live_model,
            voice=profile.gemini_voice,
            instructions=instruction,
            io_rate=settings.web_sample_rate,
            tools=declarations,
            tool_handler=agent.handle_tool_call,
        )
        await self._client.connect()
        self._running = True
        await agent.set_state(AgentState.LISTENING)
        await agent.trace(
            "gemini_live",
            f"Голосовой канал · {profile.display_name} ({profile.gemini_voice})"
            + (" · web search" if profile.enable_web_search else ""),
        )

        self._tasks = [
            asyncio.create_task(self._pump_audio(), name="live-audio-out"),
            asyncio.create_task(self._pump_events(), name="live-events"),
        ]

    async def _pump_audio(self) -> None:
        """Gemini audio -> emit to the browser as binary frames."""
        assert self._client is not None
        async for chunk in self._client.receive_chunks():
            if not self._running:
                break
            await self.agent.emit({"type": "audio", "data": chunk})

    async def _pump_events(self) -> None:
        """Translate AI events into transcript entries and UI state."""
        assert self._client is not None
        agent = self.agent
        async for event in self._client.events():
            data = event.data or {}
            if event.type == AiEventType.TRANSCRIPT_PARTIAL:
                if is_barge_in_event(event):
                    self._client.clear_audio_queue()
                    self._agent_turn_id = None
                    await agent.set_state(AgentState.LISTENING)
                    await agent.emit({"type": "barge_in"})
                    continue
                if data.get("event") == "turn_complete":
                    agent.trigger_auto_memory()
                    await agent.set_state(
                        AgentState.LISTENING if self._running else AgentState.STANDBY
                    )
                    continue
                role = data.get("role")
                text = (data.get("text") or "").strip()
                if role == "user" and text:
                    await agent.emit(
                        {"type": "transcript_partial", "role": "user", "text": text}
                    )
                elif role == "model" and text:
                    self._agent_turn_id = self._agent_turn_id or f"live-{time.time_ns()}"
                    await agent.emit(
                        {
                            "type": "transcript_partial",
                            "role": "agent",
                            "id": self._agent_turn_id,
                            "text": text,
                        }
                    )
                    await agent.set_state(AgentState.SPEAKING)

            elif event.type == AiEventType.TRANSCRIPT_FINAL:
                if data.get("event") == "tool_call":
                    continue  # traces are emitted by handle_tool_call
                role = data.get("role")
                text = (data.get("text") or "").strip()
                if not text:
                    continue
                if role == "user":
                    await agent.user_text(text)
                    await agent.set_state(AgentState.LISTENING)
                elif role == "model":
                    await agent.agent_text(text, streaming_id=self._agent_turn_id)
                    self._agent_turn_id = None

            elif event.type == AiEventType.DISCONNECTED:
                await agent.set_state(AgentState.ERROR, "Gemini Live отключился")
                break
            elif event.type == AiEventType.ERROR:
                await agent.set_state(AgentState.ERROR, str(event.error or data))

    async def send_audio(self, chunk: bytes) -> None:
        """Browser PCM16 bytes -> 20ms frames (frame_bytes) -> Gemini.

        The browser sends arbitrary-size chunks; GeminiLiveClient requires
        exact 20ms frames, so bytes are buffered and sliced here (same as
        VoiceAgent's web_bridge).
        """
        if self._client is None or not self._client.is_connected:
            return
        self._pending += chunk
        frame = self.frame_bytes
        while len(self._pending) >= frame:
            head, self._pending = self._pending[:frame], self._pending[frame:]
            # Uplink diagnostics: peak amplitude ~every 2s tells silence from signal
            peak = max(
                (abs(int.from_bytes(head[i : i + 2], "little", signed=True)))
                for i in range(0, len(head), 16)
            )
            self._up_peak = max(self._up_peak, peak)
            self._up_frames += 1
            if self._up_frames >= 100:
                logger.info(
                    "Uplink audio level",
                    peak=self._up_peak,
                    silent=self._up_peak < 100,
                )
                self._up_peak = 0
                self._up_frames = 0
            try:
                await self._client.send_pcm16_8k(head)
            except Exception as e:
                logger.debug("uplink frame dropped", error=str(e))

    async def send_text(self, text: str) -> None:
        """Route a typed message into the live session (text -> voice)."""
        await self.agent.user_text(text)
        if self._client is not None and self._client.is_connected:
            await self.agent.set_state(AgentState.THINKING)
            await self._client.send_text(text)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        await self.agent.set_state(AgentState.STANDBY)

    @property
    def frame_bytes(self) -> int:
        return settings.web_sample_rate * 2 * self.FRAME_MS // 1000

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected


# ---------------------------------------------------------------- text chat


async def _build_contents(session_id: str) -> list[dict[str, Any]]:
    """Restore generateContent history from persisted transcript (cold start)."""
    if session_id in _CHAT_HISTORIES:
        return _CHAT_HISTORIES[session_id]
    contents: list[dict[str, Any]] = []
    entries = await store.get_messages(session_id, limit=200)
    for e in entries:
        if e.role == TranscriptRole.USER:
            contents.append({"role": "user", "parts": [{"text": e.text}]})
        elif e.role == TranscriptRole.AGENT:
            contents.append({"role": "model", "parts": [{"text": e.text}]})
    _CHAT_HISTORIES[session_id] = contents
    return contents


async def chat_turn(
    agent: AgentSession,
    user_text: str,
    *,
    voice: Optional[VoiceSession] = None,
) -> dict[str, Any]:
    """One text turn.

    If a voice session is live, text is injected into it (VoxRelay behavior:
    the agent answers by voice); otherwise a generateContent tool-loop runs —
    used by the web chat, REST API and CLI (headless).
    """
    user_text = user_text.strip()
    if not user_text:
        return {"text": "", "traces": []}

    if voice is not None and voice.connected:
        await voice.send_text(user_text)
        return {"text": "", "traces": [], "routed_to_voice": True}

    await agent.user_text(user_text)
    await agent.set_state(AgentState.THINKING)

    history = await _build_contents(agent.session.id)
    instruction = prompts.build_system_instruction(
        agent.profile, prompts.continuation_context(agent.entries[:-1])
    )

    traces: list[dict[str, str]] = []

    async def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = await agent.handle_tool_call(name, args)
        return result

    try:
        outcome = await run_chat_turn(
            history,
            user_text,
            system_instruction=instruction,
            tools=declarations_for(agent.profile),
            tool_executor=executor,
        )
    except Exception as e:
        logger.error("Chat turn failed", error=str(e))
        await agent.set_state(AgentState.ERROR, str(e))
        return {"text": "", "traces": traces, "error": str(e)}

    reply = outcome.get("text") or ""
    traces = outcome.get("traces") or []
    if reply:
        await agent.agent_text(reply)
    elif outcome.get("finish") == "tool_rounds_exceeded":
        reply = "…слишком много вызовов инструментов подряд, остановился."
        await agent.agent_text(reply)
    else:
        reply = "(пустой ответ модели)"
        await agent.agent_text(reply)

    await agent.set_state(AgentState.STANDBY)
    agent.trigger_auto_memory()
    return {"text": reply, "traces": traces}
