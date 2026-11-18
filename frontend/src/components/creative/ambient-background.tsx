"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

/**
 * AmbientBackground: the living ground behind every /app page. Mounted once in app/app/layout.tsx, so it never unmounts
 * between routes; the variant follows the route and crossfades (colours lerp, the motif fades out and in).
 *
 * Two layers on one 2D canvas at reduced resolution (the layer is soft by design): six slow clay blobs in the
 * workspace's role colours that lean gently toward the pointer, and one motif per workspace (paper chips, contour rings,
 * glints, rising bubbles, ghost stamps, flowing waves, a constellation, or motes). It runs on the shared 30 fps ticker,
 * which stops while the tab is hidden, and draws a single still frame under prefers-reduced-motion.
 *
 * Usage: nothing to do in a page. `ambientVariantFor(pathname)` is exported for tests and for the shell.
 */

export type AmbientVariant = "today" | "desk" | "lens" | "studio" | "lab" | "launch" | "pulse" | "proof" | "platform";
type Motif = "motes" | "chips" | "contours" | "glints" | "bubbles" | "stamps" | "waves" | "constellation";

const VARIANTS: Record<AmbientVariant, { roles: string[]; motif: Motif }> = {
  today: { roles: ["--role-desk", "--role-lab", "--role-studio", "--role-lens", "--role-launch", "--role-proof"], motif: "motes" },
  desk: { roles: ["--role-desk", "--role-launch", "--role-studio"], motif: "chips" },
  lens: { roles: ["--role-lens", "--role-lab", "--role-pulse"], motif: "contours" },
  studio: { roles: ["--role-studio", "--role-desk", "--role-proof"], motif: "glints" },
  lab: { roles: ["--role-lab", "--role-pulse", "--role-studio"], motif: "bubbles" },
  launch: { roles: ["--role-launch", "--role-desk", "--role-lens"], motif: "stamps" },
  pulse: { roles: ["--role-pulse", "--role-lab", "--role-lens"], motif: "waves" },
  proof: { roles: ["--role-proof", "--role-lab", "--role-pulse"], motif: "constellation" },
  platform: { roles: ["--role-proof", "--role-lab", "--role-desk"], motif: "motes" },
};

/** "/app/c/<id>/lens?view=…" → "lens"; "/app" → "today"; settings and usage → "platform". */
export function ambientVariantFor(pathname: string): AmbientVariant {
  const seg = pathname.split("/");
  if (seg[2] === "c") {
    const ws = seg[4];
    return ws && ws in VARIANTS && ws !== "today" && ws !== "platform" ? (ws as AmbientVariant) : "desk";
  }
  if (seg[2] === "settings" || seg[2] === "usage") return "platform";
  return "today";
}

type RGB = [number, number, number];
type Blob = { role: number; x: number; y: number; ax: number; ay: number; px: number; py: number; phase: number; r: number; depth: number; color: RGB; target: RGB };
type P = { x: number; y: number; vx: number; vy: number; size: number; phase: number; rot: number; vr: number; age: number; life: number; tone: number; cycle: number };

