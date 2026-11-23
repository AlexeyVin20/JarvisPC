"use client";

import { useEffect, useState } from "react";

interface HorizonWaveProps {
  state: string;
  voiceOn: boolean;
  micLevel: number;
}

/**
 * Ethereal luminous horizon spline with radiant starlight focal node —
 * inspired directly by the glowing wave-curve over the horizon landscape.
 * Reacts smoothly to voice input, speaking, and thinking states.
 */
export function HorizonWave({ state, voiceOn, micLevel }: HorizonWaveProps) {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const speed =
        state === "SPEAKING"
          ? 2.8
          : state === "THINKING" || state === "CONNECTING"
          ? 2.1
          : voiceOn
          ? 1.5
          : 0.45;
      setPhase((p) => (p + dt * speed) % (Math.PI * 200));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [state, voiceOn]);

  const activeBoost =
    state === "SPEAKING"
      ? 1.45
      : voiceOn
      ? 0.9 + Math.min(1, micLevel * 2.2) * 1.15
      : state === "THINKING"
      ? 1.1
      : 0.62;

  // Generate smooth horizon wave path (viewBox 0 0 800 130)
  const pts: string[] = [];
  const fillPts: string[] = [];
  const samples = 48;
  let centerY = 82;

  for (let i = 0; i <= samples; i++) {
    const t = i / samples;
    const x = t * 800;
    // Envelope keeps edges calm and swells organically across the central horizon
    const env = Math.sin(t * Math.PI);
    const wave1 = Math.sin(t * Math.PI * 3.4 - 0.65 + phase * 0.6) * 24 * activeBoost;
    const wave2 = Math.cos(t * Math.PI * 5.2 + phase * 0.9) * 8 * activeBoost;
    // Subtle central dip right at t=0.5 for the radiant focal starlight node
    const centerDip = Math.exp(-Math.pow((t - 0.5) / 0.13, 2)) * 22;
    const y = 76 - (wave1 + wave2) * env + centerDip * 0.85;

    if (i === Math.floor(samples / 2)) centerY = y;
    const cmd = i === 0 ? "M" : "L";
    pts.push(`${cmd}${x.toFixed(1)},${y.toFixed(1)}`);
    fillPts.push(`${cmd}${x.toFixed(1)},${y.toFixed(1)}`);
  }

  const linePath = pts.join(" ");
  const areaPath = `${fillPts.join(" ")} L800,130 L0,130 Z`;
  const starScale =
    state === "SPEAKING"
      ? 1.32
      : voiceOn
      ? 1.05 + Math.min(1, micLevel * 2) * 0.55
      : 1;

  return (
    <div className={`horizon-wave ${voiceOn ? "live" : ""}`} aria-hidden="true">
      <svg viewBox="0 0 800 130" preserveAspectRatio="none" className="horizon-svg">
        <defs>
          <linearGradient id="hw-stroke" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="rgba(255,255,255,0)" />
            <stop offset="18%" stopColor="rgba(255,255,255,0.45)" />
            <stop offset="50%" stopColor="rgba(255,255,255,0.95)" />
            <stop offset="82%" stopColor="rgba(255,255,255,0.45)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0)" />
          </linearGradient>
          <linearGradient id="hw-fill" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(255,255,255,0.18)" />
            <stop offset="65%" stopColor="rgba(var(--accent-rgb), 0.06)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0)" />
          </linearGradient>
          <linearGradient id="hw-beam" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(255,255,255,0)" />
            <stop offset="50%" stopColor="rgba(255,255,255,0.75)" />
            <stop offset="100%" stopColor="rgba(255,255,255,0)" />
          </linearGradient>
          <radialGradient id="hw-star" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgba(255,255,255,1)" />
            <stop offset="30%" stopColor="rgba(var(--accent-rgb), 0.85)" />
            <stop offset="100%" stopColor="rgba(var(--accent-rgb), 0)" />
          </radialGradient>
        </defs>

        <path d={areaPath} fill="url(#hw-fill)" />
        <path
          d={linePath}
          fill="none"
          stroke="url(#hw-stroke)"
          strokeWidth="2"
          strokeLinecap="round"
        />

        {/* Delicate vertical light pillar intersecting the focal starlight node */}
        <line
          x1="400"
          y1={Math.max(4, centerY - 52)}
          x2="400"
          y2={Math.min(126, centerY + 46)}
          stroke="url(#hw-beam)"
          strokeWidth="1.2"
        />

        {/* Radiant starlight focal point */}
        <circle
          cx="400"
          cy={centerY}
          r={18 * starScale}
          fill="url(#hw-star)"
          opacity={voiceOn ? 0.95 : 0.72}
        />
        <circle cx="400" cy={centerY} r={3.4 * starScale} fill="#ffffff" />
      </svg>
    </div>
  );
}
