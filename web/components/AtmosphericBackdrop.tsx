"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type SceneId =
  | "storm-horizon"
  | "ethereal-fjord"
  | "cloud-dawn"
  | "moonlit-coast"
  | "custom";

export interface ScenePreset {
  id: Exclude<SceneId, "custom">;
  name: string;
  subtitle: string;
  previewGradient: string;
  defaultTint: string;
  outerBg: string;
}

export const SCENE_PRESETS: ScenePreset[] = [
  {
    id: "storm-horizon",
    name: "Грозовой горизонт",
    subtitle: "Свинцовые облака и золотой просвет",
    previewGradient:
      "linear-gradient(145deg, #273e47 0%, #4e6b71 42%, #d4be8e 74%, #2d4123 100%)",
    defaultTint: "#9dd9e5",
    outerBg: "#4c6266",
  },
  {
    id: "ethereal-fjord",
    name: "Эфирный фьорд",
    subtitle: "Сумеречные пики и северное сияние",
    previewGradient:
      "linear-gradient(145deg, #0b1929 0%, #1c4452 46%, #56bfa6 76%, #0b1620 100%)",
    defaultTint: "#7de2d1",
    outerBg: "#172d38",
  },
  {
    id: "cloud-dawn",
    name: "Небесный рассвет",
    subtitle: "Море облаков над горным хребтом",
    previewGradient:
      "linear-gradient(145deg, #21304d 0%, #586382 42%, #e6b692 78%, #3c3448 100%)",
    defaultTint: "#f3c7a2",
    outerBg: "#3d465d",
  },
  {
    id: "moonlit-coast",
    name: "Лунный прибой",
    subtitle: "Серебристый свет над ночным океаном",
    previewGradient:
      "linear-gradient(145deg, #0e1624 0%, #2a3c54 45%, #8ba5bd 74%, #0f1b2b 100%)",
    defaultTint: "#b8d0eb",
    outerBg: "#1c2838",
  },
];

/* Deterministic fast 2D value noise + domain-warped FBM for volumetric clouds */
function hash2(x: number, y: number, seed: number): number {
  let n = Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(seed, 1442695041);
  n = (n ^ (n >>> 13)) >>> 0;
  n = Math.imul(n, 1274126177) >>> 0;
  return ((n ^ (n >>> 16)) >>> 0) / 4294967295;
}

function smoothNoise(x: number, y: number, seed: number): number {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);

  const a = hash2(ix, iy, seed);
  const b = hash2(ix + 1, iy, seed);
  const c = hash2(ix, iy + 1, seed);
  const d = hash2(ix + 1, iy + 1, seed);

  return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy;
}

function fbm(x: number, y: number, seed: number, octaves = 5): number {
  let value = 0;
  let amp = 0.52;
  let freq = 1;
  for (let i = 0; i < octaves; i++) {
    value += amp * smoothNoise(x * freq, y * freq, seed + i * 31);
    freq *= 2.04;
    amp *= 0.49;
  }
  return value;
}

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function mixRgb(
  c1: [number, number, number],
  c2: [number, number, number],
  t: number
): [number, number, number] {
  const k = clamp(t, 0, 1);
  return [lerp(c1[0], c2[0], k), lerp(c1[1], c2[1], k), lerp(c1[2], c2[2], k)];
}

/**
 * Procedurally renders a rich, painterly-photographic 16:9 atmospheric scene
 * with volumetric self-shadowed clouds, horizon light scattering, and terrain depth.
 */
