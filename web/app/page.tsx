"use client";

import {
  ChangeEvent,
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
import {
  AtmosphericBackdrop,
  SCENE_PRESETS,
  SceneId,
} from "@/components/AtmosphericBackdrop";
import { HorizonWave } from "@/components/HorizonWave";

type View = "chat" | "profiles" | "memory" | "sessions";
type PopoverId = "profiles" | "atmosphere" | "account" | null;

const TINT_PRESETS = [
  { id: "mist", name: "Штормовой", hex: "#9dd9e5" },
  { id: "aurora", name: "Аврора", hex: "#7de2d1" },
  { id: "dawn", name: "Рассвет", hex: "#f3c7a2" },
  { id: "lunar", name: "Лунный", hex: "#b8d0eb" },
  { id: "pearl", name: "Жемчуг", hex: "#e5ecf2" },
];

const STORAGE_SCENE = "jarvis_spatial_scene";
const STORAGE_CUSTOM_PHOTO = "jarvis_spatial_custom_photo";
const STORAGE_TINT = "jarvis_spatial_tint";
const STORAGE_DIM = "jarvis_spatial_dim";
const STORAGE_CINEMA = "jarvis_spatial_cinema";

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

function applyAccentTint(hex: string) {
  const root = document.documentElement;
  const { r, g, b } = hexToRgb(hex);
  root.style.setProperty("--accent", hex);
  root.style.setProperty("--accent-rgb", `${r}, ${g}, ${b}`);
}

const STATE_LABEL: Record<string, string> = {
  IDLE: "Готов",
  STANDBY: "Готов",
  CONNECTING: "Подключение",
  LISTENING: "Слушаю",
  THINKING: "Думаю",
  SPEAKING: "Говорю",
  ERROR: "Ошибка",
};

const NAV: { id: View; label: string; icon: ReactNode }[] = [
  {
    id: "chat",
    label: "Пространство чата",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <rect x="4" y="4" width="6.5" height="6.5" rx="1.8" />
        <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8" />
        <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8" />
        <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8" />
      </svg>
    ),
  },
  {
    id: "profiles",
    label: "Профили агента",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <circle cx="12" cy="8.5" r="3.6" />
        <path
          d="M5 19.5c1.5-3.4 4-5.2 7-5.2s5.5 1.8 7 5.2"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    id: "memory",
    label: "Долгосрочная память",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <circle cx="12" cy="12" r="8.2" />
        <path d="M12 3.8a13 13 0 0 1 0 16.4M12 3.8a13 13 0 0 0 0 16.4M4.4 9.5h15.2M4.4 14.5h15.2" />
      </svg>
    ),
  },
  {
    id: "sessions",
    label: "История диалогов",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <rect x="4" y="5" width="16" height="14" rx="3" />
        <path d="M8 9.5h8M8 13.5h5" strokeLinecap="round" />
      </svg>
    ),
  },
];

const EMBLEM_ICON = (
  <svg viewBox="0 0 36 36" fill="none">
    <circle cx="18" cy="18" r="14" stroke="currentColor" strokeWidth="1.2" opacity="0.35" />
    <path
      d="M7 13.5c3.2-2.2 6.8-2.2 10.5 0s7.3 2.2 11.5 0"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
    />
    <path
      d="M5.5 18c3.6-2.4 7.6-2.4 12 0s8.4 2.4 13 0"
      stroke="currentColor"
      strokeWidth="2.1"
      strokeLinecap="round"
    />
    <path
      d="M7 22.5c3.2-2.2 6.8-2.2 10.5 0s7.3 2.2 11.5 0"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
    />
  </svg>
);

const MIC_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.85">
    <rect x="9" y="3.5" width="6" height="10.5" rx="3" />
    <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" strokeLinecap="round" />
  </svg>
);

const STOP_ICON = (
  <svg viewBox="0 0 24 24" fill="currentColor">
    <rect x="7" y="7" width="10" height="10" rx="2.5" />
  </svg>
);

const SEND_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const PLUS_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9">
    <path d="M12 5v14M5 12h14" strokeLinecap="round" />
  </svg>
);

const SCENERY_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
    <circle cx="12" cy="12" r="4" />
    <path
      d="M12 3v2M12 19v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M3 12h2M19 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
      strokeLinecap="round"
    />
  </svg>
);

const PERSONA_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
    <path
      d="M12 3.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM5 20c1.2-3.4 3.7-5 7-5s5.8 1.6 7 5"
      strokeLinecap="round"
    />
  </svg>
);

