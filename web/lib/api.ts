export const API_BASE =
  process.env.NEXT_PUBLIC_JARVIS_API ?? "http://localhost:8787";

export const WS_URL =
  process.env.NEXT_PUBLIC_JARVIS_WS ?? "ws://localhost:8787/ws";

export interface Profile {
  id: string;
  voice_id: string;
  display_name: string;
  role_tag: string;
  system_prompt: string;
  memory_text: string;
  memory_tokens: number;
  memory_max_tokens: number;
  enable_web_search: boolean;
  enable_memory: boolean;
  enable_tasks: boolean;
  orb_style: string;
  gemini_voice: string;
  is_builtin: boolean;
}

export interface VoiceOption {
  id: string;
  name: string;
  tone: string;
}

export interface AuthStatus {
  method: "env_key" | "stored_key" | "oauth" | null;
  email: string | null;
  oauth_ready: boolean;
}

export interface TranscriptEntry {
  id: string;
  role: "USER" | "AGENT" | "TOOL" | "SYSTEM";
  text: string;
  tool_name?: string | null;
  time: string;
}

export interface SessionInfo {
  id: string;
  profile_id: string;
  title: string;
  status: string;
  updated_at: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const api = {
  health: () => req<{ ok: boolean; live_model: string }>("/api/health"),
  profiles: () => req<Profile[]>("/api/profiles"),
  activeProfile: () => req<Profile>("/api/profiles/active"),
  activateProfile: (id: string) =>
    req<Profile>(`/api/profiles/${id}/activate`, { method: "POST" }),
  updateProfile: (id: string, patch: Partial<Profile>) =>
    req<Profile>(`/api/profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  createProfile: (body: {
    display_name: string;
    role_tag?: string;
    voice_id?: string;
    system_prompt?: string;
    orb_style?: string;
  }) =>
    req<Profile>("/api/profiles", { method: "POST", body: JSON.stringify(body) }),
  deleteProfile: (id: string) =>
    req(`/api/profiles/${id}`, { method: "DELETE" }),
  voices: () => req<VoiceOption[]>("/api/voices"),
  authStatus: () => req<AuthStatus>("/api/auth/status"),
  googleAuthUrl: () => req<{ url: string }>("/api/auth/google"),
  saveApiKey: (key: string) =>
    req("/api/auth/key", { method: "POST", body: JSON.stringify({ key }) }),
  disconnectAuth: () => req("/api/auth/disconnect", { method: "POST" }),
  resetProfile: (id: string) =>
    req<Profile>(`/api/profiles/${id}/reset`, { method: "POST" }),
  setMemory: (id: string, memory_text: string) =>
    req(`/api/profiles/${id}/memory`, {
      method: "PUT",
      body: JSON.stringify({ memory_text }),
    }),
  updateMemory: (id: string, body: { mode: "append" | "replace"; text: string }) =>
    req(`/api/profiles/${id}/memory`, {
      method: "PUT",
      body: JSON.stringify({ memory_text: body.text, mode: body.mode }),
    }),
  clearMemory: (id: string) =>
    req(`/api/profiles/${id}/memory`, { method: "DELETE" }),
  sessions: () => req<SessionInfo[]>("/api/sessions"),
  createSession: (profile_id?: string) =>
    req<SessionInfo>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ profile_id }),
    }),
  getSession: (id: string) =>
    req<SessionInfo & { messages: TranscriptEntry[] }>(`/api/sessions/${id}`),
  deleteSession: (id: string) =>
    req(`/api/sessions/${id}`, { method: "DELETE" }),
  chat: (message: string, session_id?: string, profile_id?: string) =>
    req<{ session_id: string; text: string; error?: string }>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, session_id, profile_id }),
    }),
};