function renderSceneToDataUrl(sceneId: Exclude<SceneId, "custom">): string {
  const w = 960;
  const h = 540;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";

  const img = ctx.createImageData(w, h);
  const data = img.data;

  const seedMap: Record<Exclude<SceneId, "custom">, number> = {
    "storm-horizon": 17,
    "ethereal-fjord": 43,
    "cloud-dawn": 89,
    "moonlit-coast": 131,
  };
  const seed = seedMap[sceneId];

  for (let py = 0; py < h; py++) {
    const ny = py / h;
    for (let px = 0; px < w; px++) {
      const nx = px / w;
      const idx = (py * w + px) * 4;

      let rgb: [number, number, number] = [20, 30, 38];

      if (sceneId === "storm-horizon") {
        // Dramatic towering cumulonimbus over lush dark emerald fields with golden horizon light
        const horizonY = 0.72;
        if (ny < horizonY + 0.04) {
          // Sky base gradient: deep slate teal top -> warm sunlit silver-gold right horizon
          const skyTop: [number, number, number] = [28, 49, 58];
          const skyMid: [number, number, number] = [66, 97, 102];
          const skyRightWarm: [number, number, number] = [228, 211, 168];
          const skyLeftDeep: [number, number, number] = [18, 35, 44];

          let base = mixRgb(skyTop, skyMid, Math.pow(ny / horizonY, 0.9));
          const warmBreak =
            Math.exp(-Math.pow((nx - 0.78) / 0.34, 2)) *
            Math.exp(-Math.pow((ny - 0.62) / 0.25, 2));
          const centerBreak =
            Math.exp(-Math.pow((nx - 0.44) / 0.26, 2)) *
            Math.exp(-Math.pow((ny - 0.12) / 0.22, 2));
          base = mixRgb(base, skyRightWarm, warmBreak * 0.92);
          base = mixRgb(base, [172, 206, 208], centerBreak * 0.55);
          base = mixRgb(base, skyLeftDeep, clamp((0.35 - nx) * 0.9, 0, 0.55));

          // Domain-warped volumetric towering storm clouds
          const cx = nx * 3.8;
          const cy = ny * 3.1;
          const wx = fbm(cx + 1.4, cy + 0.7, seed + 5, 4);
          const wy = fbm(cx - 0.9, cy + 2.1, seed + 13, 4);
          const densityRaw = fbm(cx + wx * 1.45, cy + wy * 1.15, seed, 5);

          // Shape giant cloud anvil rising center-left to center-right
          const anvilMask =
            clamp(1.25 - Math.abs(nx - 0.48) * 1.05, 0.25, 1) *
            clamp(1.15 - Math.pow(ny / 0.75, 2.2), 0, 1);
          const density = clamp((densityRaw - 0.34) * 2.15 * anvilMask, 0, 1);

          // Directional lighting derivative for sunlit cloud crowns vs brooding dark undersides
          const lightSample = fbm(
            cx + wx * 1.45 + 0.08,
            cy + wy * 1.15 - 0.11,
            seed,
            4
          );
          const rim = clamp((densityRaw - lightSample) * 4.5 + 0.52, 0, 1);
          const underDark = clamp((ny - 0.38) * 2.1, 0, 1);

          const cloudShadow: [number, number, number] = [20, 32, 39];
          const cloudMid: [number, number, number] = [74, 96, 102];
          const cloudCrown: [number, number, number] = [212, 224, 222];
          const cloudGoldEdge: [number, number, number] = [242, 224, 178];

          let cloudCol = mixRgb(cloudShadow, cloudMid, clamp(rim * 1.15 - underDark * 0.45, 0, 1));
          cloudCol = mixRgb(cloudCol, cloudCrown, Math.pow(clamp(rim - underDark * 0.35, 0, 1), 2.1) * 0.85);
          cloudCol = mixRgb(cloudCol, cloudGoldEdge, warmBreak * rim * 0.88);

          rgb = mixRgb(base, cloudCol, Math.pow(density, 0.82));

          // Soft atmospheric mist right above horizon
          const mistBand = Math.exp(-Math.pow((ny - horizonY) / 0.075, 2));
          const mistCol = mixRgb([130, 152, 146], [232, 212, 165], clamp(nx * 1.25 - 0.1, 0, 1));
          rgb = mixRgb(rgb, mistCol, mistBand * 0.48);
        }

        // Layered emerald terraced agricultural landscape below horizon
        if (ny >= horizonY - 0.015) {
          const ridgeOffset =
            (fbm(nx * 6.5, 0.5, seed + 71, 3) - 0.5) * 0.032;
          const groundStart = horizonY + ridgeOffset;
          if (ny >= groundStart) {
            const gy = clamp((ny - groundStart) / (1 - groundStart), 0, 1);
            // Perspective terraced field rows
            const perspective = Math.pow(gy + 0.08, 0.58);
            const curve = Math.sin(nx * 4.5 + gy * 3.8) * 0.18;
            const rowWave = Math.sin((gy * 38 + curve * 14) / (0.28 + perspective * 0.85));
            const texture = fbm(nx * 14, gy * 18, seed + 99, 3);

            const farField: [number, number, number] = [76, 94, 62];
            const darkRow: [number, number, number] = [24, 38, 18];
            const litRow: [number, number, number] = [104, 128, 54];
            const warmSunwash: [number, number, number] = [165, 166, 96];

            let field = mixRgb(darkRow, litRow, clamp(rowWave * 0.42 + 0.5 + (texture - 0.5) * 0.35, 0, 1));
            const sunPatch = Math.exp(-Math.pow((nx - 0.65) / 0.42, 2)) * (1 - gy * 0.4);
            field = mixRgb(field, warmSunwash, sunPatch * 0.38);
            // Distance haze fading into misty treeline
            field = mixRgb(farField, field, Math.pow(gy, 0.42));
            // Subtle dark foreground vignette for grounding
            field = mixRgb(field, [14, 22, 12], Math.pow(gy, 2.5) * 0.48);

            const edgeBlend = clamp((ny - groundStart) * 85, 0, 1);
            rgb = mixRgb(rgb, field, edgeBlend);
          }
        }
      } else if (sceneId === "ethereal-fjord") {
        // Nordic twilight fjord with misty alpine peaks, aurora ribbons, and glassy water
        const waterY = 0.68;
        const sampleSky = (sx: number, sy: number): [number, number, number] => {
          const top: [number, number, number] = [9, 20, 34];
          const mid: [number, number, number] = [22, 52, 68];
          const low: [number, number, number] = [74, 122, 130];
          let c = sy < 0.55 ? mixRgb(top, mid, sy / 0.55) : mixRgb(mid, low, (sy - 0.55) / 0.45);

          // Flowing aurora ribbons
          const wave = Math.sin(sx * 5.2 + fbm(sx * 2.5, sy * 2.2, seed + 19, 3) * 3.1);
          const ribbon =
            Math.exp(-Math.pow((sy - 0.28 - wave * 0.09) / 0.14, 2)) *
            clamp(fbm(sx * 6.2, sy * 2.4, seed + 29, 4) * 1.45 - 0.28, 0, 1);
          const auroraCol = mixRgb([72, 214, 184], [148, 232, 245], sx);
          c = mixRgb(c, auroraCol, ribbon * 0.68);

          // Soft twilight clouds
          const cl = fbm(sx * 4.1 + 1.2, sy * 3.4, seed, 4);
          const cMask = clamp((cl - 0.45) * 2.4, 0, 1) * (1 - sy * 0.3);
          c = mixRgb(c, [145, 192, 198], cMask * 0.34);
          return c;
        };

        const mFar = 0.54 - fbm(nx * 3.4, 0.2, seed + 41, 4) * 0.24;
        const mNear =
          0.63 -
          Math.abs(nx - 0.52) * 0.28 -
          fbm(nx * 5.1 + 2.3, 0.8, seed + 61, 4) * 0.16;

        if (ny < waterY) {
          rgb = sampleSky(nx, ny / waterY);
          if (ny >= mFar) {
            const depth = clamp((ny - mFar) / (waterY - mFar), 0, 1);
            const farCol = mixRgb([34, 66, 80], [18, 36, 48], depth);
            rgb = mixRgb(rgb, farCol, clamp((ny - mFar) * 90, 0, 1));
          }
          if (ny >= mNear) {
            const depth = clamp((ny - mNear) / (waterY - mNear), 0, 1);
            const ridgeTex = fbm(nx * 14, ny * 14, seed + 77, 3);
            const nearCol = mixRgb([18, 34, 46], [9, 17, 26], depth * 0.8 + ridgeTex * 0.2);
            rgb = mixRgb(rgb, nearCol, clamp((ny - mNear) * 110, 0, 1));
          }
          // Valley mist
          const valleyMist = Math.exp(-Math.pow((ny - waterY + 0.02) / 0.06, 2));
          rgb = mixRgb(rgb, [132, 182, 186], valleyMist * 0.36);
        } else {
          // Mirror fjord water with subtle ripples
          const wy = (ny - waterY) / (1 - waterY);
          const ripple = Math.sin(ny * 190 + fbm(nx * 12, wy * 20, seed + 101, 3) * 6) * 0.014 * wy;
          const reflY = clamp(1 - wy * 0.88 + ripple, 0, 1);
          const reflected = sampleSky(nx + ripple * 0.6, reflY * 0.85);
          rgb = mixRgb(reflected, [10, 22, 32], 0.42 + wy * 0.32);
        }
      } else if (sceneId === "cloud-dawn") {
        // High-altitude sea of golden sunlit pearl clouds at sunrise
        const skyTop: [number, number, number] = [26, 39, 64];
        const skyMid: [number, number, number] = [78, 92, 124];
        const skyHorizon: [number, number, number] = [238, 186, 148];

        let base =
          ny < 0.46
            ? mixRgb(skyTop, skyMid, ny / 0.46)
            : mixRgb(skyMid, skyHorizon, clamp((ny - 0.46) / 0.28, 0, 1));

        // Sun glow behind cloud horizon
        const sunGlow =
          Math.exp(-Math.pow((nx - 0.68) / 0.28, 2)) *
          Math.exp(-Math.pow((ny - 0.56) / 0.22, 2));
        base = mixRgb(base, [255, 228, 188], sunGlow * 0.85);

        // Upper cirrus wisps
        const cirrus = fbm(nx * 5.4, ny * 2.2, seed + 11, 4);
        base = mixRgb(base, [224, 198, 186], clamp((cirrus - 0.52) * 2.2, 0, 0.5) * (1 - ny));

        rgb = base;

        // Sea of volumetric billowing clouds in lower 48%
        const cloudLine = 0.52 + (fbm(nx * 3.2, 0.4, seed + 33, 4) - 0.5) * 0.09;
        if (ny >= cloudLine - 0.04) {
          const cy = clamp((ny - cloudLine) / (1 - cloudLine), 0, 1);
          const wx = fbm(nx * 4.5, cy * 5.2, seed + 17, 4);
          const billow = fbm(nx * 4.2 + wx * 1.1, cy * 4.8, seed, 5);
          const lit = fbm(nx * 4.2 + wx * 1.1 + 0.09, cy * 4.8 - 0.1, seed, 4);
          const shade = clamp((billow - lit) * 4.8 + 0.55, 0, 1);

          const cDeep: [number, number, number] = [56, 54, 78];
          const cRose: [number, number, number] = [174, 146, 152];
          const cGold: [number, number, number] = [250, 214, 178];

          let cCol = mixRgb(cDeep, cRose, clamp(shade * 1.1 - cy * 0.25, 0, 1));
          cCol = mixRgb(cCol, cGold, Math.pow(shade, 1.8) * (0.45 + sunGlow * 0.8) * (1 - cy * 0.35));
          const blend = clamp((ny - cloudLine + 0.04) * 18, 0, 1);
          rgb = mixRgb(rgb, cCol, blend);
        }
      } else {
        // Moonlit Coast: volumetric silver-blue clouds & shimmering midnight sea
        const seaY = 0.66;
        const moonDist = Math.hypot((nx - 0.64) * 1.78, ny - 0.28);
        const moonHalo = Math.exp(-moonDist * 3.1);
        const moonCore = Math.exp(-Math.pow(moonDist / 0.045, 2));

        if (ny < seaY) {
          const skyTop: [number, number, number] = [10, 18, 30];
          const skyLow: [number, number, number] = [44, 66, 88];
          let base = mixRgb(skyTop, skyLow, Math.pow(ny / seaY, 1.15));
          base = mixRgb(base, [176, 206, 232], moonHalo * 0.58);
          base = mixRgb(base, [242, 248, 255], moonCore * 0.82);

          const wx = fbm(nx * 3.6 + 0.8, ny * 3.2, seed + 7, 4);
          const cl = fbm(nx * 3.5 + wx * 1.3, ny * 3.0, seed, 5);
          const clLit = fbm(nx * 3.5 + wx * 1.3 + 0.07, ny * 3.0 - 0.08, seed, 4);
          const rim = clamp((cl - clLit) * 4.5 + 0.45, 0, 1);
          const dens = clamp((cl - 0.39) * 2.1, 0, 1) * (1 - moonCore * 0.65);

          const cDark: [number, number, number] = [14, 22, 34];
          const cSilver: [number, number, number] = [170, 196, 220];
          const cCol = mixRgb(cDark, cSilver, rim * (0.35 + moonHalo * 0.85));
          rgb = mixRgb(base, cCol, dens * 0.88);
        } else {
          const wy = (ny - seaY) / (1 - seaY);
          const wave = fbm(nx * 16, wy * 34, seed + 55, 4);
          const shimmerWidth = 0.06 + wy * 0.24;
          const shimmer =
            Math.exp(-Math.pow((nx - 0.64) / shimmerWidth, 2)) *
            clamp((wave - 0.42) * 3.2, 0, 1);
          const waterBase = mixRgb([36, 56, 76], [9, 16, 26], Math.pow(wy, 0.65));
          rgb = mixRgb(waterBase, [215, 232, 248], shimmer * 0.78);

          // Atmospheric cliff silhouette on far left
          const cliffEdge = 0.24 - wy * 0.12 + fbm(wy * 5, 1.2, seed + 88, 3) * 0.08;
          if (nx < cliffEdge) {
            const cliffBlend = clamp((cliffEdge - nx) * 45, 0, 1);
            rgb = mixRgb(rgb, [8, 13, 21], cliffBlend * 0.92);
          }
        }
      }

      // Subtle photographic micro-grain to eliminate gradient banding
      const grain = (hash2(px, py, seed + 303) - 0.5) * 4.5;
      data[idx] = clamp(Math.round(rgb[0] + grain), 0, 255);
      data[idx + 1] = clamp(Math.round(rgb[1] + grain), 0, 255);
      data[idx + 2] = clamp(Math.round(rgb[2] + grain), 0, 255);
      data[idx + 3] = 255;
    }
  }

  ctx.putImageData(img, 0, 0);

  // Subtle volumetric light rays for storm-horizon and cloud-dawn
  if (sceneId === "storm-horizon" || sceneId === "cloud-dawn") {
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    const rayGrad = ctx.createRadialGradient(
      w * 0.78,
      h * 0.56,
      10,
      w * 0.75,
      h * 0.58,
      w * 0.48
    );
    rayGrad.addColorStop(
      0,
      sceneId === "storm-horizon"
        ? "rgba(255, 234, 186, 0.34)"
        : "rgba(255, 218, 178, 0.38)"
    );
    rayGrad.addColorStop(0.5, "rgba(240, 210, 160, 0.08)");
    rayGrad.addColorStop(1, "rgba(240, 210, 160, 0)");
    ctx.fillStyle = rayGrad;
    ctx.fillRect(0, 0, w, h);
    ctx.restore();
  }

  return canvas.toDataURL("image/jpeg", 0.92);
}

