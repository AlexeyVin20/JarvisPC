"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, Profile, TranscriptEntry, WS_URL } from "./api";

const SAMPLE_RATE = 24000;

// Speaker echo protection: ONLY active while agent audio is playing (+ short
// reverb/AEC tail). When the agent is silent, 100% of mic audio passes raw.
// While playing, residual speaker bleed (~0.09 peak) is silenced, while real
// user speech over the agent (>= 0.25 peak & >= 0.06 RMS) opens the barge-in
// gate for 1.2s so interruptions work cleanly without self-interruption loops.
const BARGE_IN_PEAK = 0.25;
const BARGE_IN_RMS = 0.06;
const BARGE_IN_HOLD_PEAK = 0.1;
const BARGE_IN_HOLD_S = 1.2;
const ECHO_TAIL_S = 0.35;

export type AgentState =
  | "IDLE"
  | "STANDBY"
  | "CONNECTING"
  | "LISTENING"
  | "THINKING"
  | "SPEAKING"
  | "ERROR";

interface UseJarvisOptions {
  sessionId?: string;
  onMemoryUpdated?: (profileId: string) => void;
}

export function useJarvis(opts: UseJarvisOptions = {}) {
  const [connected, setConnected] = useState(false);
  const [state, setState] = useState<AgentState>("IDLE");
  const [stateNote, setStateNote] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>(opts.sessionId);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [messages, setMessages] = useState<TranscriptEntry[]>([]);
  const [liveUser, setLiveUser] = useState("");
  const [liveAgent, setLiveAgent] = useState<{ id: string; text: string } | null>(null);
  const [voiceOn, setVoiceOn] = useState(false);
  const [micLevel, setMicLevel] = useState(0); // 0..1 mic input peak, ~5 Hz updates
  const [micError, setMicError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const voiceOnRef = useRef(false);
  const audioRef = useRef<{
    ctx: AudioContext | null;
    mic: MediaStream | null;
    source: MediaStreamAudioSourceNode | null;
    proc: ScriptProcessorNode | null;
    mute: GainNode | null;
    nextPlay: number;
    sources: AudioBufferSourceNode[];
    echoTailUntil: number;
    bargeOpenUntil: number;
    resampleTail: Float32Array;
    resamplePos: number;
  }>({
    ctx: null,
    mic: null,
    source: null,
    proc: null,
    mute: null,
    nextPlay: 0,
    sources: [],
    echoTailUntil: -1,
    bargeOpenUntil: -1,
    resampleTail: new Float32Array(0),
    resamplePos: 0,
  });
  const liveAgentIdRef = useRef<string | null>(null);
  const onMemoryUpdatedRef = useRef(opts.onMemoryUpdated);
  onMemoryUpdatedRef.current = opts.onMemoryUpdated;

  const send = useCallback((payload: object) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }, []);

  const stopPlayback = useCallback(() => {
    const a = audioRef.current;
    for (const s of a.sources) {
      try {
        s.stop();
      } catch {}
    }
    a.sources = [];
    a.nextPlay = 0;
    const now = a.ctx?.currentTime ?? 0;
    a.echoTailUntil = now > 0 ? now + 0.15 : -1;
  }, []);

  const closeAudio = useCallback(() => {
    const a = audioRef.current;
    if (a.proc) {
      a.proc.onaudioprocess = null;
      a.proc.disconnect();
      a.proc = null;
    }
    a.source?.disconnect();
    a.source = null;
    a.mute?.disconnect();
    a.mute = null;
    a.mic?.getTracks().forEach((t) => t.stop());
    a.mic = null;
    stopPlayback();
    a.echoTailUntil = -1;
    a.bargeOpenUntil = -1;
    a.resampleTail = new Float32Array(0);
    a.resamplePos = 0;
    if (a.ctx) {
      void a.ctx.close().catch(() => {});
      a.ctx = null;
    }
  }, [stopPlayback]);

  const playChunk = useCallback((buf: ArrayBuffer) => {
    const a = audioRef.current;
    if (!a.ctx) return;
    if (a.ctx.state === "suspended") void a.ctx.resume();
    const i16 = new Int16Array(buf);
    if (i16.length < 2) return;
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 0x8000;
    const audioBuf = a.ctx.createBuffer(1, f32.length, SAMPLE_RATE);
    audioBuf.copyToChannel(f32, 0);
    const src = a.ctx.createBufferSource();
    src.buffer = audioBuf;
    src.connect(a.ctx.destination);
    const t = Math.max(a.nextPlay, a.ctx.currentTime + 0.03);
    src.start(t);
    a.nextPlay = t + audioBuf.duration;
    a.echoTailUntil = a.nextPlay + ECHO_TAIL_S;
    a.sources.push(src);
    src.onended = () => {
      const i = a.sources.indexOf(src);
      if (i >= 0) a.sources.splice(i, 1);
    };
  }, []);

  const handleMessage = useCallback(
    (ev: MessageEvent) => {
      if (ev.data instanceof ArrayBuffer) {
        playChunk(ev.data);
        return;
      }
      let msg: any;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      switch (msg.type) {
        case "ready":
          setSessionId(msg.session.id);
          setProfile(msg.profile);
          setMessages(msg.messages ?? []);
          setState("STANDBY");
          break;
        case "state":
          setState(msg.state ?? "STANDBY");
          setStateNote(msg.error ?? msg.notice ?? null);
          break;
        case "transcript": {
          const e: TranscriptEntry = msg.entry;
          if (e.role === "USER") setLiveUser("");
          if (e.role === "AGENT") {
            setLiveAgent(null);
            liveAgentIdRef.current = null;
          }
          setMessages((prev) => {
            const i = prev.findIndex((m) => m.id === e.id);
            if (i >= 0) {
              const copy = [...prev];
              copy[i] = e;
              return copy;
            }
            return [...prev.slice(-199), e];
          });
          break;
        }
        case "tool_trace": {
          const e: TranscriptEntry = msg.entry;
          setMessages((prev) => [...prev.slice(-199), e]);
          break;
        }
        case "transcript_partial":
          if (msg.role === "user") setLiveUser(msg.text ?? "");
          else if (msg.role === "agent") {
            liveAgentIdRef.current = msg.id ?? liveAgentIdRef.current;
            setLiveAgent({ id: msg.id ?? "live", text: msg.text ?? "" });
          }
          break;
        case "barge_in":
          stopPlayback();
          setLiveAgent(null);
          break;
        case "memory_updated":
          onMemoryUpdatedRef.current?.(msg.profile_id);
          break;
        case "profile":
          setProfile(msg.profile);
          break;
      }
    },
    [playChunk, stopPlayback]
  );

  const connect = useCallback(
    (sessionOverride?: string) => {
      if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
        if (sessionOverride !== undefined) send({ type: "init", session_id: sessionOverride });
        return;
      }
      const ws = new WebSocket(WS_URL);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        send({ type: "init", session_id: sessionOverride ?? sessionId });
      };
      ws.onmessage = handleMessage;
      ws.onclose = () => {
        setConnected(false);
        setVoiceOn(false);
        setMicLevel(0);
        voiceOnRef.current = false;
        closeAudio();
        setState("IDLE");
      };
      ws.onerror = () => setConnected(false);
    },
    [closeAudio, handleMessage, send, sessionId]
  );

  const startVoice = useCallback(async () => {
    setMicError(null);
    closeAudio();
    const a = audioRef.current;
    // Create AudioContext synchronously in the click gesture at native OS rate
    // (48kHz on Windows) so browser WebRTC AEC aligns with the hardware output.
    const ctx = new AudioContext();
    a.ctx = ctx;
    if (ctx.state === "suspended") void ctx.resume();
    try {
      a.mic = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
    } catch (e) {
      closeAudio();
      setMicError(String(e));
      return;
    }
    if (ctx.state === "suspended") await ctx.resume();
    const src = ctx.createMediaStreamSource(a.mic);
    const proc = ctx.createScriptProcessor(2048, 1, 1);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    src.connect(proc);
    proc.connect(mute);
    mute.connect(ctx.destination);
    a.source = src;
    a.proc = proc;
    a.mute = mute;
    let levelPeak = 0;
    let levelTicks = 0;
    proc.onaudioprocess = (ev) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !voiceOnRef.current) return;
      const raw = ev.inputBuffer.getChannelData(0);
      let peak = 0;
      let sumSq = 0;
      for (let i = 0; i < raw.length; i++) {
        const s = raw[i];
        const v = s < 0 ? -s : s;
        if (v > peak) peak = v;
        sumSq += s * s;
      }
      const rms = Math.sqrt(sumSq / raw.length);
      const now = ctx.currentTime;
      const agentPlaying = a.sources.length > 0 || now < a.echoTailUntil;
      let muteFrame = false;
      if (agentPlaying) {
        if (peak >= BARGE_IN_PEAK && rms >= BARGE_IN_RMS) {
          a.bargeOpenUntil = now + BARGE_IN_HOLD_S;
        } else if (now < a.bargeOpenUntil && peak >= BARGE_IN_HOLD_PEAK) {
          a.bargeOpenUntil = now + BARGE_IN_HOLD_S;
        }
        if (now >= a.bargeOpenUntil) {
          muteFrame = true;
        }
      }
      const shownPeak = muteFrame ? 0 : peak;
      if (shownPeak > levelPeak) levelPeak = shownPeak;
      if (++levelTicks >= 12) {
        setMicLevel(Math.min(1, levelPeak));
        levelTicks = 0;
        levelPeak = 0;
      }
      let input: Float32Array = muteFrame ? new Float32Array(raw.length) : raw;
      const ctxRate = ctx.sampleRate;
      if (ctxRate !== SAMPLE_RATE) {
        const ratio = ctxRate / SAMPLE_RATE;
        const combined = new Float32Array(a.resampleTail.length + input.length);
        combined.set(a.resampleTail);
        combined.set(input, a.resampleTail.length);
        const out: number[] = [];
        let pos = a.resamplePos;
        while (pos + 1 < combined.length) {
          const idx = pos | 0;
          const f = pos - idx;
          out.push(combined[idx] + (combined[idx + 1] - combined[idx]) * f);
          pos += ratio;
        }
        const consumed = Math.min(combined.length, pos | 0);
        a.resampleTail = combined.slice(consumed);
        a.resamplePos = pos - consumed;
        input = Float32Array.from(out);
      }
      if (input.length === 0) return;
      const i16 = new Int16Array(input.length);
      for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        i16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      ws.send(i16.buffer);
    };
    voiceOnRef.current = true;
    setVoiceOn(true);
    send({ type: "start_voice" });
  }, [closeAudio, send]);

  const stopVoice = useCallback(() => {
    voiceOnRef.current = false;
    setVoiceOn(false);
    setMicLevel(0);
    send({ type: "stop_voice" });
    closeAudio();
  }, [closeAudio, send]);

  const sendChat = useCallback(
    (text: string) => {
      const t = text.trim();
      if (!t) return;
      send({ type: "chat", text: t });
    },
    [send]
  );

  const switchProfile = useCallback(
    (profileId: string) => send({ type: "set_profile", profile_id: profileId }),
    [send]
  );

  const newSession = useCallback(() => {
    setMessages([]);
    setLiveAgent(null);
    setLiveUser("");
    send({ type: "init", session_id: null });
  }, [send]);

  const openSession = useCallback(
    (id: string) => {
      setMessages([]);
      send({ type: "init", session_id: id });
    },
    [send]
  );

  useEffect(() => {
    return () => {
      voiceOnRef.current = false;
      closeAudio();
      wsRef.current?.close();
    };
  }, [closeAudio]);

  return {
    connected,
    state,
    stateNote,
    sessionId,
    profile,
    messages,
    liveUser,
    liveAgent,
    voiceOn,
    micLevel,
    micError,
    connect,
    startVoice,
    stopVoice,
    sendChat,
    switchProfile,
    newSession,
    openSession,
  };
}
