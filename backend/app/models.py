"""Core data models — ported from VoxRelay's AcpModels.kt.

VoiceProfile (per-persona prompt, voice, memory, tool flags), dialogue
sessions and transcript entries keep the same semantics as the Android app so
the behavior (system prompt building, memory rules) ports 1:1.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

MAX_MEMORY_TOKENS = 4000
MAX_MEMORY_CHARS = 16_000


def estimate_memory_tokens(memory_text: str) -> int:
    if not memory_text.strip():
        return 0
    return max(1, min((len(memory_text) + 3) // 4, MAX_MEMORY_TOKENS))


# Selectable Gemini Live prebuilt voices. Custom profiles pick one of these;
# the four VoxRelay personas map onto the first four.
VOICE_OPTIONS: list[dict[str, str]] = [
    {"id": "FENRIR", "name": "Fenrir", "tone": "Глубокий · Дружеский"},
    {"id": "KORE", "name": "Kore", "tone": "Тёплый · Спокойный"},
    {"id": "PUCK", "name": "Puck", "tone": "Живой · Энергичный"},
    {"id": "AOEDE", "name": "Aoede", "tone": "Мягкий · Креативный"},
    {"id": "CHARON", "name": "Charon", "tone": "Низкий · Серьёзный"},
    {"id": "ZEPHYR", "name": "Zephyr", "tone": "Лёгкий · Светлый"},
]

VOICE_GEMINI_NAMES: dict[str, str] = {v["id"]: v["name"] for v in VOICE_OPTIONS}

BUILTIN_PROFILE_IDS = ("FENRIR", "KORE", "PUCK", "AOEDE")


class OrbStyle(str, Enum):
    SPHERE = "sphere"
    NEBULA = "nebula"
    RINGS = "rings"


class AgentState(str, Enum):
    STANDBY = "STANDBY"
    CONNECTING = "CONNECTING"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class TranscriptRole(str, Enum):
    USER = "USER"
    AGENT = "AGENT"
    TOOL = "TOOL"
    SYSTEM = "SYSTEM"


@dataclass
class Profile:
    """One persona profile — VoxRelay's VoiceProfile."""

    id: str  # = voice_id, one profile per voice like in VoxRelay
    voice_id: str = "FENRIR"
    display_name: str = "Фенрир"
    role_tag: str = "Друг и технарь"
    system_prompt: str = ""
    memory_text: str = ""
    enable_web_search: bool = True
    enable_memory: bool = True
    enable_tasks: bool = True  # reserved for the future Devin task tools
    orb_style: str = OrbStyle.SPHERE.value
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def gemini_voice(self) -> str:
        return VOICE_GEMINI_NAMES.get(self.voice_id.upper(), self.voice_id.title() or "Fenrir")

    @property
    def is_builtin(self) -> bool:
        return self.id in BUILTIN_PROFILE_IDS

    @property
    def estimated_tokens(self) -> int:
        return estimate_memory_tokens(self.memory_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "voice_id": self.voice_id,
            "display_name": self.display_name,
            "role_tag": self.role_tag,
            "system_prompt": self.system_prompt,
            "memory_text": self.memory_text,
            "memory_tokens": self.estimated_tokens,
            "memory_max_tokens": MAX_MEMORY_TOKENS,
            "enable_web_search": self.enable_web_search,
            "enable_memory": self.enable_memory,
            "enable_tasks": self.enable_tasks,
            "orb_style": self.orb_style,
            "gemini_voice": self.gemini_voice,
            "is_builtin": self.is_builtin,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TranscriptEntry:
    role: TranscriptRole
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    tool_name: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def timestamp_label(self) -> str:
        return time.strftime("%H:%M", time.localtime(self.timestamp))

    def to_wire_line(self) -> str:
        """VoxRelay's persisted line format: ROLE|HH:MM|tool|text."""
        safe_tool = (self.tool_name or "").replace("|", "/").replace("\n", " ")
        safe_text = self.text.replace("\n", " ")[:420]
        return f"{self.role.name}|{self.timestamp_label}|{safe_tool}|{safe_text}"

    @classmethod
    def from_wire_line(cls, index: int, raw: str) -> "TranscriptEntry":
        parts = raw.split("|", 3)
        if len(parts) == 4:
            role = TranscriptRole.__members__.get(parts[0].upper(), TranscriptRole.SYSTEM)
            return cls(
                id=f"restored-{index}",
                role=role,
                text=parts[3],
                tool_name=parts[2] or None,
            )
        return cls(id=f"restored-{index}", role=TranscriptRole.SYSTEM, text=raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role.name,
            "text": self.text,
            "tool_name": self.tool_name,
            "timestamp": self.timestamp,
            "time": self.timestamp_label,
        }


@dataclass
class DialogueSession:
    """VoxRelay's DialogueSession: a persisted conversation."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    profile_id: str = "FENRIR"
    title: str = ""
    summary: str = ""
    status: str = "active"  # active | archived
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self, messages: Optional[list[TranscriptEntry]] = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "profile_id": self.profile_id,
            "title": self.title,
            "summary": self.summary,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if messages is not None:
            out["messages"] = [m.to_dict() for m in messages]
            out["message_count"] = len(messages)
        return out