function fmtTime(t?: number | string) {
  if (!t) return "";
  const d = typeof t === "number" ? new Date(t * 1000) : new Date(t);
  return `${d.getDate().toString().padStart(2, "0")}.${(d.getMonth() + 1)
    .toString()
    .padStart(2, "0")} · ${d.getHours().toString().padStart(2, "0")}:${d
    .getMinutes()
    .toString()
    .padStart(2, "0")}`;
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
  const [now, setNow] = useState<Date | null>(null);

  // Spatial Atmosphere & Floating Glass controls
  const [sceneId, setSceneId] = useState<SceneId>("storm-horizon");
  const [customPhoto, setCustomPhoto] = useState<string | null>(null);
  const [backdropUrl, setBackdropUrl] = useState<string>("");
  const [tint, setTint] = useState<string>("#9dd9e5");
  const [dimLevel, setDimLevel] = useState<number>(38);
  const [cinemaMode, setCinemaMode] = useState<boolean>(false);
  const [openPopover, setOpenPopover] = useState<PopoverId>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const [parallax, setParallax] = useState({ x: 0, y: 0 });

  const scrollRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const confirmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate spatial preferences
  useEffect(() => {
    try {
      const savedScene = localStorage.getItem(STORAGE_SCENE) as SceneId | null;
      const savedPhoto = localStorage.getItem(STORAGE_CUSTOM_PHOTO);
      const savedTint = localStorage.getItem(STORAGE_TINT);
      const savedDim = localStorage.getItem(STORAGE_DIM);
      const savedCinema = localStorage.getItem(STORAGE_CINEMA);

      if (savedPhoto) setCustomPhoto(savedPhoto);
      if (
        savedScene &&
        (savedScene === "custom" ||
          SCENE_PRESETS.some((s) => s.id === savedScene))
      ) {
        if (savedScene === "custom" && !savedPhoto) {
          setSceneId("storm-horizon");
        } else {
          setSceneId(savedScene);
        }
      }
      if (savedTint && /^#[0-9a-fA-F]{6}$/.test(savedTint)) setTint(savedTint);
      if (savedDim !== null) {
        const parsed = Number(savedDim);
        if (!Number.isNaN(parsed)) setDimLevel(Math.max(0, Math.min(100, parsed)));
      }
      if (savedCinema === "1") setCinemaMode(true);
    } catch {}
  }, []);

  useEffect(() => {
    applyAccentTint(tint);
    try {
      localStorage.setItem(STORAGE_SCENE, sceneId);
      localStorage.setItem(STORAGE_TINT, tint);
      localStorage.setItem(STORAGE_DIM, String(dimLevel));
      localStorage.setItem(STORAGE_CINEMA, cinemaMode ? "1" : "0");
    } catch {}
  }, [sceneId, tint, dimLevel, cinemaMode]);

  // Close popovers on outside click or Escape
  useEffect(() => {
    if (!openPopover) return;
    function onDown(e: MouseEvent) {
      if (headerRef.current && !headerRef.current.contains(e.target as Node)) {
        setOpenPopover(null);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpenPopover(null);
    }
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [openPopover]);

  // Gentle GPU parallax following cursor
  useEffect(() => {
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    let raf = 0;
    let targetX = 0;
    let targetY = 0;
    const onMove = (e: MouseEvent) => {
      targetX = (e.clientX / window.innerWidth - 0.5) * 2;
      targetY = (e.clientY / window.innerHeight - 0.5) * 2;
      if (!raf) {
        raf = requestAnimationFrame(() => {
          setParallax({ x: targetX, y: targetY });
          raf = 0;
        });
      }
    };
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => {
      window.removeEventListener("mousemove", onMove);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

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
    const clock = setInterval(() => setNow(new Date()), 20000);
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
    return sessions.filter((s) =>
      (s.title || "Диалог").toLowerCase().includes(q)
    );
  }, [sessions, sessionSearch]);

  const memoryFactsCount = useMemo(
    () => ap?.memory_text?.split("\n").filter((l) => l.trim()).length || 0,
    [ap?.memory_text]
  );

  const memPct = ap
    ? Math.min(
        100,
        Math.round((ap.memory_tokens / Math.max(1, ap.memory_max_tokens)) * 100)
      )
    : 0;

  const hasConversation =
    j.messages.length > 0 || Boolean(j.liveUser) || Boolean(j.liveAgent);

  // Safe two-step inline confirmation (no window.confirm)
  function runWithConfirm(key: string, action: () => void | Promise<void>) {
    if (confirmKey === key) {
      setConfirmKey(null);
      if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
      void action();
      return;
    }
    setConfirmKey(key);
    if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
    confirmTimerRef.current = setTimeout(() => setConfirmKey(null), 3500);
  }

  function send() {
    const t = input.trim();
    if (!t) return;
    setInput("");
    j.sendChat(t);
  }

  function toggleVoice() {
    if (j.voiceOn) j.stopVoice();
    else j.startVoice();
  }

  function handleSelectScene(id: Exclude<SceneId, "custom">) {
    setSceneId(id);
    const preset = SCENE_PRESETS.find((s) => s.id === id);
    if (preset) setTint(preset.defaultTint);
  }

  function handlePhotoUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const src = typeof reader.result === "string" ? reader.result : null;
      if (!src) return;
      // Downscale gracefully to fit localStorage comfortably while remaining ultra-crisp
      const img = new Image();
      img.onload = () => {
        const maxW = 1920;
        const scale = img.width > maxW ? maxW / img.width : 1;
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          const optimized = canvas.toDataURL("image/jpeg", 0.86);
          setCustomPhoto(optimized);
          setSceneId("custom");
          try {
            localStorage.setItem(STORAGE_CUSTOM_PHOTO, optimized);
          } catch {}
        }
      };
      img.src = src;
    };
    reader.readAsDataURL(file);
    e.target.value = "";
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
    await api.deleteProfile(id);
    if (editingId === id) {
      setEditingId(null);
      setDraft(null);
    }
    await refresh();
  }

  async function resetProfile(id: string) {
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
    await api.saveApiKey(keyInput.trim());
    setKeyInput("");
    await refreshAuth();
  }

  const timeString = now
    ? now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    : "—:—";

  const dateString = now
    ? now.toLocaleDateString("ru-RU", {
        weekday: "long",
        day: "numeric",
        month: "long",
      })
    : "";

  const heroTitle =
    j.state === "LISTENING"
      ? "Слушаю вас…"
      : j.state === "SPEAKING"
      ? `${ap?.display_name || "Jarvis"} отвечает`
      : j.state === "THINKING"
      ? "Собираю ответ…"
      : "Чем помочь сегодня?";

  const userInitial = auth?.email
    ? auth.email[0].toUpperCase()
    : auth?.method
    ? "K"
    : "J";

  return (
    <div className={`spatial-viewport ${cinemaMode ? "cinema" : ""}`}>
      {/* Soft misty ambient halo outside the floating panoramic window */}
      {!cinemaMode && backdropUrl && (
        <div
          className="outer-mist-photo"
          style={{ backgroundImage: `url(${backdropUrl})` }}
          aria-hidden="true"
        />
      )}
      {!cinemaMode && <div className="outer-mist-veil" aria-hidden="true" />}

      {/* Main Rounded Floating Spatial Stage Window */}
      <main className="stage-window">
        <AtmosphericBackdrop
          sceneId={sceneId}
          customPhoto={customPhoto}
          dimLevel={dimLevel}
          voiceOn={j.voiceOn}
          micLevel={j.micLevel}
          parallax={parallax}
          onBackdropUrl={setBackdropUrl}
        />

        {/* ==================== Floating Left Vertical Glass Capsule Dock ==================== */}
        <nav className="floating-dock" aria-label="Основная навигация">
          <button
            className="dock-emblem"
            onClick={() => setView("chat")}
            aria-label="На главный экран Jarvis"
          >
            {EMBLEM_ICON}
          </button>

          <div className="dock-nav">
            {NAV.map((item) => (
              <button
                key={item.id}
                className={`dock-btn ${view === item.id ? "active" : ""}`}
                onClick={() => setView(item.id)}
                aria-label={item.label}
                aria-current={view === item.id ? "page" : undefined}
              >
                {item.icon}
                <span className="dock-tooltip">{item.label}</span>
              </button>
            ))}
          </div>

          <div className="dock-spacer" />

          <button
            className={`dock-voice-btn ${j.voiceOn ? "live" : ""}`}
            onClick={toggleVoice}
            aria-label={
              j.voiceOn ? "Остановить голосовой режим" : "Включить голосовой режим"
            }
          >
            {j.voiceOn ? STOP_ICON : MIC_ICON}
            <span className="dock-tooltip">
              {j.voiceOn ? "Остановить голос" : "Голосовой эфир"}
            </span>
          </button>
        </nav>

        {/* ==================== Foreground Content Shell ==================== */}
        <div className="stage-shell">
          {/* Spatial Floating Header */}
          <header className="spatial-header" ref={headerRef}>
            <div className="welcome-identity">
              <span className="welcome-kicker">
                {j.voiceOn
                  ? `Голосовой эфир · ${STATE_LABEL[j.state] || j.state}`
                  : "Добро пожаловать"}
              </span>
              <div className="welcome-name-row">
                <span className="welcome-name">
                  {ap?.display_name || "Jarvis"}
                </span>
                <span className="welcome-meta">
                  {ap
                    ? `${ap.gemini_voice} · ${ap.role_tag || "Личный ассистент"}`
                    : j.connected
                    ? "Подключён"
                    : "Ожидание сервера"}
                </span>
              </div>
            </div>

            {/* Top-Right Floating Circular Glass Orbs */}
            <div className="header-orbs">
              <button
                className="glass-orb-btn"
                onClick={() => {
                  j.newSession();
                  setView("chat");
                }}
                title="Новый диалог"
                aria-label="Новый диалог"
              >
                {PLUS_ICON}
              </button>

              {/* Profile Quick Switcher Orb */}
              <div className="orb-anchor">
                <button
                  className={`glass-orb-btn ${
                    openPopover === "profiles" ? "open" : ""
                  }`}
                  onClick={() =>
                    setOpenPopover((v) => (v === "profiles" ? null : "profiles"))
                  }
                  title="Сменить профиль"
                  aria-label="Сменить профиль"
                >
                  {PERSONA_ICON}
                </button>

                {openPopover === "profiles" && (
                  <div className="glass-popover">
                    <div className="pop-title-row">
                      <span className="pop-title">Профиль ассистента</span>
                      <button
                        className="link-quiet"
                        onClick={() => {
                          setOpenPopover(null);
                          setView("profiles");
                        }}
                      >
                        Все
                      </button>
                    </div>
                    <div className="profile-pop-list">
                      {profiles.length === 0 && (
                        <div className="pop-caption">
                          Профили появятся после подключения к серверу.
                        </div>
                      )}
                      {profiles.map((p) => (
                        <button
                          key={p.id}
                          className={`profile-pop-item ${
                            p.id === ap?.id ? "active" : ""
                          }`}
                          onClick={() => {
                            activate(p);
                            setOpenPopover(null);
                          }}
                        >
                          <div>
                            <div className="profile-pop-name">
                              {p.display_name}
                            </div>
                            <div className="profile-pop-sub">
                              {p.gemini_voice} · {p.role_tag || "Ассистент"}
                            </div>
                          </div>
                          {p.id === ap?.id && (
                            <span className="pop-caption">Активен</span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Atmosphere & Glass Studio Orb */}
              <div className="orb-anchor">
                <button
                  className={`glass-orb-btn ${
                    openPopover === "atmosphere" ? "open" : ""
                  }`}
                  onClick={() =>
                    setOpenPopover((v) =>
                      v === "atmosphere" ? null : "atmosphere"
                    )
                  }
                  title="Атмосфера и глубина"
                  aria-label="Атмосфера и глубина"
                >
                  {SCENERY_ICON}
                </button>

                {openPopover === "atmosphere" && (
                  <div className="glass-popover">
                    <div className="pop-title-row">
                      <span className="pop-title">Атмосфера мира</span>
                      <span className="pop-caption">
                        {cinemaMode ? "Полный экран" : "Парящее окно"}
                      </span>
                    </div>

                    <div className="scene-grid">
                      {SCENE_PRESETS.map((s) => (
                        <button
                          key={s.id}
                          className={`scene-tile ${
                            sceneId === s.id ? "active" : ""
                          }`}
                          style={{ background: s.previewGradient }}
                          onClick={() => handleSelectScene(s.id)}
                        >
                          <span className="scene-tile-name">{s.name}</span>
                        </button>
                      ))}
                    </div>

                    <div className="upload-row">
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        onChange={handlePhotoUpload}
                        style={{ display: "none" }}
                      />
                      <button
                        className="glass-btn full"
                        onClick={() => fileInputRef.current?.click()}
                      >
                        {customPhoto
                          ? "Заменить своё фото фона"
                          : "Загрузить своё фото"}
                      </button>
                      {customPhoto && sceneId !== "custom" && (
                        <button
                          className="glass-btn"
                          onClick={() => setSceneId("custom")}
                        >
                          Моё
                        </button>
                      )}
                    </div>

                    <div className="pop-section-label">Отображение окна</div>
                    <div className="segmented-glass">
                      <button
                        className={!cinemaMode ? "active" : ""}
                        onClick={() => setCinemaMode(false)}
                      >
                        Парящее окно
                      </button>
                      <button
                        className={cinemaMode ? "active" : ""}
                        onClick={() => setCinemaMode(true)}
                      >
                        Весь экран
                      </button>
                    </div>

                    <div className="pop-section-label">
                      Глубина затемнения ·{" "}
                      <span className="tabular">{dimLevel}%</span>
                    </div>
                    <div className="slider-row">
                      <input
                        type="range"
                        min={5}
                        max={85}
                        value={dimLevel}
                        onChange={(e) => setDimLevel(Number(e.target.value))}
                        aria-label="Глубина затемнения фона"
                      />
                    </div>

                    <div className="pop-section-label">Свечение стекла</div>
                    <div className="tint-swatches">
                      {TINT_PRESETS.map((c) => (
                        <button
                          key={c.id}
                          className={`tint-dot ${
                            tint.toLowerCase() === c.hex ? "active" : ""
                          }`}
                          style={{ background: c.hex }}
                          onClick={() => setTint(c.hex)}
                          title={c.name}
                          aria-label={c.name}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Account / Auth Glass Orb */}
              <div className="orb-anchor">
                <button
                  className={`glass-orb-btn avatar-orb ${
                    openPopover === "account" ? "open" : ""
                  } ${auth && !auth.method ? "needs-auth" : ""}`}
                  onClick={() =>
                    setOpenPopover((v) => (v === "account" ? null : "account"))
                  }
                  title="Аккаунт и подключение Gemini"
                  aria-label="Аккаунт и подключение Gemini"
                >
                  {userInitial}
                </button>

                {openPopover === "account" && (
                  <div className="glass-popover">
                    <div className="pop-title-row">
                      <span className="pop-title">Подключение Gemini</span>
                      <span className="pop-caption">
                        {j.connected ? "Сервер онлайн" : "Нет связи"}
                      </span>
                    </div>

                    {auth?.method === "oauth" ? (
                      <div className="profile-pop-list">
                        <div className="profile-pop-name">
                          {auth.email || "Google-аккаунт"}
                        </div>
                        <div className="profile-pop-sub">
                          Авторизация через Google OAuth активна
                        </div>
                        <button
                          className="glass-btn danger full"
                          style={{ marginTop: 10 }}
                          onClick={async () => {
                            await api.disconnectAuth();
                            await refreshAuth();
                          }}
                        >
                          Выйти из аккаунта
                        </button>
                      </div>
                    ) : auth?.method === "env_key" ? (
                      <div className="profile-pop-sub">
                        Ключ Gemini API подключён из файла .env
                      </div>
                    ) : auth?.method === "stored_key" ? (
                      <div className="profile-pop-list">
                        <div className="profile-pop-name">API-ключ сохранён</div>
                        <button
                          className="glass-btn danger full"
                          style={{ marginTop: 10 }}
                          onClick={async () => {
                            await api.disconnectAuth();
                            await refreshAuth();
                          }}
                        >
                          Удалить сохранённый ключ
                        </button>
                      </div>
                    ) : (
                      <div className="profile-pop-list">
                        {auth?.oauth_ready && (
                          <button
                            className="glass-btn primary full"
                            onClick={async () => {
                              const r = await api.googleAuthUrl();
                              window.location.href = r.url;
                            }}
                          >
                            Войти через Google
                          </button>
                        )}
                        <div className="key-inline" style={{ marginTop: 6 }}>
                          <input
                            className="glass-input"
                            type="password"
                            placeholder="Gemini API-ключ"
                            value={keyInput}
                            onChange={(e) => setKeyInput(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && submitApiKey()}
                          />
                          <button
                            className="glass-btn primary"
                            onClick={submitApiKey}
                          >
                            OK
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </header>

          {/* ==================== VIEW: CHAT (Spatial Panoramic Stage) ==================== */}
          {view === "chat" && (
            <div className="workspace-grid">
              {/* Left / Center Expansive Stage */}
              <section className="main-stage">
                <div
                  className={`chat-stage-body ${
                    hasConversation ? "has-messages" : ""
                  }`}
                >
                  {!hasConversation ? (
                    <div className="hero-atmosphere">
                      <div className="hero-top-copy">
                        <div className="hero-eyebrow">
                          <span>{dateString || "Сегодня"}</span>
                          <span aria-hidden="true">·</span>
                          <span className="tabular">{timeString}</span>
                          <span aria-hidden="true">·</span>
                          <span>{STATE_LABEL[j.state] || j.state}</span>
                        </div>
                        <h1 className="hero-headline">{heroTitle}</h1>
                        <p className="hero-subcopy">
                          {j.micError
                            ? `Микрофон недоступен: ${j.micError}`
                            : j.stateNote
                            ? j.stateNote
                            : `${
                                ap?.display_name || "Jarvis"
                              } на связи — живой голос, долгосрочная память и поиск в сети. Начните голосом или напишите ниже.`}
                        </p>
                      </div>

                      {/* Signature luminous horizon wave curve with starlight node */}
                      <div className="hero-wave-band">
                        <HorizonWave
                          state={j.state}
                          voiceOn={j.voiceOn}
                          micLevel={j.micLevel}
                        />
                      </div>

                      <div className="hero-prompts">
                        {[
                          "Что нового сегодня?",
                          "Расскажи, что ты умеешь",
                          "Запомни: я работаю над JarvisPC",
                        ].map((promptText) => (
                          <button
                            key={promptText}
                            className="prompt-glass-btn"
                            onClick={() => j.sendChat(promptText)}
                          >
                            <span>{promptText}</span>
                            <span className="prompt-arrow" aria-hidden="true">
                              →
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="transcript-bar">
                        <div className="transcript-meta">
                          {j.voiceOn && <span className="live-signal-dot" />}
                          <span>
                            {j.voiceOn
                              ? j.micLevel > 0.02
                                ? "Голосовой эфир · слышу вас"
                                : "Голосовой эфир · ожидаю речь"
                              : j.micError
                              ? `Микрофон: ${j.micError}`
                              : `${ap?.display_name || "Jarvis"} · активный диалог`}
                          </span>
                        </div>
                        <button className="glass-btn" onClick={j.newSession}>
                          Новый диалог
                        </button>
                      </div>

                      <div className="transcript-scroll" ref={scrollRef}>
                        {j.messages.map((m) =>
                          m.role === "TOOL" ? (
                            <div key={m.id} className="msg-tool mono">
                              <span>Инструмент</span>
                              <span aria-hidden="true">·</span>
                              <span>{m.text}</span>
                            </div>
                          ) : m.role === "SYSTEM" ? (
                            <div key={m.id} className="msg-system">
                              {m.text}
                            </div>
                          ) : (
                            <div
                              key={m.id}
                              className={`msg-bubble ${
                                m.role === "USER" ? "user" : "agent"
                              }`}
                            >
                              <span className="msg-sender">
                                {m.role === "USER"
                                  ? "Вы"
                                  : ap?.display_name || "Jarvis"}
                              </span>
                              <div>{m.text}</div>
                            </div>
                          )
                        )}

                        {j.liveUser && (
                          <div className="msg-bubble user live">
                            <span className="msg-sender">Вы · эфир</span>
                            <div>{j.liveUser}</div>
                          </div>
                        )}

                        {j.liveAgent && (
                          <div className="msg-bubble agent live">
                            <span className="msg-sender">
                              {ap?.display_name || "Jarvis"} · эфир
                            </span>
                            <div>{j.liveAgent.text}</div>
                          </div>
                        )}

                        {j.state === "THINKING" && (
                          <div className="msg-bubble agent live">
                            <span className="msg-sender">
                              {ap?.display_name || "Jarvis"}
                            </span>
                            <div className="typing-wave" aria-label="Думает">
                              <span />
                              <span />
                              <span />
                            </div>
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>

                {/* Floating Liquid-Glass Command Capsule */}
                <div className="command-bar-wrap">
                  <div className="command-bar">
                    <button
                      className={`cmd-orb ${j.voiceOn ? "mic-live" : ""}`}
                      onClick={toggleVoice}
                      title={
                        j.voiceOn
                          ? "Выключить голосовой режим"
                          : "Включить голосовой режим"
                      }
                      aria-label={
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
                      placeholder={`Спросите ${ap?.display_name || "Jarvis"}…`}
                    />
                    <button
                      className="cmd-orb send"
                      onClick={send}
                      disabled={!input.trim()}
                      title="Отправить сообщение"
                      aria-label="Отправить сообщение"
                    >
                      {SEND_ICON}
                    </button>
                  </div>
                </div>
              </section>

              {/* Right Floating Frosted Glass Stack */}
              <aside className="right-stack" aria-label="Состояние и быстрый доступ">
                {/* Hero Voice Core Frosted Card (mirrors main focal glass card in reference) */}
                <button
                  type="button"
                  className={`glass-hero-card ${j.voiceOn ? "live" : ""}`}
                  onClick={toggleVoice}
                >
                  <div className="hero-card-top">
                    <span className="hero-card-loc">
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.8"
                      >
                        <circle cx="12" cy="12" r="9" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                      <span>{ap?.display_name || "Jarvis"}</span>
                    </span>
                    <span className="tabular">
                      {j.connected ? "Онлайн" : "Офлайн"}
                    </span>
                  </div>

                  <div className="hero-card-main">
                    <div>
                      <div className="hero-big-figure tabular">
                        {j.voiceOn ? STATE_LABEL[j.state] || j.state : timeString}
                      </div>
                      <div className="hero-state-caption">
                        {j.voiceOn
                          ? "Нажмите, чтобы завершить эфир"
                          : `${STATE_LABEL[j.state] || j.state} · нажмите для голоса`}
                      </div>
                    </div>

                    <div
                      className={`mini-eq ${
                        j.state === "SPEAKING"
                          ? "speaking"
                          : j.voiceOn
                          ? "listening"
                          : ""
                      }`}
                      style={
                        {
                          "--level": Math.max(0.18, Math.min(1, j.micLevel * 2.4)),
                        } as CSSProperties
                      }
                      aria-hidden="true"
                    >
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                    </div>
                  </div>

                  <div className="hero-metrics-strip">
                    <span className="metric-pair">
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.8"
                      >
                        <path d="M12 4v16M8 8v8M16 9v6" strokeLinecap="round" />
                      </svg>
                      <span>{ap?.gemini_voice || "Голос"}</span>
                    </span>
                    <span className="metric-pair tabular">
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.8"
                      >
                        <path
                          d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"
                          strokeLinejoin="round"
                        />
                      </svg>
                      <span>{toolCount} инстр.</span>
                    </span>
                    <span className="metric-pair tabular">
                      <span>{sessions.length} диал.</span>
                    </span>
                  </div>
                </button>

                {/* Inline Auth Card when unauthenticated */}
                {auth && !auth.method && (
                  <div className="auth-glass-card">
                    <div className="sub-card-kicker">Подключение к Gemini</div>
                    {auth.oauth_ready && (
                      <button
                        className="glass-btn primary full"
                        onClick={async () => {
                          const r = await api.googleAuthUrl();
                          window.location.href = r.url;
                        }}
                      >
                        Войти через Google
                      </button>
                    )}
                    <div className="key-inline">
                      <input
                        className="glass-input"
                        type="password"
                        placeholder={
                          auth.oauth_ready
                            ? "или Gemini API-ключ"
                            : "Gemini API-ключ"
                        }
                        value={keyInput}
                        onChange={(e) => setKeyInput(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && submitApiKey()}
                      />
                      <button
                        className="glass-btn primary"
                        onClick={submitApiKey}
                      >
                        OK
                      </button>
                    </div>
                  </div>
                )}

                {/* Stacked Frosted Memory Card */}
                <button
                  type="button"
                  className="glass-sub-card"
                  onClick={() => setView("memory")}
                >
                  <div className="sub-card-left">
                    <div className="sub-card-kicker">Долгосрочная память</div>
                    <div className="sub-card-title">
                      {memoryFactsCount > 0
                        ? `${memoryFactsCount} сохранённых фактов`
                        : "Память пока пуста"}
                    </div>
                    <div className="sub-card-sub tabular">
                      {ap?.memory_tokens || 0} / {ap?.memory_max_tokens || 4000}{" "}
                      токенов
                    </div>
                    <div className="thin-meter">
                      <div
                        className="thin-meter-fill"
                        style={{ width: `${memPct}%` }}
                      />
                    </div>
                  </div>
                  <div className="sub-card-figure tabular">{memPct}%</div>
                </button>

                {/* Recent Sessions Stacked Glass Cards */}
                <div className="stack-section-row">
                  <span>Недавние диалоги</span>
                  <button
                    className="link-quiet"
                    onClick={() => setView("sessions")}
                  >
                    Все ({sessions.length})
                  </button>
                </div>

                {sessions.length === 0 ? (
                  <div
                    className="glass-sub-card"
                    style={{ cursor: "default" }}
                  >
                    <div className="sub-card-left">
                      <div className="sub-card-kicker">История</div>
                      <div className="sub-card-title">Нет сохранённых бесед</div>
                      <div className="sub-card-sub">
                        Появятся после первого сообщения
                      </div>
                    </div>
                  </div>
                ) : (
                  sessions.slice(0, 3).map((s, idx) => (
                    <button
                      type="button"
                      key={s.id}
                      className={`glass-sub-card ${
                        s.id === j.sessionId ? "active" : ""
                      }`}
                      onClick={() => j.openSession(s.id)}
                    >
                      <div className="sub-card-left">
                        <div className="sub-card-kicker tabular">
                          {fmtTime(s.updated_at)}
                        </div>
                        <div className="sub-card-title">
                          {s.title || "Новый диалог"}
                        </div>
                        <div className="sub-card-sub">
                          {s.id === j.sessionId
                            ? "Открыт сейчас"
                            : "Нажмите, чтобы продолжить"}
                        </div>
                      </div>
                      <div className="sub-card-figure tabular">
                        0{idx + 1}
                      </div>
                    </button>
                  ))
                )}
              </aside>
            </div>
          )}

          {/* ==================== VIEW: PROFILES ==================== */}
          {view === "profiles" && (
            <div
              className={`workspace-grid ${
                draft ? "split-editor" : "single"
              }`}
            >
              <section className="glass-panel">
                <div className="panel-header">
                  <div>
                    <h1 className="panel-title">Профили ассистента</h1>
                    <div className="panel-subtitle">
                      Персоны с собственным голосом, памятью и системным характером
                    </div>
                  </div>
                  <div className="panel-actions">
                    <button className="glass-btn primary" onClick={createProfile}>
                      Создать профиль
                    </button>
                  </div>
                </div>

                <div className="profiles-grid">
                  {profiles.map((p) => (
                    <article
                      key={p.id}
                      className={`persona-card ${
                        p.id === ap?.id ? "active" : ""
                      }`}
                    >
                      <div className="persona-head">
                        <div>
                          <div className="persona-name">{p.display_name}</div>
                          <div className="persona-meta">
                            {p.gemini_voice} · {p.role_tag || "Ассистент"} ·{" "}
                            {p.is_builtin ? "Пресет" : "Свой"}
                          </div>
                        </div>
                      </div>

                      <div className="persona-toggles">
                        <div className="toggle-line">
                          <span>Веб-поиск</span>
                          <button
                            type="button"
                            className={`glass-switch ${
                              p.enable_web_search ? "on" : ""
                            }`}
                            onClick={() =>
                              api
                                .updateProfile(p.id, {
                                  enable_web_search: !p.enable_web_search,
                                })
                                .then(refresh)
                            }
                            aria-label={`Веб-поиск для ${p.display_name}`}
                            aria-pressed={p.enable_web_search}
                          />
                        </div>
                        <div className="toggle-line">
                          <span>Долгосрочная память</span>
                          <button
                            type="button"
                            className={`glass-switch ${
                              p.enable_memory ? "on" : ""
                            }`}
                            onClick={() =>
                              api
                                .updateProfile(p.id, {
                                  enable_memory: !p.enable_memory,
                                })
                                .then(refresh)
                            }
                            aria-label={`Память для ${p.display_name}`}
                            aria-pressed={p.enable_memory}
                          />
                        </div>
                      </div>

                      <div className="persona-actions">
                        <button
                          className={`glass-btn ${
                            p.id === ap?.id ? "" : "primary"
                          }`}
                          onClick={() => activate(p)}
                        >
                          {p.id === ap?.id ? "Активен" : "Активировать"}
                        </button>
                        <button
                          className="glass-btn"
                          onClick={() => setEditingId(p.id)}
                        >
                          Настроить
                        </button>
                        {p.is_builtin ? (
                          <button
                            className={`glass-btn ${
                              confirmKey === `reset:${p.id}`
                                ? "danger confirming"
                                : ""
                            }`}
                            onClick={() =>
                              runWithConfirm(`reset:${p.id}`, () =>
                                resetProfile(p.id)
                              )
                            }
                          >
                            {confirmKey === `reset:${p.id}`
                              ? "Сбросить?"
                              : "Сброс"}
                          </button>
                        ) : (
                          <button
                            className={`glass-btn danger ${
                              confirmKey === `del-p:${p.id}` ? "confirming" : ""
                            }`}
                            onClick={() =>
                              runWithConfirm(`del-p:${p.id}`, () =>
                                removeProfile(p.id)
                              )
                            }
                          >
                            {confirmKey === `del-p:${p.id}`
                              ? "Удалить?"
                              : "Удалить"}
                          </button>
                        )}
                      </div>
                    </article>
                  ))}

                  <button className="persona-add-card" onClick={createProfile}>
                    <span className="persona-add-plus">+</span>
                    <span>Новый профиль</span>
                  </button>
                </div>
              </section>

              {draft && (
                <aside className="glass-panel">
                  <div className="panel-header">
                    <h2 className="panel-title" style={{ fontSize: 20 }}>
                      Настройка профиля
                    </h2>
                    <button
                      className="glass-btn"
                      onClick={() => {
                        setEditingId(null);
                        setDraft(null);
                      }}
                    >
                      Закрыть
                    </button>
                  </div>

                  <div className="editor-scroll">
                    <div className="form-field">
                      <label>Имя</label>
                      <input
                        className="glass-input"
                        type="text"
                        value={draft.display_name}
                        onChange={(e) =>
                          setDraft({ ...draft, display_name: e.target.value })
                        }
                      />
                    </div>

                    <div className="form-field">
                      <label>Роль</label>
                      <input
                        className="glass-input"
                        type="text"
                        value={draft.role_tag}
                        onChange={(e) =>
                          setDraft({ ...draft, role_tag: e.target.value })
                        }
                        placeholder="Например: Технический ассистент"
                      />
                    </div>

                    <div className="form-field">
                      <label>Голос Gemini Live</label>
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

                    <div className="form-field">
                      <label>Системный промпт</label>
                      <textarea
                        value={draft.system_prompt}
                        onChange={(e) =>
                          setDraft({ ...draft, system_prompt: e.target.value })
                        }
                      />
                    </div>

                    <div className="persona-toggles">
                      <div className="toggle-line">
                        <span>Веб-поиск</span>
                        <button
                          type="button"
                          className={`glass-switch ${
                            draft.enable_web_search ? "on" : ""
                          }`}
                          onClick={() =>
                            setDraft({
                              ...draft,
                              enable_web_search: !draft.enable_web_search,
                            })
                          }
                        />
                      </div>
                      <div className="toggle-line">
                        <span>Долгосрочная память</span>
                        <button
                          type="button"
                          className={`glass-switch ${
                            draft.enable_memory ? "on" : ""
                          }`}
                          onClick={() =>
                            setDraft({
                              ...draft,
                              enable_memory: !draft.enable_memory,
                            })
                          }
                        />
                      </div>
                      <div className="toggle-line">
                        <span>Задачи (плагины)</span>
                        <button
                          type="button"
                          className={`glass-switch ${
                            draft.enable_tasks ? "on" : ""
                          }`}
                          onClick={() =>
                            setDraft({
                              ...draft,
                              enable_tasks: !draft.enable_tasks,
                            })
                          }
                        />
                      </div>
                    </div>
                  </div>

                  <div className="persona-actions" style={{ marginTop: 16 }}>
                    <button className="glass-btn primary" onClick={saveDraft}>
                      Сохранить изменения
                    </button>
                    <button
                      className="glass-btn"
                      onClick={() => {
                        setEditingId(null);
                        setDraft(null);
                      }}
                    >
                      Отмена
                    </button>
                  </div>
                </aside>
              )}
            </div>
          )}

          {/* ==================== VIEW: MEMORY ==================== */}
          {view === "memory" && (
            <div className="workspace-grid single">
              <section className="glass-panel">
                <div className="panel-header">
                  <div>
                    <h1 className="panel-title">
                      Долгосрочная память · {ap?.display_name || "Jarvis"}
                    </h1>
                    <div className="panel-subtitle tabular">
                      {ap?.memory_tokens || 0} / {ap?.memory_max_tokens || 4000}{" "}
                      токенов · {memPct}% · {memoryFactsCount} фактов
                    </div>
                  </div>
                </div>

                <div className="thin-meter" style={{ marginTop: 0 }}>
                  <div
                    className="thin-meter-fill"
                    style={{ width: `${memPct}%` }}
                  />
                </div>

                <div className="memory-textarea-wrap">
                  <textarea
                    className="memory-textarea"
                    value={memoryDraft}
                    onChange={(e) => {
                      setMemoryDraft(e.target.value);
                      setMemDirty(true);
                    }}
                    placeholder="- Факты о вас, предпочтения и контекст проектов, по строке на факт…"
                  />
                </div>

                <div className="panel-header" style={{ marginBottom: 0 }}>
                  <div className="panel-actions">
                    <button
                      className="glass-btn primary"
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
                      Сохранить полностью
                    </button>
                    <button
                      className="glass-btn"
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
                      Дополнить строками
                    </button>
                    <button
                      className={`glass-btn danger ${
                        confirmKey === "clear-mem" ? "confirming" : ""
                      }`}
                      onClick={() =>
                        runWithConfirm("clear-mem", async () => {
                          if (!ap) return;
                          await api.clearMemory(ap.id);
                          setMemDirty(false);
                          await refresh();
                        })
                      }
                    >
                      {confirmKey === "clear-mem"
                        ? "Подтвердить очистку?"
                        : "Очистить память"}
                    </button>
                  </div>

                  <span className="panel-subtitle">
                    Экстрактор автоматически пополняет факты после каждого диалога
                  </span>
                </div>
              </section>
            </div>
          )}

          {/* ==================== VIEW: SESSIONS ==================== */}
          {view === "sessions" && (
            <div className="workspace-grid single">
              <section className="glass-panel">
                <div className="panel-header">
                  <div>
                    <h1 className="panel-title">
                      История диалогов ·{" "}
                      <span className="tabular">{sessions.length}</span>
                    </h1>
                    <div className="panel-subtitle">
                      Выберите беседу, чтобы вернуться к её контексту
                    </div>
                  </div>
                  <div className="panel-actions">
                    <input
                      className="glass-input"
                      style={{ width: 240 }}
                      type="text"
                      placeholder="Поиск по диалогам…"
                      value={sessionSearch}
                      onChange={(e) => setSessionSearch(e.target.value)}
                    />
                    <button
                      className="glass-btn primary"
                      onClick={() => {
                        j.newSession();
                        setView("chat");
                      }}
                    >
                      Новый диалог
                    </button>
                  </div>
                </div>

                <div className="sessions-list">
                  {filteredSessions.length === 0 ? (
                    <div className="empty-quiet">
                      {sessions.length === 0
                        ? "Пока нет сохранённых диалогов. Отправьте первое сообщение в чате."
                        : "По вашему запросу ничего не найдено."}
                    </div>
                  ) : (
                    filteredSessions.map((s, idx) => (
                      <div
                        key={s.id}
                        className={`session-row ${
                          s.id === j.sessionId ? "active" : ""
                        }`}
                        onClick={() => {
                          j.openSession(s.id);
                          setView("chat");
                        }}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            j.openSession(s.id);
                            setView("chat");
                          }
                        }}
                      >
                        <span className="session-index tabular">
                          {idx + 1}
                        </span>
                        <span className="session-title">
                          {s.title || "Диалог"}
                        </span>
                        <span className="session-meta tabular">
                          {s.status} · {fmtTime(s.updated_at)}
                        </span>
                        <button
                          className={`glass-btn danger ${
                            confirmKey === `del-s:${s.id}` ? "confirming" : ""
                          }`}
                          onClick={(e) => {
                            e.stopPropagation();
                            runWithConfirm(`del-s:${s.id}`, () =>
                              api.deleteSession(s.id).then(refresh)
                            );
                          }}
                        >
                          {confirmKey === `del-s:${s.id}`
                            ? "Удалить?"
                            : "Удалить"}
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}