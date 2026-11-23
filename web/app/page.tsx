"use client";

import {
  CSSProperties,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useJarvis } from "@/lib/useJarvis";
import { api, AuthStatus, Profile, SessionInfo, VoiceOption } from "@/lib/api";

type View = "chat" | "profiles" | "memory" | "sessions";
type ThemeMode = "dark" | "light";

const COLOR_PRESETS = [
  { id: "cyan", name: "Кибер-циан", hex: "#22d3ee" },
  { id: "indigo", name: "Нейро-индиго", hex: "#6366f1" },
  { id: "violet", name: "Ультрафиолет", hex: "#a855f7" },
  { id: "emerald", name: "Матрица", hex: "#10b981" },
  { id: "amber", name: "Солнечный", hex: "#f59e0b" },
  { id: "rose", name: "Импульс", hex: "#f43f5e" },
  { id: "titanium", name: "Титан", hex: "#94a3b8" },
];

const STORAGE_COLOR_KEY = "jarvis_accent_color";
const STORAGE_THEME_KEY = "jarvis_theme_mode";

function hexToRgb(hex: string) {
  const clean = hex.replace("#", "").trim();
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean.padEnd(6, "0").slice(0, 6);
  const num = parseInt(full, 16);
  return {
    r: (num >> 16) & 255,
    g: (num >> 8) & 255,
    b: num & 255,
  };
}

function rgbToHsl(r: number, g: number, b: number) {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case rn:
        h = (gn - bn) / d + (gn < bn ? 6 : 0);
        break;
      case gn:
        h = (bn - rn) / d + 2;
        break;
      case bn:
        h = (rn - gn) / d + 4;
        break;
    }
    h *= 60;
  }
  return { h, s: s * 100, l: l * 100 };
}

function hslToRgb(h: number, s: number, l: number) {
  const sn = s / 100;
  const ln = l / 100;
  const c = (1 - Math.abs(2 * ln - 1)) * sn;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = ln - c / 2;
  let rn = 0,
    gn = 0,
    bn = 0;
  if (h < 60) [rn, gn, bn] = [c, x, 0];
  else if (h < 120) [rn, gn, bn] = [x, c, 0];
  else if (h < 180) [rn, gn, bn] = [0, c, x];
  else if (h < 240) [rn, gn, bn] = [0, x, c];
  else if (h < 300) [rn, gn, bn] = [x, 0, c];
  else [rn, gn, bn] = [c, 0, x];
  return {
    r: Math.round((rn + m) * 255),
    g: Math.round((gn + m) * 255),
    b: Math.round((bn + m) * 255),
  };
}

function applyDynamicPalette(hex: string, theme: ThemeMode) {
  const root = document.documentElement;
  root.setAttribute("data-theme", theme);

  const { r, g, b } = hexToRgb(hex);
  const { h, s, l } = rgbToHsl(r, g, b);

  // Гармоничный вторичный оттенок со смещением по цветовому кругу
  const h2 = (h + 38) % 360;
  const s2 = s < 16 ? s : Math.min(96, Math.max(s, 68));
  const l2 = Math.min(70, Math.max(46, l));
  const rgb2 = hslToRgb(h2, s2, l2);

  // Расчёт читаемого контрастного текста поверх акцента
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  const contrast = lum > 0.62 ? "#07090e" : "#ffffff";

  root.style.setProperty("--accent", hex);
  root.style.setProperty("--accent-rgb", `${r}, ${g}, ${b}`);
  root.style.setProperty("--accent-2", `rgb(${rgb2.r}, ${rgb2.g}, ${rgb2.b})`);
  root.style.setProperty("--accent-2-rgb", `${rgb2.r}, ${rgb2.g}, ${rgb2.b}`);
  root.style.setProperty("--accent-contrast", contrast);
}

const NAV: { id: View; label: string; icon: ReactNode }[] = [
  {
    id: "chat",
    label: "Чат",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path
          d="M21 12a8 8 0 0 1-8 8H4l2.2-2.9A8 8 0 1 1 21 12z"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    id: "profiles",
    label: "Профили",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: "memory",
    label: "Память",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path
          d="M9 3a4 4 0 0 0-4 5 4 4 0 0 0-1 7 4 4 0 0 0 4 5"
          strokeLinecap="round"
        />
        <path
          d="M15 3a4 4 0 0 1 4 5 4 4 0 0 1 1 7 4 4 0 0 1-4 5"
          strokeLinecap="round"
        />
        <path d="M12 4v16" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: "sessions",
    label: "Диалоги",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M4 6h16M4 12h16M4 18h10" strokeLinecap="round" />
      </svg>
    ),
  },
];

