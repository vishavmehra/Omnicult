"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { zoneOf } from "@/components/field/transition";

import { prefersReducedMotion, subscribe } from "./ticker";

/*
 * Meadow at dusk: a band of slim grass blades along the bottom of the landing page swaying in a slow breeze (ember rim
 * light on the tips), and sparse drifting motes with a soft glow. Mounted once in the root layout, so it carries on into
 * the app, where the grass folds away and only a calmer drift of motes remains. One 2D canvas, DPR 1 (the layer is soft by
 * design), the shared 30 fps ticker, fewer elements on phones, a single still frame under prefers-reduced-motion.
 */

type Blade = { x: number; h: number; w: number; lean: number; phase: number; back: boolean };
type Mote = { x: number; y: number; vx: number; vy: number; r: number; phase: number; flicker: number };

function readColors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string) => cs.getPropertyValue(name).trim();
  return { base: v("--grass-base"), back: v("--grass-back"), rim: v("--grass-rim"), mote: v("--mote") };
}

function moteSprite(color: string) {
  const c = document.createElement("canvas");
  c.width = c.height = 32;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(16, 16, 0, 16, 16, 16);
  grad.addColorStop(0, color);
  grad.addColorStop(0.25, color);
  grad.addColorStop(1, "transparent");
  g.fillStyle = grad;
  g.fillRect(0, 0, 32, 32);
  return c;
}

export function AmbientCanvas() {
  const ref = useRef<HTMLCanvasElement>(null);
  const pathname = usePathname();
  const zone = useRef(zoneOf(pathname));
  const redraw = useRef<() => void>(() => {});

  useEffect(() => {
    zone.current = zoneOf(pathname);
    redraw.current();
  }, [pathname]);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const still = prefersReducedMotion();
    let colors = readColors();
    let sprite = moteSprite(colors.mote || "rgb(255 176 110 / 0.9)");
    let blades: Blade[] = [];
    let motes: Mote[] = [];
    let w = 0;
    let h = 0;
    let t = 0;
    let grass = zone.current === "landing" ? 1 : 0;

    const build = () => {
      w = canvas.width = window.innerWidth;
      h = canvas.height = window.innerHeight;
      const small = w < 768;
      const count = Math.round(w / (small ? 15 : 10));
      blades = Array.from({ length: count }, (_, i) => {
        const back = i % 3 === 0;
        return {
          x: (i / count) * w + (Math.random() - 0.5) * (small ? 12 : 9),
          h: (small ? 26 : 38) + Math.random() * (small ? 46 : 92) * (back ? 1.15 : 1),
          w: 2 + Math.random() * 2.2,
          lean: (Math.random() - 0.5) * 0.3,
          phase: Math.random() * Math.PI * 2,
          back,
        };
      }).sort((a, b) => Number(b.back) - Number(a.back));
      const moteCount = small ? 10 : 22;
      motes = Array.from({ length: moteCount }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 10,
        vy: -3 - Math.random() * 7,
        r: 1 + Math.random() * 1.2,
        phase: Math.random() * Math.PI * 2,
        flicker: 0.6 + Math.random() * 1.2,
      }));
    };

    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      const app = zone.current !== "landing";
      // Motes: fewer and dimmer inside the app.
      const visibleMotes = app ? Math.ceil(motes.length * 0.55) : motes.length;
      for (let i = 0; i < visibleMotes; i++) {
        const m = motes[i];
        const a = (0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * m.flicker + m.phase))) * (app ? 0.35 : 0.6);
        const size = m.r * 9;
        ctx.globalAlpha = a;
        ctx.drawImage(sprite, m.x - size / 2, m.y - size / 2, size, size);
      }
      ctx.globalAlpha = 1;
      if (grass < 0.01) return;
      // Grass: a breeze wave travels left to right; each blade also sways on its own phase.
      for (const b of blades) {
        const gust = 0.5 + 0.5 * Math.sin(t * 0.35 - b.x * 0.004);
        const angle = b.lean + Math.sin(t * 0.9 + b.phase) * 0.05 + gust * 0.16;
        const tipX = b.x + Math.sin(angle) * b.h;
        const tipY = h - Math.cos(angle) * b.h * grass;
        const midX = b.x + Math.sin(angle) * b.h * 0.42;
        const midY = h - b.h * 0.5 * grass;
        ctx.beginPath();
        ctx.moveTo(b.x - b.w / 2, h);
        ctx.quadraticCurveTo(midX - b.w * 0.25, midY, tipX, tipY);
        ctx.quadraticCurveTo(midX + b.w * 0.35, midY, b.x + b.w / 2, h);
        ctx.closePath();
        ctx.fillStyle = b.back ? colors.back : colors.base;
        ctx.globalAlpha = grass;
        ctx.fill();
        // Rim light along the top of the blade.
        ctx.beginPath();
        ctx.moveTo(midX + (tipX - midX) * 0.35, midY + (tipY - midY) * 0.35);
        ctx.quadraticCurveTo(midX + (tipX - midX) * 0.7, midY + (tipY - midY) * 0.72, tipX, tipY);
        ctx.strokeStyle = colors.rim;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    };

    const step = (dt: number) => {
      const app = zone.current !== "landing";
      t += dt * (app ? 0.6 : 1);
      grass += ((app ? 0 : 1) - grass) * Math.min(1, dt * 2.5);
      const speed = app ? 0.55 : 1;
      for (const m of motes) {
        m.x += m.vx * dt * speed;
        m.y += m.vy * dt * speed + Math.sin(t * 0.7 + m.phase) * 0.15;
        if (m.y < -10) m.y = h + 10;
        if (m.x < -10) m.x = w + 10;
        if (m.x > w + 10) m.x = -10;
      }
      draw();
    };

    const refreshColors = () => {
      colors = readColors();
      sprite = moteSprite(colors.mote || "rgb(255 176 110 / 0.9)");
      draw();
    };
    const theme = new MutationObserver(refreshColors);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    const onResize = () => {
      build();
      draw();
    };
    build();
    redraw.current = () => {
      if (still) {
        grass = zone.current === "landing" ? 1 : 0;
        draw();
      }
    };
    draw();
    canvas.style.opacity = "1";
    window.addEventListener("resize", onResize);
    const unsubscribe = still ? () => {} : subscribe(step);
    return () => {
      unsubscribe();
      theme.disconnect();
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return <canvas ref={ref} aria-hidden className="pointer-events-none fixed inset-0 -z-[1] size-full opacity-0 transition-opacity duration-1000" />;
}