/** Small deterministic PRNG, so the composition is the same on every visit (and in screenshots). */
function rng(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rgba = (c: RGB, a: number) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, Math.min(1, a)).toFixed(3)})`;

function createScene(canvas: HTMLCanvasElement, initial: AmbientVariant) {
  const ctx = canvas.getContext("2d");
  const probe = document.createElement("canvas").getContext("2d");
  if (!ctx || !probe) return null;
  const still = prefersReducedMotion();
  const rand = rng(415883);

  const toRgb = (css: string, fallback: RGB): RGB => {
    if (!css) return fallback;
    probe.fillStyle = "#000";
    probe.fillStyle = css;
    const v = String(probe.fillStyle);
    if (v.startsWith("#")) return [parseInt(v.slice(1, 3), 16), parseInt(v.slice(3, 5), 16), parseInt(v.slice(5, 7), 16)];
    const m = v.match(/[\d.]+/g);
    return m ? [Number(m[0]), Number(m[1]), Number(m[2])] : fallback;
  };
  const readTheme = (variant: AmbientVariant) => {
    const cs = getComputedStyle(document.documentElement);
    const v = (n: string) => cs.getPropertyValue(n).trim();
    return {
      roles: VARIANTS[variant].roles.map((r) => toRgb(v(r), [255, 165, 132])),
      ink: toRgb(v("--ambient-ink"), [128, 128, 128]),
      blobAlpha: Number(v("--ambient-blob-alpha")) || 0.15,
      motifAlpha: Number(v("--ambient-motif-alpha")) || 0.7,
      dark: document.documentElement.classList.contains("dark"),
    };
  };

  let variant = initial;
  let theme = readTheme(variant);
  let motif: Motif = VARIANTS[variant].motif;
  let nextMotif: Motif | null = null;
  let motifLevel = 1;
  let w = 0;
  let h = 0;
  let t = 12;
  let spawnClock = 0;
  const lean = { x: 0, y: 0 };
  const aim = { x: 0, y: 0 };

  const blobs: Blob[] = Array.from({ length: 6 }, (_, i) => ({
    role: i,
    x: [0.12, 0.82, 0.5, 0.2, 0.9, 0.62][i],
    y: [0.18, 0.12, 0.55, 0.88, 0.7, 0.95][i],
    ax: 0.05 + rand() * 0.08,
    ay: 0.04 + rand() * 0.07,
    px: 55 + rand() * 50,
    py: 65 + rand() * 60,
    phase: rand() * Math.PI * 2,
    r: 0.26 + rand() * 0.16,
    depth: 0.35 + rand() * 0.65,
    color: [0, 0, 0],
    target: [0, 0, 0],
  }));
  const assign = (snap: boolean) =>
    blobs.forEach((b) => {
      b.target = theme.roles[b.role % theme.roles.length];
      if (snap) b.color = [...b.target];
    });
  assign(true);

  let ps: P[] = [];
  const counts: Record<Motif, [number, number, number]> = {
    // [area per particle, min, max]
    motes: [52_000, 10, 26],
    chips: [95_000, 6, 15],
    contours: [1e12, 2, 2],
    glints: [70_000, 8, 18],
    bubbles: [85_000, 7, 16],
    stamps: [1e12, 0, 0],
    waves: [1e12, 0, 0],
    constellation: [62_000, 10, 22],
  };
  const spawn = (fresh: boolean): P => ({
    x: rand() * w,
    y: fresh ? rand() * h : h + 20,
    vx: (rand() - 0.5) * 10,
    vy: 0,
    size: rand(),
    phase: rand() * Math.PI * 2,
    rot: rand() * Math.PI * 2,
    vr: (rand() - 0.5) * 0.5,
    age: 0,
    life: 4.5 + rand() * 2,
    tone: Math.floor(rand() * 6),
    cycle: -1,
  });
  const build = () => {
    const [per, min, max] = counts[motif];
    const n = Math.max(min, Math.min(max, Math.round((w * h) / per)));
    ps = Array.from({ length: n }, () => spawn(true));
    if (motif === "contours") ps.forEach((p, i) => ((p.x = w * (i ? 0.78 : 0.22)), (p.y = h * (i ? 0.72 : 0.3))));
  };

  const resize = () => {
    w = window.innerWidth;
    h = window.innerHeight;
    const scale = w >= 1024 ? 0.6 : 0.8;
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    build();
  };

  const role = (i: number) => theme.roles[i % theme.roles.length];

  const drawBlobs = () => {
    const big = Math.max(w, h);
    for (const b of blobs) {
      const cx = (b.x + Math.sin((t * Math.PI * 2) / b.px + b.phase) * b.ax) * w + lean.x * 30 * b.depth;
      const cy = (b.y + Math.cos((t * Math.PI * 2) / b.py + b.phase) * b.ay) * h + lean.y * 22 * b.depth;
      const r = b.r * big;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
      g.addColorStop(0, rgba(b.color, theme.blobAlpha));
      g.addColorStop(0.55, rgba(b.color, theme.blobAlpha * 0.42));
      g.addColorStop(1, rgba(b.color, 0));
      ctx.fillStyle = g;
      ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
    }
  };

  const drawMotif = (level: number) => {
    const a = theme.motifAlpha * level;
    if (a < 0.01) return;
    const ox = lean.x * 12;
    const oy = lean.y * 9;
    const ink = theme.ink;
    switch (motif) {
      case "motes":
        for (const p of ps) {
          const tw = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * (0.6 + p.size) + p.phase));
          ctx.fillStyle = rgba(role(p.tone), a * 0.6 * tw);
          ctx.beginPath();
          ctx.arc(p.x + ox, p.y + oy, 1.4 + p.size * 2.2, 0, Math.PI * 2);
          ctx.fill();
        }
        break;
      case "chips":
        for (const p of ps) {
          const s = 6 + p.size * 8;
          ctx.save();
          ctx.translate(p.x + ox, p.y + oy);
          ctx.rotate(p.rot);
          ctx.fillStyle = rgba(role(p.tone), a * (theme.dark ? 0.32 : 0.75));
          ctx.beginPath();
          ctx.roundRect(-s / 2, -s / 2, s, s * 0.72, 2.5);
          ctx.fill();
          ctx.strokeStyle = rgba(ink, a * 0.1);
          ctx.lineWidth = 1;
          ctx.stroke();
          ctx.restore();
        }
        break;
      case "contours":
        ctx.lineWidth = 1.2;
        for (const p of ps) {
          for (let k = 0; k < 6; k++) {
            const r = 46 + k * 34 + Math.sin(t * 0.35 + k * 0.8 + p.phase) * 7;
            ctx.strokeStyle = rgba(k % 2 ? ink : role(p.tone), a * (k % 2 ? 0.09 : 0.32) * (1 - k / 7));
            ctx.beginPath();
            ctx.ellipse(p.x + ox, p.y + oy, r, r * 0.7, p.rot + t * 0.01, 0, Math.PI * 2);
            ctx.stroke();
          }
        }
        break;
      case "glints":
        for (const p of ps) {
          const s = Math.sin(t * (0.5 + p.size * 0.7) + p.phase);
          const v = Math.pow(Math.max(0, s), 4);
          if (v < 0.02) continue;
          const r = 3 + p.size * 6;
          const x = p.x + ox;
          const y = p.y + oy;
          ctx.fillStyle = rgba(theme.dark ? [255, 244, 236] : role(p.tone), a * v * (theme.dark ? 0.55 : 0.95));
          ctx.beginPath();
          ctx.moveTo(x, y - r);
          ctx.quadraticCurveTo(x, y, x + r, y);
          ctx.quadraticCurveTo(x, y, x, y + r);
          ctx.quadraticCurveTo(x, y, x - r, y);
          ctx.quadraticCurveTo(x, y, x, y - r);
          ctx.fill();
        }
        break;
      case "bubbles":
        for (const p of ps) {
          const r = 5 + p.size * 12;
          const x = p.x + ox + Math.sin(t * 0.8 + p.phase) * 6;
          const y = p.y + oy;
          ctx.fillStyle = rgba(role(p.tone), a * (theme.dark ? 0.12 : 0.4));
          ctx.strokeStyle = rgba(ink, a * 0.12);
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = rgba([255, 255, 255], a * (theme.dark ? 0.12 : 0.6));
          ctx.beginPath();
          ctx.arc(x - r * 0.35, y - r * 0.35, r * 0.22, 0, Math.PI * 2);
          ctx.fill();
        }
        break;
      case "stamps":
        for (const p of ps) {
          const k = p.age / p.life;
          const v = Math.sin(Math.PI * Math.min(1, k));
          const settle = 1.12 - 0.12 * Math.min(1, p.age / 0.7);
          const r = (24 + p.size * 22) * settle;
          ctx.save();
          ctx.translate(p.x + ox, p.y + oy);
          ctx.rotate(p.rot * 0.3);
          ctx.strokeStyle = rgba(role(p.tone), a * v * (theme.dark ? 0.32 : 0.75));
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(0, 0, r, 0, Math.PI * 2);
          ctx.stroke();
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(0, 0, r - 5, 0, Math.PI * 2);
          ctx.stroke();
          ctx.fillStyle = rgba(role(p.tone), a * v * (theme.dark ? 0.08 : 0.22));
          ctx.fill();
          ctx.restore();
        }
        break;
      case "waves":
        ctx.lineWidth = 1.6;
        for (let k = 0; k < 3; k++) {
          const base = h * (0.32 + k * 0.22) + oy * (k + 1);
          const amp = 16 + k * 9;
          const len = 300 + k * 110;
          const speed = 0.22 + k * 0.08;
          ctx.strokeStyle = rgba(role(k), a * (theme.dark ? 0.3 : 0.75));
          ctx.beginPath();
          for (let x = -20; x <= w + 20; x += 14) {
            const y = base + amp * Math.sin((x / len) * Math.PI * 2 + t * speed + k) + amp * 0.4 * Math.sin((x / (len * 0.53)) * Math.PI * 2 - t * speed * 1.3);
            if (x === -20) ctx.moveTo(x + ox, y);
            else ctx.lineTo(x + ox, y);
          }
          ctx.stroke();
        }
        break;
      case "constellation": {
        const reach = 170;
        ctx.lineWidth = 1;
        for (let i = 0; i < ps.length; i++) {
          for (let j = i + 1; j < ps.length; j++) {
            const dx = ps[i].x - ps[j].x;
            const dy = ps[i].y - ps[j].y;
            const d = Math.hypot(dx, dy);
            if (d > reach) continue;
            ctx.strokeStyle = rgba(ink, a * 0.16 * (1 - d / reach));
            ctx.beginPath();
            ctx.moveTo(ps[i].x + ox, ps[i].y + oy);
            ctx.lineTo(ps[j].x + ox, ps[j].y + oy);
            ctx.stroke();
          }
        }
        ps.forEach((p, i) => {
          const hub = i % 4 === 0;
          ctx.fillStyle = hub ? rgba(role(p.tone), a * (theme.dark ? 0.55 : 0.95)) : rgba(ink, a * 0.28);
          ctx.beginPath();
          ctx.arc(p.x + ox, p.y + oy, hub ? 3 : 1.7, 0, Math.PI * 2);
          ctx.fill();
        });
        break;
      }
    }
  };

  const draw = () => {
    ctx.clearRect(0, 0, w, h);
    drawBlobs();
    drawMotif(motifLevel);
  };

  const update = (dt: number) => {
    t += dt;
    const k = Math.min(1, dt * 1.6);
    lean.x += (aim.x - lean.x) * k;
    lean.y += (aim.y - lean.y) * k;
    const c = Math.min(1, dt * 1.4);
    for (const b of blobs) for (let i = 0; i < 3; i++) b.color[i] += (b.target[i] - b.color[i]) * c;
    if (nextMotif) {
      motifLevel -= dt * 2.2;
      if (motifLevel <= 0) {
        motif = nextMotif;
        nextMotif = null;
        motifLevel = 0;
        build();
      }
    } else if (motifLevel < 1) motifLevel = Math.min(1, motifLevel + dt * 1.1);

    switch (motif) {
      case "motes":
        for (const p of ps) {
          p.x += p.vx * 0.5 * dt;
          p.y -= (4 + p.size * 8) * dt;
          if (p.y < -10) Object.assign(p, spawn(false));
          if (p.x < -10) p.x = w + 10;
          if (p.x > w + 10) p.x = -10;
        }
        break;
      case "chips":
        for (const p of ps) {
          p.y += (7 + p.size * 8) * dt;
          p.x += Math.sin(t * 0.6 + p.phase) * 8 * dt;
          p.rot += p.vr * dt;
          if (p.y > h + 20) Object.assign(p, spawn(false), { y: -20 });
        }
        break;
      case "contours":
        ps.forEach((p, i) => {
          p.x += Math.sin(t * 0.05 + i * 2) * 3 * dt;
          p.y += Math.cos(t * 0.04 + i) * 2 * dt;
        });
        break;
      case "glints":
        for (const p of ps) {
          const cycle = Math.floor((t * (0.5 + p.size * 0.7) + p.phase) / (Math.PI * 2));
          if (cycle !== p.cycle) {
            if (p.cycle !== -1) Object.assign(p, { x: rand() * w, y: rand() * h });
            p.cycle = cycle;
          }
          p.y -= 2 * dt;
        }
        break;
      case "bubbles":
        for (const p of ps) {
          p.y -= (10 + p.size * 16) * dt;
          if (p.y < -30) Object.assign(p, spawn(false));
        }
        break;
      case "stamps":
        spawnClock += dt;
        for (const p of ps) p.age += dt;
        ps = ps.filter((p) => p.age < p.life);
        if (spawnClock > 2.6 && ps.length < 3) {
          spawnClock = 0;
          ps.push({ ...spawn(true), x: w * (0.1 + rand() * 0.8), y: h * (0.12 + rand() * 0.76) });
        }
        break;
      case "constellation":
        for (const p of ps) {
          p.x += p.vx * 0.6 * dt;
          p.y += Math.sin(t * 0.2 + p.phase) * 4 * dt;
          if (p.x < 0 || p.x > w) p.vx *= -1;
        }
        break;
      case "waves":
        break;
    }
    draw();
  };

  const onTheme = () => {
    theme = readTheme(variant);
    assign(true);
    draw();
  };
  const onResize = () => {
    resize();
    draw();
  };
  const onPointer = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    aim.x = (e.clientX / Math.max(1, w)) * 2 - 1;
    aim.y = (e.clientY / Math.max(1, h)) * 2 - 1;
  };

  resize();
  if (motif === "stamps" && still) ps = [0.3, 0.7].map((x, i) => ({ ...spawn(true), x: w * x, y: h * (0.3 + i * 0.4), age: 2.4 }));
  draw();
  canvas.style.opacity = "1";
  const themeObserver = new MutationObserver(onTheme);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  window.addEventListener("resize", onResize);
  if (!still) window.addEventListener("pointermove", onPointer, { passive: true });
  const unsubscribe = still ? () => {} : subscribe((dt) => update(dt));

  return {
    setVariant(next: AmbientVariant) {
      if (next === variant) return;
      variant = next;
      theme = readTheme(variant);
      assign(still);
      const m = VARIANTS[variant].motif;
      if (still) {
        motif = m;
        build();
        if (motif === "stamps") ps = [0.3, 0.7].map((x, i) => ({ ...spawn(true), x: w * x, y: h * (0.3 + i * 0.4), age: 2.4 }));
        draw();
      } else if (m !== motif) nextMotif = m;
      else nextMotif = null;
    },
    destroy() {
      unsubscribe();
      themeObserver.disconnect();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onPointer);
    },
  };
}

export function AmbientBackground({ variant }: { variant?: AmbientVariant }) {
  const pathname = usePathname();
  const active = variant ?? ambientVariantFor(pathname);
  const ref = useRef<HTMLCanvasElement>(null);
  const scene = useRef<ReturnType<typeof createScene>>(null);
  const first = useRef(active);

  useEffect(() => {
    scene.current?.setVariant(active);
  }, [active]);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const s = createScene(canvas, first.current);
    scene.current = s;
    return () => {
      s?.destroy();
      scene.current = null;
    };
  }, []);

  return (
    <canvas
      ref={ref}
      aria-hidden
      data-ambient={active}
      className="pointer-events-none fixed inset-0 -z-[1] size-full opacity-0 transition-opacity duration-1000"
    />
  );
}