const STATE_LABEL: Record<string, string> = {
  IDLE: "ГОТОВ",
  STANDBY: "ГОТОВ",
  CONNECTING: "ПОДКЛЮЧЕНИЕ",
  LISTENING: "СЛУШАЮ",
  THINKING: "ДУМАЮ",
  SPEAKING: "ГОВОРЮ",
  ERROR: "ОШИБКА",
};

const ROLE_CLASS: Record<string, string> = {
  USER: "user",
  AGENT: "agent",
  TOOL: "tool",
  SYSTEM: "system",
};

const MIC_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9">
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
  </svg>
);

const STOP_ICON = (
  <svg viewBox="0 0 24 24" fill="currentColor">
    <rect x="6.5" y="6.5" width="11" height="11" rx="2.5" />
  </svg>
);

const SEND_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M5 12h14M13 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const PALETTE_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M12 3a9 9 0 1 0 0 18h1.5a2.5 2.5 0 0 0 0-5H13a2 2 0 0 1-2-2v-.5a2.5 2.5 0 0 1 2.5-2.5H16a5 5 0 0 0-4-8z" />
    <circle cx="7.5" cy="10.5" r="1" fill="currentColor" />
    <circle cx="10.5" cy="7.5" r="1" fill="currentColor" />
    <circle cx="15" cy="7.5" r="1" fill="currentColor" />
  </svg>
);

function fmtTime(t?: number | string) {
  if (!t) return "";
  const d = typeof t === "number" ? new Date(t * 1000) : new Date(t);
  return `${d.getDate().toString().padStart(2, "0")}.${(d.getMonth() + 1)
    .toString()
    .padStart(2, "0")} ${d.getHours().toString().padStart(2, "0")}:${d
    .getMinutes()
    .toString()
    .padStart(2, "0")}`;
}

function AgentOrb({
  size = "sm",
  stateCls,
  pulse = false,
  micLevel = 0,
  voiceOn = false,
}: {
  size?: "sm" | "md" | "lg";
  stateCls: string;
  pulse?: boolean;
  micLevel?: number;
  voiceOn?: boolean;
}) {
  const scale = voiceOn ? 1 + Math.min(micLevel, 1) * 0.25 : 1;
  return (
    <div
      className={`orb orb-${size} ${stateCls} ${pulse ? "pulse" : ""} ${
        voiceOn ? "voice-on" : ""
      }`}
      style={{ "--mic-scale": scale } as CSSProperties}
    >
      <span className="orb-halo" />
      <span className="orb-ring r1" />
      <span className="orb-ring r2" />
      <span className="orb-core" />
    </div>
  );
}

