"use client";

import { useEffect, useId, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

/*
 * Two butterflies drifting through the landing page. Crafted SVG (forewing, hindwing, veins, graphite body), ember-to-pink
 * wings from theme variables, flown by a small steering loop: each one wanders between targets in the open margins, steers
 * clear of the headline and the actions, banks into its turns, flaps at its own slightly irregular rate and sometimes glides.
 * Transform-only updates on the shared ticker (paused in hidden tabs), perched still under prefers-reduced-motion.
 * pointer-events: none throughout.
 */

// Left wings, drawn around the body axis (x = 0). The right pair is the same paths mirrored.
// Forewing: long, with a pointed apex up and out; hindwing: shorter, rounded, with a swallowtail. Distinct shapes read as a butterfly.
const FORE = "M-1.6 -4 C-6 -14 -19 -29 -35 -33 C-43 -35 -47 -29 -44.5 -22 C-42 -14.5 -33.5 -6.5 -20.5 -2.2 C-12 0.2 -5.5 0.4 -1.6 0 Z";
const HIND = "M-1.6 1 C-8 1.2 -21.5 4.5 -29.5 12 C-35.5 18 -34 27.5 -26 30 C-22.5 31 -19.5 30 -17 28 L-13.5 39.5 C-12.8 41.2 -10.9 40.8 -11.1 39 L-12.2 25.6 C-8.2 21.6 -5.6 17.8 -4.5 14.5 C-2.7 9.5 -1.8 5 -1.6 1 Z";
const VEINS = ["M-2.5 -2.5 C-12 -12 -24 -24 -37 -30", "M-2.5 -1.5 C-14 -6 -28 -13 -42 -20", "M-2.5 -0.6 C-14 -1.8 -24 -3.5 -33 -7", "M-2.5 3 C-10 7 -20 14 -27 24", "M-2.5 5 C-7 11 -12 19 -16 28"];
const DOTS: [number, number, number][] = [
  [-41.5, -27.5, 1.25],
  [-43.8, -23, 0.95],
  [-39.5, -16, 0.8],
  [-31.5, 26.5, 0.95],
  [-25, 28.6, 0.8],
];

function Wing({ side, gradient }: { side: "l" | "r"; gradient: string }) {
  return (
    <g data-wing={side} transform={side === "r" ? "scale(-1,1)" : undefined}>
      <path d={HIND} fill={`url(#${gradient})`} stroke="var(--bfly-edge)" strokeWidth="1.5" strokeLinejoin="round" />
      <path d={FORE} fill={`url(#${gradient})`} stroke="var(--bfly-edge)" strokeWidth="1.6" strokeLinejoin="round" />
      {VEINS.map((d) => (
        <path key={d} d={d} stroke="var(--bfly-vein)" strokeWidth="0.6" fill="none" strokeLinecap="round" />
      ))}
      {DOTS.map(([cx, cy, r]) => (
        <circle key={`${cx}${cy}`} cx={cx} cy={cy} r={r} fill="var(--bfly-spot)" />
      ))}
    </g>
  );
}

function Butterfly({ id, tone }: { id: string; tone: "ember" | "pink" }) {
  const g = `bfly-grad-${id}`;
  const s = `bfly-shadow-${id}`;
  return (
    <svg viewBox="-50 -42 100 84" className="block size-full overflow-visible" aria-hidden>
      <defs>
        <linearGradient id={g} x1="0" y1="0" x2="-44" y2="-22" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor={`var(--bfly-${tone}-in)`} />
          <stop offset="1" stopColor={`var(--bfly-${tone}-out)`} />
        </linearGradient>
        <radialGradient id={s}>
          <stop offset="0" stopColor="rgb(0 0 0 / 0.28)" />
          <stop offset="1" stopColor="rgb(0 0 0 / 0)" />
        </radialGradient>
      </defs>
      <ellipse cx="0" cy="38" rx="20" ry="4.5" fill={`url(#${s})`} />
      <Wing side="l" gradient={g} />
      <Wing side="r" gradient={g} />
      <path d="M-0.9 -11 C-2.5 -18 -5.5 -24 -9.5 -28.5 M0.9 -11 C2.5 -18 5.5 -24 9.5 -28.5" stroke="var(--bfly-body)" strokeWidth="0.9" fill="none" strokeLinecap="round" />
      <circle cx="-9.7" cy="-28.8" r="1.25" fill="var(--bfly-body)" />
      <circle cx="9.7" cy="-28.8" r="1.25" fill="var(--bfly-body)" />
      <ellipse cx="0" cy="11" rx="1.9" ry="11" fill="var(--bfly-body)" />
      <ellipse cx="0" cy="-3" rx="2.7" ry="5.4" fill="var(--bfly-body)" />
      <circle cx="0" cy="-9.6" r="2.3" fill="var(--bfly-body)" />
    </svg>
  );
}

type Flyer = {
  el: HTMLDivElement;
  wings: SVGGElement[];
  x: number;
  y: number;
  vx: number;
  vy: number;
  angle: number;
  turn: number;
  tx: number;
  ty: number;
  retargetAt: number;
  speed: number;
  phase: number;
  rate: number;
  amp: number;
  ampTarget: number;
  glideUntil: number;
  nextGlide: number;
  size: number;
};

const rand = (a: number, b: number) => a + Math.random() * (b - a);

export function Butterflies() {
  const a = useRef<HTMLDivElement>(null);
  const b = useRef<HTMLDivElement>(null);
  const ida = useId().replace(/:/g, "");
  const idb = useId().replace(/:/g, "");

  useEffect(() => {
    const els = [a.current, b.current].filter(Boolean) as HTMLDivElement[];
    if (els.length < 2) return;
    const reduce = prefersReducedMotion();
    const small = window.innerWidth < 768;
    const size = small ? 38 : 52;
    const place = (el: HTMLDivElement, x: number, y: number, deg: number, s = 1) => {
      el.style.transform = `translate3d(${x - size / 2}px, ${y - size / 2}px, 0) rotate(${deg}deg) scale(${s})`;
    };

    // Perched, still: one in the upper right margin, one by the stage cards.
    if (reduce) {
      place(els[0], window.innerWidth * 0.86, window.innerHeight * 0.2, -14);
      place(els[1], window.innerWidth * 0.92, window.innerHeight * 0.82, 18, 0.85);
      els.forEach((el) => (el.style.opacity = "1"));
      return;
    }

    // Keep-out zone: the headline block and the actions, padded. Measured live, so it follows scrolling and resizing.
    const keepOut = () => {
      const hero = document.querySelector("[data-hero-content]");
      const r = hero?.getBoundingClientRect();
      if (!r || r.bottom < 0 || r.top > window.innerHeight) return null;
      return { l: r.left - 32, t: r.top - 32, r: r.right + 24, b: r.bottom + 24 };
    };
    const pickTarget = (f: Flyer, now: number) => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      const zone = keepOut();
      for (let i = 0; i < 12; i++) {
        // Wander around the product picture (right) and the stage cards (lower band); the left margin only rarely.
        const r = Math.random();
        const x = r < 0.7 ? rand(w * 0.5, w - 24) : rand(24, w - 24);
        const y = r < 0.7 ? rand(h * 0.08, h - 24) : rand(h * 0.66, h - 24);
        if (!zone || x < zone.l || x > zone.r || y < zone.t || y > zone.b) {
          f.tx = x;
          f.ty = y;
          break;
        }
      }
      f.retargetAt = now + rand(6000, 11000);
    };

    const now0 = performance.now();
    const flyers: Flyer[] = els.map((el, i) => ({
      el,
      wings: Array.from(el.querySelectorAll<SVGGElement>("[data-wing]")),
      x: i === 0 ? -60 : window.innerWidth + 60,
      y: i === 0 ? window.innerHeight * 0.3 : window.innerHeight * 0.75,
      vx: i === 0 ? 30 : -24,
      vy: i === 0 ? -6 : 4,
      angle: i === 0 ? 90 : -90,
      turn: 0,
      tx: 0,
      ty: 0,
      retargetAt: 0,
      speed: (i === 0 ? 38 : 28) * (small ? 0.7 : 1),
      phase: rand(0, Math.PI * 2),
      rate: i === 0 ? 1.45 : 1.1,
      amp: 1,
      ampTarget: 1,
      glideUntil: 0,
      nextGlide: now0 + rand(3500, 7000),
      size,
    }));
    flyers.forEach((f) => pickTarget(f, now0));

    const step = (dt: number, now: number) => {
      const zone = keepOut();
      for (const f of flyers) {
        if (now > f.retargetAt || Math.hypot(f.tx - f.x, f.ty - f.y) < 40) pickTarget(f, now);
        // Steer toward the target, with a slow sideways wander so the path never runs straight.
        const dx = f.tx - f.x;
        const dy = f.ty - f.y;
        const d = Math.hypot(dx, dy) || 1;
        const wander = Math.sin(now / 1700 + f.phase) * 0.55;
        let ax = (dx / d) * f.speed - f.vx + (-dy / d) * f.speed * wander;
        let ay = (dy / d) * f.speed - f.vy + (dx / d) * f.speed * wander;
        if (zone && f.x > zone.l && f.x < zone.r && f.y > zone.t && f.y < zone.b) {
          // Inside the keep-out zone: drift out the nearest way instead of hovering over the words.
          const exitUp = f.y - zone.t;
          const exitRight = zone.r - f.x;
          if (exitRight < exitUp) ax += f.speed * 2.2;
          else ay -= f.speed * 2.2;
        }
        f.vx += ax * dt * 0.9;
        f.vy += ay * dt * 0.9;
        const v = Math.hypot(f.vx, f.vy) || 1;
        const cap = f.speed * 1.35;
        if (v > cap) {
          f.vx = (f.vx / v) * cap;
          f.vy = (f.vy / v) * cap;
        }
        // Flight bobs with each wing beat.
        const lift = Math.sin(f.phase) * 0.6;
        f.x += f.vx * dt;
        f.y += (f.vy + lift * 14) * dt;

        // Heading and bank: the body points along travel; turning tilts it a little further and narrows it (roll).
        const heading = (Math.atan2(f.vy, f.vx) * 180) / Math.PI + 90;
        let delta = heading - f.angle;
        delta = ((delta + 540) % 360) - 180;
        f.turn += (delta - f.turn) * Math.min(1, dt * 3);
        f.angle += delta * Math.min(1, dt * 2.2);
        const bank = Math.max(-16, Math.min(16, f.turn * 0.35));
        const roll = 1 - Math.min(0.18, Math.abs(f.turn) * 0.004);

        // Wing beat with an irregular rate and occasional glides.
        if (now > f.nextGlide && f.glideUntil < now) {
          f.glideUntil = now + rand(1200, 2800);
          f.nextGlide = f.glideUntil + rand(2500, 6000);
        }
        f.ampTarget = now < f.glideUntil ? 0.08 : 1;
        f.amp += (f.ampTarget - f.amp) * Math.min(1, dt * 4);
        const rate = f.rate * (1 + Math.sin(now / 2300 + f.phase) * 0.12);
        f.phase += dt * Math.PI * 2 * rate;
        const beat = Math.pow(0.5 + 0.5 * Math.sin(f.phase), 1.3);
        const sx = 1 - f.amp * beat * 0.6;
        f.wings[0]?.setAttribute("transform", `scale(${sx.toFixed(3)},1)`);
        f.wings[1]?.setAttribute("transform", `scale(${(-sx).toFixed(3)},1)`);

        f.el.style.transform = `translate3d(${(f.x - f.size / 2).toFixed(1)}px, ${(f.y - f.size / 2).toFixed(1)}px, 0) rotate(${(f.angle + bank).toFixed(1)}deg) scale(${roll.toFixed(3)}, 1)`;
      }
    };
    els.forEach((el) => (el.style.opacity = "1"));
    return subscribe(step);
  }, []);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-[5] overflow-hidden">
      <div ref={a} className="absolute top-0 left-0 size-[38px] opacity-0 transition-opacity duration-1000 will-change-transform md:size-[52px]">
        <Butterfly id={ida} tone="ember" />
      </div>
      <div ref={b} className="absolute top-0 left-0 size-[38px] opacity-0 transition-opacity duration-1000 will-change-transform md:size-[52px]">
        <Butterfly id={idb} tone="pink" />
      </div>
    </div>
  );
}