const sceneCache = new Map<string, string>();

interface AtmosphericBackdropProps {
  sceneId: SceneId;
  customPhoto: string | null;
  dimLevel: number; // 0..100
  voiceOn: boolean;
  micLevel: number;
  parallax: { x: number; y: number };
  onBackdropUrl?: (url: string) => void;
}

export function AtmosphericBackdrop({
  sceneId,
  customPhoto,
  dimLevel,
  voiceOn,
  micLevel,
  parallax,
  onBackdropUrl,
}: AtmosphericBackdropProps) {
  const [generatedUrl, setGeneratedUrl] = useState<string>("");
  const lastSceneRef = useRef<string>("");

  const activePreset = useMemo(
    () => SCENE_PRESETS.find((s) => s.id === sceneId) ?? SCENE_PRESETS[0],
    [sceneId]
  );

  useEffect(() => {
    if (sceneId === "custom" && customPhoto) {
      setGeneratedUrl(customPhoto);
      onBackdropUrl?.(customPhoto);
      return;
    }

    const key = sceneId === "custom" ? "storm-horizon" : sceneId;
    if (sceneCache.has(key)) {
      const cached = sceneCache.get(key)!;
      setGeneratedUrl(cached);
      onBackdropUrl?.(cached);
      return;
    }

    if (lastSceneRef.current === key) return;
    lastSceneRef.current = key;

    // Defer slightly so first paint is instant with smooth gradient fallback
    const raf = window.requestAnimationFrame(() => {
      const url = renderSceneToDataUrl(key);
      if (url) {
        sceneCache.set(key, url);
        setGeneratedUrl(url);
        onBackdropUrl?.(url);
      }
    });
    return () => window.cancelAnimationFrame(raf);
  }, [sceneId, customPhoto, onBackdropUrl]);

  const activeImg = sceneId === "custom" && customPhoto ? customPhoto : generatedUrl;
  const scrimAlpha = 0.22 + (dimLevel / 100) * 0.45;
  const voiceGlow = voiceOn ? 0.16 + Math.min(1, micLevel) * 0.24 : 0.04;

  return (
    <div className="backdrop-root" aria-hidden="true">
      {/* Fallback atmospheric gradient while procedural canvas generates */}
      <div
        className="backdrop-fallback"
        style={{ background: activePreset.previewGradient }}
      />

      {/* Full-bleed high-resolution photographic / volumetric layer with spatial parallax */}
      {activeImg && (
        <div
          className="backdrop-photo"
          style={{
            backgroundImage: `url(${activeImg})`,
            transform: `translate3d(${parallax.x * -10}px, ${parallax.y * -7}px, 0) scale(1.06)`,
          }}
        />
      )}

      {/* Drifting atmospheric light veil for living depth */}
      <div
        className="backdrop-mist"
        style={{
          transform: `translate3d(${parallax.x * -18}px, ${parallax.y * -10}px, 0)`,
        }}
      />

      {/* Voice reactive ethereal radiance */}
      <div
        className="backdrop-aura"
        style={{
          opacity: voiceGlow,
        }}
      />

      {/* Calibrated contrast scrim ensuring crisp legibility while preserving horizon light */}
      <div
        className="backdrop-scrim"
        style={{
          background: `linear-gradient(108deg, rgba(8, 14, 20, ${
            scrimAlpha + 0.16
          }) 0%, rgba(10, 18, 24, ${scrimAlpha * 0.65}) 48%, rgba(8, 14, 20, ${
            scrimAlpha + 0.08
          }) 100%)`,
        }}
      />
    </div>
  );
}