export default function Page() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [view, setView] = useState<View>("chat");
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Profile | null>(null);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [memDirty, setMemDirty] = useState(false);
  const [input, setInput] = useState("");
  const [sessionSearch, setSessionSearch] = useState("");
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [orbPulse, setOrbPulse] = useState(false);
  const [now, setNow] = useState<Date | null>(null);

  // Динамическая тема и цвет
  const [accent, setAccent] = useState<string>("#22d3ee");
  const [theme, setTheme] = useState<ThemeMode>("dark");
  const [paletteOpen, setPaletteOpen] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const paletteRef = useRef<HTMLDivElement>(null);

  // Инициализация сохранённого цвета и темы
  useEffect(() => {
    try {
      const savedColor = localStorage.getItem(STORAGE_COLOR_KEY);
      const savedTheme = localStorage.getItem(STORAGE_THEME_KEY) as ThemeMode | null;
      if (savedColor && /^#[0-9a-fA-F]{6}$/.test(savedColor)) setAccent(savedColor);
      if (savedTheme === "dark" || savedTheme === "light") setTheme(savedTheme);
    } catch {}
  }, []);

  useEffect(() => {
    applyDynamicPalette(accent, theme);
    try {
      localStorage.setItem(STORAGE_COLOR_KEY, accent);
      localStorage.setItem(STORAGE_THEME_KEY, theme);
    } catch {}
  }, [accent, theme]);

  // Закрытие поповера палитры по клику вне области
  useEffect(() => {
    if (!paletteOpen) return;
    function onDown(e: MouseEvent) {
      if (paletteRef.current && !paletteRef.current.contains(e.target as Node)) {
        setPaletteOpen(false);
      }
    }
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [paletteOpen]);

  const refresh = useCallback(async () => {
    try {
      const [ps, ss] = await Promise.all([api.profiles(), api.sessions()]);
      setProfiles(ps);
      setSessions(ss);
    } catch {}
  }, []);

  const refreshAuth = useCallback(async () => {
    try {
      setAuth(await api.authStatus());
    } catch {}
  }, []);

  const j = useJarvis({ onMemoryUpdated: refresh });

  useEffect(() => {
    j.connect();
    refresh();
    refreshAuth();
    api.voices().then(setVoices).catch(() => {});
    setNow(new Date());
    const clock = setInterval(() => setNow(new Date()), 30000);
    const q = new URLSearchParams(window.location.search);
    if (q.get("auth")) {
      window.history.replaceState({}, "", window.location.pathname);
      refreshAuth();
    }
    return () => clearInterval(clock);
  }, []); // eslint-disable-line

  useEffect(() => {
    if (!j.profile) return;
    setProfiles((prev) => {
      const i = prev.findIndex((p) => p.id === j.profile!.id);
      if (i < 0) return [...prev, j.profile!];
      const copy = [...prev];
      copy[i] = j.profile!;
      return copy;
    });
  }, [j.profile]);

  useEffect(() => {
    refresh();
  }, [j.sessionId]); // eslint-disable-line

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [j.messages, j.liveUser, j.liveAgent]);

  const ap = j.profile;
  useEffect(() => {
    if (!memDirty) setMemoryDraft(ap?.memory_text || "");
  }, [ap, memDirty]);

  const editing = editingId ? profiles.find((p) => p.id === editingId) : null;
  useEffect(() => {
    setDraft(editing ? { ...editing } : null);
  }, [editingId]); // eslint-disable-line

  const toolCount = useMemo(
    () => j.messages.filter((m) => m.role === "TOOL").length,
    [j.messages]
  );

  const filteredSessions = useMemo(() => {
    const q = sessionSearch.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => (s.title || "Диалог").toLowerCase().includes(q));
  }, [sessions, sessionSearch]);

  const memoryFactsCount = useMemo(
    () => ap?.memory_text?.split("\n").filter((l) => l.trim()).length || 0,
    [ap?.memory_text]
  );

  function send() {
    const t = input.trim();
    if (!t) return;
    setInput("");
    j.sendChat(t);
  }

  function toggleVoice() {
    setOrbPulse(true);
    setTimeout(() => setOrbPulse(false), 750);
    if (j.voiceOn) j.stopVoice();
    else j.startVoice();
  }

  async function saveDraft() {
    if (!draft) return;
    await api.updateProfile(draft.id, {
      display_name: draft.display_name,
      role_tag: draft.role_tag,
      system_prompt: draft.system_prompt,
      voice_id: draft.voice_id,
      enable_web_search: draft.enable_web_search,
      enable_memory: draft.enable_memory,
      enable_tasks: draft.enable_tasks,
      orb_style: draft.orb_style,
    });
    await refresh();
    setEditingId(null);
    setDraft(null);
  }

  async function createProfile() {
    const p = await api.createProfile({
      display_name: "Новый профиль",
      voice_id: "ZEPHYR",
      role_tag: "Личный ассистент",
    });
    await refresh();
    setEditingId(p.id);
  }

  async function removeProfile(id: string) {
    if (!confirm("Удалить профиль вместе с его диалогами?")) return;
    await api.deleteProfile(id);
    if (editingId === id) setEditingId(null);
    await refresh();
  }

  async function resetProfile(id: string) {
    if (!confirm("Сбросить профиль к заводским настройкам?")) return;
    await api.resetProfile(id);
    await refresh();
  }

  async function activate(p: Profile) {
    j.switchProfile(p.id);
    try {
      await api.activateProfile(p.id);
    } catch {}
    await refresh();
  }

  async function submitApiKey() {
    if (!keyInput.trim()) return;
    await api.saveApiKey(keyInput);
    setKeyInput("");
    await refreshAuth();
  }

  const memPct = ap
    ? Math.min(100, Math.round((ap.memory_tokens / Math.max(1, ap.memory_max_tokens)) * 100))
    : 0;

  const orbCls = j.state === "STANDBY" ? "" : j.state.toLowerCase();

  return (
    <div className={`app ${j.voiceOn ? "voice-active" : ""}`}>
      {/* Динамическое фоновое свечение */}
      <div className="ambient-mesh" aria-hidden="true">
        <span className="blob b1" />
        <span className="blob b2" />
      </div>

      {/* ---------------- Левый навигационный док ---------------- */}
      <nav className="rail">
        <div className="mark" title="Jarvis Neural Agent">
          <span>J</span>
        </div>

        <div className="rail-nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`rbtn ${view === n.id ? "active" : ""}`}
              onClick={() => setView(n.id)}
            >
              <span className="rbtn-ic">{n.icon}</span>
              <span>{n.label}</span>
            </button>
          ))}
        </div>

        <div className="flex" />

        {/* Быстрые цветовые точки на панели */}
        <div className="rail-swatches" title="Быстрый выбор цвета">
          {COLOR_PRESETS.slice(0, 4).map((c) => (
            <button
              key={c.id}
              className={`mini-swatch ${accent.toLowerCase() === c.hex ? "active" : ""}`}
              style={{ background: c.hex }}
              onClick={() => setAccent(c.hex)}
              aria-label={c.name}
            />
          ))}
        </div>

        <div
          className={`conn-indicator ${j.connected ? "on" : ""}`}
          title={j.connected ? "Backend подключён" : "Backend не подключён"}
        >
          <span className="conn-dot" />
        </div>
      </nav>

      {/* ---------------- Основная область ---------------- */}
      <div className="content">
        <header className="topbar">
          <div className="brand-block">
            <div className="title">
              Jarvis
              <span className="agent-badge">AI AGENT</span>
            </div>
            <div className="subtitle">
              {ap ? `${ap.display_name} · ${ap.role_tag || "Ассистент"}` : "Инициализация ядра…"}
            </div>
          </div>

          <div className="flex" />

          <div className="datechip">
            {now
              ? now
                  .toLocaleDateString("ru-RU", {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                  })
                  .toUpperCase()
              : "…"}
            {now && (
              <span className="time-sep">
                {now.toLocaleTimeString("ru-RU", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
          </div>

          <div className={`state-pill ${orbCls}`}>
            <span className="dot" />
            {STATE_LABEL[j.state] || j.state}
          </div>

          {/* Выбор профиля */}
          <div className="select-wrap">
            <select
              className="pselect"
              value={ap?.id || ""}
              onChange={(e) => {
                const p = profiles.find((x) => x.id === e.target.value);
                if (p) activate(p);
              }}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name} · {p.gemini_voice}
                </option>
              ))}
            </select>
          </div>

          {/* Кнопка динамической настройки цвета и темы */}
          <div className="palette-anchor" ref={paletteRef}>
            <button
              className={`icon-pill ${paletteOpen ? "open" : ""}`}
              onClick={() => setPaletteOpen((v) => !v)}
              title="Цвет и тема интерфейса"
            >
              <span className="swatch-dot" style={{ background: accent }} />
              {PALETTE_ICON}
            </button>

            {paletteOpen && (
              <div className="palette-popover">
                <div className="pop-head">
                  <span>Оформление агента</span>
                  <span className="hex-code">{accent.toUpperCase()}</span>
                </div>

                <div className="theme-switch">
                  <button
                    className={theme === "dark" ? "active" : ""}
                    onClick={() => setTheme("dark")}
                  >
                    Тёмная
                  </button>
                  <button
                    className={theme === "light" ? "active" : ""}
                    onClick={() => setTheme("light")}
                  >
                    Светлая
                  </button>
                </div>

                <div className="pop-label">Акцентный цвет</div>
                <div className="preset-grid">
                  {COLOR_PRESETS.map((c) => (
                    <button
                      key={c.id}
                      className={`preset-btn ${
                        accent.toLowerCase() === c.hex.toLowerCase() ? "active" : ""
                      }`}
                      onClick={() => setAccent(c.hex)}
                      title={c.name}
                    >
                      <span className="preset-dot" style={{ background: c.hex }} />
                      <span className="preset-name">{c.name}</span>
                    </button>
                  ))}
                </div>

                <div className="custom-color-row">
                  <label htmlFor="jarvis-color-picker">Свой цвет</label>
                  <div className="picker-wrap">
                    <input
                      id="jarvis-color-picker"
                      type="color"
                      value={accent}
                      onChange={(e) => setAccent(e.target.value)}
                    />
                    <span>Выбрать</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </header>

        {/* ================= VIEW: CHAT ================= */}
        {view === "chat" && (
          <div className="dash">
            {/* Главная карточка чата */}
            <section className="card chat-card">
              <div className="chat-head">
                <AgentOrb
                  size="sm"
                  stateCls={orbCls}
                  micLevel={j.micLevel}
                  voiceOn={j.voiceOn}
                />
                <div className="who">
                  <div className="who-row">
                    <span>{ap?.display_name || "Jarvis"}</span>
                    {ap?.gemini_voice && <span className="voice-tag">{ap.gemini_voice}</span>}
                  </div>
                  <small>
                    {j.voiceOn ? (
                      <span className="voice-status-line">
                        <span className="live-dot" />
                        голосовая сессия ·{" "}
                        {j.micLevel > 0.02 ? "слышу вас" : "ожидаю речь"}
                        <span className="micmeter">
                          <span style={{ width: `${Math.min(100, Math.round(j.micLevel * 130))}%` }} />
                        </span>
                      </span>
                    ) : j.micError ? (
                      <span className="err-text">микрофон недоступен: {j.micError}</span>
                    ) : (
                      "текстовый и голосовой режим · готов к задачам"
                    )}
                  </small>
                </div>
                <div className="right">
                  <button className="smallbtn" onClick={j.newSession}>
                    + Новый диалог
                  </button>
                </div>
              </div>

              <div className="transcript" ref={scrollRef}>
                {j.messages.length === 0 && !j.liveUser && !j.liveAgent && (
                  <div className="hero">
                    <AgentOrb
                      size="lg"
                      stateCls={orbCls}
                      pulse={orbPulse}
                      micLevel={j.micLevel}
                      voiceOn={j.voiceOn}
                    />
                    <h2>Чем помочь сегодня?</h2>
                    <p>
                      {ap?.display_name || "Jarvis"} на связи — голос в реальном времени,
                      долгосрочная память и веб-поиск. Нажмите на микрофон или выберите запрос.
                    </p>
                    <div className="chips">
                      {[
                        "Что нового сегодня?",
                        "Расскажи, что ты умеешь",
                        "Запомни: я работаю над JarvisPC",
                      ].map((s) => (
                        <button key={s} className="chip" onClick={() => j.sendChat(s)}>
                          <span>{s}</span>
                          <span className="chip-arrow">→</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {j.messages.map((m) =>
                  m.role === "TOOL" ? (
                    <div key={m.id} className="msg tool">
                      <span className="tool-badge">TOOL</span>
                      <span>{m.text}</span>
                    </div>
                  ) : m.role === "SYSTEM" ? (
                    <div key={m.id} className="msg system">
                      {m.text}
                    </div>
                  ) : (
                    <div key={m.id} className={`msg ${ROLE_CLASS[m.role]}`}>
                      <span className="meta">
                        {m.role === "USER" ? "ВЫ" : ap?.display_name?.toUpperCase() || "JARVIS"}
                      </span>
                      <div className="msg-body">{m.text}</div>
                    </div>
                  )
                )}

                {j.liveUser && (
                  <div className="msg user live">
                    <span className="meta">ВЫ · LIVE</span>
                    <div className="msg-body">{j.liveUser}</div>
                  </div>
                )}
                {j.liveAgent && (
                  <div className="msg agent live">
                    <span className="meta">
                      {ap?.display_name?.toUpperCase() || "JARVIS"} · LIVE
                    </span>
                    <div className="msg-body">{j.liveAgent.text}</div>
                  </div>
                )}
                {j.state === "THINKING" && (
                  <div className="msg agent live">
                    <span className="meta">
                      {ap?.display_name?.toUpperCase() || "JARVIS"}
                    </span>
                    <span className="typing">
                      <i />
                      <i />
                      <i />
                    </span>
                  </div>
                )}
              </div>

              <div className="inputbar-wrap">
                <div className="inputbar">
                  <button
                    className={`btn mic ${j.voiceOn ? "on" : ""}`}
                    onClick={toggleVoice}
                    title={
                      j.voiceOn
                        ? "Выключить голосовой режим"
                        : "Включить голосовой режим"
                    }
                  >
                    {j.voiceOn ? STOP_ICON : MIC_ICON}
                  </button>
                  <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && send()}
                    placeholder={`Напишите ${ap?.display_name || "Jarvis"}…`}
                  />
                  <button
                    className="btn accent send-btn"
                    onClick={send}
                    disabled={!input.trim()}
                    title="Отправить"
                  >
                    <span>Отправить</span>
                    {SEND_ICON}
                  </button>
                </div>
              </div>
            </section>

            {/* Правая колонка телеметрии */}
            <aside className="sidecol">
              {/* Карточка статуса и голосового ядра */}
              <div
                className={`card widget voice core-card ${j.voiceOn ? "live" : ""}`}
                onClick={toggleVoice}
                title={
                  j.voiceOn
                    ? "Нажмите, чтобы выключить голос"
                    : "Нажмите, чтобы включить голос"
                }
              >
                <h3>
                  <span>Ядро агента</span>
                  <span className="right">
                    <span className={`tag ${j.connected ? "ok" : ""}`}>
                      {j.connected ? "ONLINE" : "OFFLINE"}
                    </span>
                  </span>
                </h3>

                <div className="statcol">
                  <AgentOrb
                    size="md"
                    stateCls={orbCls}
                    pulse={orbPulse}
                    micLevel={j.micLevel}
                    voiceOn={j.voiceOn}
                  />

                  <div className="core-state-text">
                    <div className="num xl">{STATE_LABEL[j.state] || j.state}</div>
                    <div className="lbl">
                      {ap?.gemini_voice || "Voice"} ·{" "}
                      {j.voiceOn ? "live-аудио активно" : "нажмите для голоса"}
                      {toolCount > 0 && <> · вызовов: {toolCount}</>}
                    </div>
                  </div>

                  {/* Аудио-визуализатор */}
                  <div
                    className={`eq-bars ${
                      j.state === "SPEAKING"
                        ? "speaking"
                        : j.voiceOn
                        ? "listening"
                        : ""
                    }`}
                    style={
                      {
                        "--level": Math.max(0.15, Math.min(1, j.micLevel * 2.2)),
                      } as CSSProperties
                    }
                  >
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>
                </div>

                {j.stateNote && <div className="hint center">{j.stateNote}</div>}

                {/* Блок авторизации */}
                <div className="authblock" onClick={(e) => e.stopPropagation()}>
                  {auth?.method === "oauth" ? (
                    <div className="acc">
                      <span className="g">G</span>
                      <span className="acc-email">{auth.email || "Google-аккаунт"}</span>
                      <button
                        className="smallbtn"
                        style={{ marginLeft: "auto" }}
                        onClick={async () => {
                          await api.disconnectAuth();
                          await refreshAuth();
                        }}
                      >
                        Выйти
                      </button>
                    </div>
                  ) : auth?.method === "env_key" ? (
                    <div className="acc">
                      <span className="g">K</span>
                      <span>API-ключ задан в .env</span>
                    </div>
                  ) : auth?.method === "stored_key" ? (
                    <div className="acc">
                      <span className="g">K</span>
                      <span>API-ключ сохранён</span>
                      <button
                        className="smallbtn"
                        style={{ marginLeft: "auto" }}
                        onClick={async () => {
                          await api.disconnectAuth();
                          await refreshAuth();
                        }}
                      >
                        Удалить
                      </button>
                    </div>
                  ) : (
                    <>
                      {auth?.oauth_ready && (
                        <button
                          className="smallbtn accent full"
                          onClick={async () => {
                            const r = await api.googleAuthUrl();
                            window.location.href = r.url;
                          }}
                        >
                          Войти через Google
                        </button>
                      )}
                      <div className="keyrow">
                        <input
                          type="password"
                          placeholder={
                            auth?.oauth_ready
                              ? "или вставьте Gemini API-ключ"
                              : "Gemini API-ключ"
                          }
                          value={keyInput}
                          onChange={(e) => setKeyInput(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && submitApiKey()}
                        />
                        <button className="smallbtn accent" onClick={submitApiKey}>
                          OK
                        </button>
                      </div>
                      {!auth?.oauth_ready && (
                        <div className="hint">
                          Для входа через Google задайте GOOGLE_OAUTH_CLIENT_ID (см. README)
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>

              {/* Карточка памяти */}
              <div
                className="card widget clickable"
                onClick={() => setView("memory")}
              >
                <h3>
                  <span>Память</span>
                  <span className="right tag">
                    {ap?.memory_tokens || 0} / {ap?.memory_max_tokens || 0}
                  </span>
                </h3>
                <div className="statline">
                  <div className="num">
                    {memPct}
                    <span className="unit">%</span>
                  </div>
                  <div className="lbl">
                    долгосрочная память
                    <br />
                    {memoryFactsCount} фактов сохранено
                  </div>
                </div>
                <div className="meterbar">
                  <div className="meterfill" style={{ width: `${memPct}%` }} />
                </div>
                <div className="hint mem-preview">
                  {ap?.memory_text
                    ? ap.memory_text
                        .split("\n")
                        .filter(Boolean)
                        .slice(-2)
                        .join("\n")
                    : "Пока пусто — факты появятся по ходу диалогов"}
                </div>
              </div>

              {/* Карточка последних диалогов */}
              <div className="card widget sessions-mini">
                <h3>
                  <span>Диалоги</span>
                  <span className="right">
                    <button className="smallbtn" onClick={() => setView("sessions")}>
                      Все ({sessions.length})
                    </button>
                  </span>
                </h3>
                <div className="sess-scroll">
                  {sessions.length === 0 && (
                    <div className="empty">
                      Диалоги появятся после первого сообщения — пустые не сохраняются
                    </div>
                  )}
                  {sessions.slice(0, 6).map((s, i) => (
                    <div
                      key={s.id}
                      className={`sess ${s.id === j.sessionId ? "cur" : ""}`}
                      onClick={() => j.openSession(s.id)}
                    >
                      <span className="idx">{i + 1}</span>
                      <span className="ttl">{s.title || "Диалог"}</span>
                      <span className="t">{fmtTime(s.updated_at)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          </div>
        )}

        {/* ================= VIEW: PROFILES ================= */}
        {view === "profiles" && (
          <div
            className="dash"
            style={{ gridTemplateColumns: editing ? "1fr 400px" : "1fr" }}
          >
            <div className="pgrid">
              {profiles.map((p) => (
                <div key={p.id} className={`pcard ${p.id === ap?.id ? "cur" : ""}`}>
                  <div className="phead">
                    <AgentOrb
                      size="sm"
                      stateCls={p.id === ap?.id ? orbCls : ""}
                      voiceOn={p.id === ap?.id && j.voiceOn}
                    />
                    <div className="nm">
                      {p.display_name}
                      <small>
                        {p.gemini_voice} · {p.role_tag || "ассистент"}
                      </small>
                    </div>
                    <div className="right">
                      {p.is_builtin ? (
                        <span className="tag">PRESET</span>
                      ) : (
                        <span className="tag accent-tag">CUSTOM</span>
                      )}
                    </div>
                  </div>

                  <div className="togglerow">
                    <span>Веб-поиск</span>
                    <button
                      className={`toggle ${p.enable_web_search ? "on" : ""}`}
                      onClick={() =>
                        api
                          .updateProfile(p.id, {
                            enable_web_search: !p.enable_web_search,
                          })
                          .then(refresh)
                      }
                    />
                  </div>
                  <div className="togglerow">
                    <span>Долгосрочная память</span>
                    <button
                      className={`toggle ${p.enable_memory ? "on" : ""}`}
                      onClick={() =>
                        api
                          .updateProfile(p.id, { enable_memory: !p.enable_memory })
                          .then(refresh)
                      }
                    />
                  </div>

                  <div className="btnrow">
                    <button
                      className={`smallbtn ${p.id === ap?.id ? "active-state" : "accent"}`}
                      onClick={() => activate(p)}
                    >
                      {p.id === ap?.id ? "Активен" : "Активировать"}
                    </button>
                    <button className="smallbtn" onClick={() => setEditingId(p.id)}>
                      Настроить
                    </button>
                    {p.is_builtin ? (
                      <button className="smallbtn" onClick={() => resetProfile(p.id)}>
                        Сброс
                      </button>
                    ) : (
                      <button
                        className="smallbtn danger"
                        onClick={() => removeProfile(p.id)}
                      >
                        Удалить
                      </button>
                    )}
                  </div>
                </div>
              ))}

              <button className="pcard pcard-add" onClick={createProfile}>
                <span className="plus">+</span>
                <span>Создать новый профиль</span>
              </button>
            </div>

            {draft && (
              <div className="card editor-card">
                <h3>
                  <span>Настройка профиля</span>
                  <span className="right">
                    <button
                      className="smallbtn"
                      onClick={() => {
                        setEditingId(null);
                        setDraft(null);
                      }}
                    >
                      ✕
                    </button>
                  </span>
                </h3>

                <div className="editor-scroll">
                  <div className="field">
                    <label>Имя</label>
                    <input
                      type="text"
                      value={draft.display_name}
                      onChange={(e) =>
                        setDraft({ ...draft, display_name: e.target.value })
                      }
                    />
                  </div>
                  <div className="field">
                    <label>Роль</label>
                    <input
                      type="text"
                      value={draft.role_tag}
                      onChange={(e) =>
                        setDraft({ ...draft, role_tag: e.target.value })
                      }
                      placeholder="Напр. Технический ассистент"
                    />
                  </div>
                  <div className="field">
                    <label>Голос (Gemini Live)</label>
                    <select
                      value={draft.voice_id}
                      onChange={(e) =>
                        setDraft({ ...draft, voice_id: e.target.value })
                      }
                    >
                      {voices.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name} — {v.tone}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label>Системный промпт</label>
                    <textarea
                      value={draft.system_prompt}
                      onChange={(e) =>
                        setDraft({ ...draft, system_prompt: e.target.value })
                      }
                    />
                  </div>

                  <div className="togglerow">
                    <span>Веб-поиск</span>
                    <button
                      className={`toggle ${draft.enable_web_search ? "on" : ""}`}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          enable_web_search: !draft.enable_web_search,
                        })
                      }
                    />
                  </div>
                  <div className="togglerow">
                    <span>Память</span>
                    <button
                      className={`toggle ${draft.enable_memory ? "on" : ""}`}
                      onClick={() =>
                        setDraft({ ...draft, enable_memory: !draft.enable_memory })
                      }
                    />
                  </div>
                  <div className="togglerow">
                    <span>Задачи (плагины)</span>
                    <button
                      className={`toggle ${draft.enable_tasks ? "on" : ""}`}
                      onClick={() =>
                        setDraft({ ...draft, enable_tasks: !draft.enable_tasks })
                      }
                    />
                  </div>
                </div>

                <div className="btnrow">
                  <button className="smallbtn accent" onClick={saveDraft}>
                    Сохранить изменения
                  </button>
                  <button
                    className="smallbtn"
                    onClick={() => {
                      setEditingId(null);
                      setDraft(null);
                    }}
                  >
                    Отмена
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ================= VIEW: MEMORY ================= */}
        {view === "memory" && (
          <div className="dash" style={{ gridTemplateColumns: "1fr" }}>
            <div className="card memory-full">
              <h3>
                <span>Долгосрочная память — {ap?.display_name}</span>
                <span className="right tag">
                  {ap?.memory_tokens || 0} / {ap?.memory_max_tokens || 0} токенов ({memPct}%)
                </span>
              </h3>
              <div className="meterbar" style={{ marginBottom: 16 }}>
                <div className="meterfill" style={{ width: `${memPct}%` }} />
              </div>
              <div className="field memory-field">
                <textarea
                  value={memoryDraft}
                  onChange={(e) => {
                    setMemoryDraft(e.target.value);
                    setMemDirty(true);
                  }}
                  placeholder="- Факты о пользователе, по строке на факт…"
                />
              </div>
              <div className="btnrow">
                <button
                  className="smallbtn accent"
                  onClick={async () => {
                    if (!ap) return;
                    await api.updateMemory(ap.id, {
                      mode: "replace",
                      text: memoryDraft,
                    });
                    setMemDirty(false);
                    await refresh();
                  }}
                >
                  Сохранить (replace)
                </button>
                <button
                  className="smallbtn"
                  onClick={async () => {
                    if (!ap || !memoryDraft.trim()) return;
                    await api.updateMemory(ap.id, {
                      mode: "append",
                      text: memoryDraft,
                    });
                    setMemDirty(false);
                    await refresh();
                  }}
                >
                  Добавить (append)
                </button>
                <button
                  className="smallbtn danger"
                  onClick={async () => {
                    if (!ap || !confirm("Очистить память профиля?")) return;
                    await api.clearMemory(ap.id);
                    setMemDirty(false);
                    await refresh();
                  }}
                >
                  Очистить память
                </button>
              </div>
              <div className="hint">
                Авто-экстрактор дополняет память после каждого диалога. Append — добавить строки,
                replace — перезаписать целиком.
              </div>
            </div>
          </div>
        )}

        {/* ================= VIEW: SESSIONS ================= */}
        {view === "sessions" && (
          <div className="dash" style={{ gridTemplateColumns: "1fr" }}>
            <div className="card sessions-full">
              <h3>
                <span>История диалогов ({sessions.length})</span>
                <div className="right sessions-actions">
                  <input
                    className="search-input"
                    type="text"
                    placeholder="Поиск по диалогам…"
                    value={sessionSearch}
                    onChange={(e) => setSessionSearch(e.target.value)}
                  />
                  <button
                    className="smallbtn accent"
                    onClick={() => {
                      j.newSession();
                      setView("chat");
                    }}
                  >
                    + Новый диалог
                  </button>
                </div>
              </h3>
              <div className="sess-scroll full">
                {filteredSessions.length === 0 && (
                  <div className="empty">
                    {sessions.length === 0
                      ? "Пока ни одного диалога"
                      : "Ничего не найдено по запросу"}
                  </div>
                )}
                {filteredSessions.map((s, i) => (
                  <div
                    key={s.id}
                    className={`sess ${s.id === j.sessionId ? "cur" : ""}`}
                    onClick={() => {
                      j.openSession(s.id);
                      setView("chat");
                    }}
                  >
                    <span className="idx">{i + 1}</span>
                    <span className="ttl">{s.title || "Диалог"}</span>
                    <span className="t">
                      {s.status} · {fmtTime(s.updated_at)}
                    </span>
                    <button
                      className="x"
                      title="Удалить"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm("Удалить диалог?"))
                          api.deleteSession(s.id).then(refresh);
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}