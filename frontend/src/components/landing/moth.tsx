"use client";

import { useEffect, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { PLANTS, clamp, getField, onField, perchAt, rand, repel, type Pt } from "./meadow-field";

/*
 * An underwing moth, from above: feathery antennae, a furry thorax, broad cryptic grey forewings with zig-zag cross
 * lines and a kidney spot. At rest on a seed stalk (the right tuft's; the left one's when a wide left margin gives it
 * room) it folds its wings back into a delta that hides the hindwings; before flying it shivers to warm up, then
 * flutters off in a jittery, zig-zagging flight that flashes the amber-banded hindwings, and comes back to its stalk.
 * It keeps longer hours in the dark theme. Hidden on phones.
 */

const FORE = "M-3 -8 C-12 -15.5 -28 -21.5 -38.5 -20.5 C-42.5 -20 -42.5 -15.5 -39.5 -12.5 C-32 -5.5 -20 0.5 -4 -0.4 Z";
const HIND = "M-3 -1 C-12 -1.5 -26 2.5 -30.5 9 C-32.5 13 -28.5 16.5 -22 15.2 C-14 13.6 -7 8.4 -3 3 Z";

function Side({ mirror }: { mirror?: boolean }) {
  return (
    <g data-side transform={mirror ? "scale(-1,1)" : undefined}>
      <g data-hind>
        <path d={HIND} fill="var(--moth-wing)" stroke="var(--moth-line)" strokeWidth="0.5" />
        <path d="M-8 1.5 C-15 2.2 -23 5.4 -27 10 C-24 12.6 -17 11.6 -11 7.6 C-8.6 6 -7.6 4 -8 1.5 Z" fill="var(--bee-amber)" opacity="0.75" />
        <path d="M-10 12.6 C-17 15 -25 15 -29.4 11" stroke="var(--moth-line)" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      </g>
      <g data-fore>
        <path d={FORE} fill="var(--moth-wing)" stroke="var(--moth-line)" strokeWidth="0.5" />
        <path d="M-9 -11.6 C-11.4 -8 -10.6 -4.6 -12.4 -1.2" stroke="var(--moth-line)" strokeWidth="0.7" fill="none" />
        <path d="M-27 -19.4 L-25 -16 L-28 -13 L-25.5 -10 L-28 -7 L-25 -3.4" stroke="var(--moth-line)" strokeWidth="0.75" fill="none" strokeLinejoin="round" />
        <path d="M-35 -19.6 C-33 -16 -36.5 -13 -34 -9.4" stroke="var(--moth-line)" strokeWidth="0.55" fill="none" opacity="0.8" />
        <ellipse cx="-17.5" cy="-10.5" rx="2.4" ry="1.6" fill="none" stroke="var(--moth-line)" strokeWidth="0.6" transform="rotate(-20 -17.5 -10.5)" />
        <ellipse cx="-14" cy="-6.6" rx="1.1" ry="1.1" fill="var(--moth-line)" />
        <path d="M-6 -6 C-14 -12 -24 -17 -36 -19" stroke="rgb(255 255 255 / 0.18)" strokeWidth="0.8" fill="none" />
      </g>
    </g>
  );
}

function Antenna({ mirror }: { mirror?: boolean }) {
  return (
    <g transform={mirror ? "scale(-1,1)" : undefined}>
      <path d="M-1.6 -13.4 C-4.4 -20.4 -9.4 -24.8 -13.2 -25.2 C-10.4 -21.6 -6.4 -17 -1 -12.6 Z" fill="var(--moth-line)" opacity="0.45" />
      <path d="M-1.2 -13 C-4 -18 -8 -22.4 -12.6 -24.6" stroke="var(--moth-line)" strokeWidth="0.8" fill="none" strokeLinecap="round" />
      <path d="M-3 -16 l-1.7 0.7 M-4.6 -18.2 l-1.7 0.8 M-6.4 -20.2 l-1.6 0.9 M-8.4 -21.8 l-1.4 1 M-10.4 -23.2 l-1.1 1" stroke="var(--moth-line)" strokeWidth="0.45" strokeLinecap="round" />
    </g>
  );
}

function MothArt() {
  return (
    <svg viewBox="-42 -30 84 56" className="block size-full overflow-visible" aria-hidden>
      <Side />
      <Side mirror />
      <Antenna />
      <Antenna mirror />
      <path d="M-3.4 1 C-3.8 8 -2.8 15 0 19.5 C2.8 15 3.8 8 3.4 1 Z" fill="var(--moth-line)" />
      {[6, 10, 14].map((y) => (
        <path key={y} d={`M-3 ${y} Q0 ${y + 1.2} 3 ${y}`} stroke="var(--moth-wing)" strokeWidth="0.5" fill="none" />
      ))}
      <ellipse cx="0" cy="-4" rx="4.6" ry="6" fill="var(--moth-line)" />
      <ellipse cx="0" cy="-4" rx="4.6" ry="6" fill="none" stroke="var(--moth-wing)" strokeWidth="1.2" strokeDasharray="0.5 1" />
      <circle cx="0" cy="-11" r="2.9" fill="var(--moth-line)" />
      <circle cx="-1.9" cy="-11.8" r="1.1" fill="var(--critter-ink)" />
      <circle cx="1.9" cy="-11.8" r="1.1" fill="var(--critter-ink)" />
    </svg>
  );
}

export function Moth() {
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const sides = Array.from(el.querySelectorAll<SVGGElement>("[data-side]"));
    const fores = Array.from(el.querySelectorAll<SVGGElement>("[data-fore]"));
    const hinds = Array.from(el.querySelectorAll<SVGGElement>("[data-hind]"));
    const place = (x: number, y: number, deg: number) => {
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -46%) rotate(${deg.toFixed(1)}deg)`;
    };
    /** rest = 1 folds the wings back into the resting delta; spread = the flap opening, 1 = flat. */
    const pose = (rest: number, spread: number) => {
      fores.forEach((g) => g.setAttribute("transform", `rotate(${(-44 * rest).toFixed(1)} -3 -7)`));
      hinds.forEach((g) => {
        g.setAttribute("transform", `rotate(${(-40 * rest).toFixed(1)} -3 -1)`);
        g.setAttribute("opacity", (1 - rest).toFixed(2));
      });
      sides[0]?.setAttribute("transform", `scale(${spread.toFixed(3)},1)`);
      sides[1]?.setAttribute("transform", `scale(${(-spread).toFixed(3)},1)`);
    };
    // Home: the left seed stalk only when a wide left margin gives it room to fly; otherwise the right one.
    const leftHome = (f: ReturnType<typeof getField>) => f.wide && f.pockets.length > 5;
    const stalk = (t: number, still: boolean) => {
      const f = getField();
      const p = perchAt(leftHome(f) ? PLANTS.seedL : PLANTS.seedR, f, t, still);
      return { x: p.x, y: p.y + 6 * f.s, deg: p.deg };
    };
    const show = (on: boolean) => {
      el.style.display = on ? "" : "none";
    };

    if (prefersReducedMotion()) {
      const off = onField((f) => {
        show(!f.phone);
        const p = stalk(0, true);
        place(p.x, p.y, p.deg);
        pose(1, 1);
        el.style.opacity = "1";
      });
      return off;
    }

    const dark = () => document.documentElement.classList.contains("dark");
    let mode: "rest" | "shiver" | "flutter" | "return" = "rest";
    let timer = rand(4, 9);
    const pos: Pt = { x: 0, y: 0 };
    let deg = 0;
    let dir = -Math.PI / 2;
    let turnAt = 0;
    let speed = 0;
    let phase = 0;
    let rest = 1;

    const step = (dt: number, now: number) => {
      const f = getField();
      if (f.phone) {
        show(false);
        return;
      }
      show(true);
      const t = now / 1000;
      const home = stalk(t, false);

      if (mode === "rest" || mode === "shiver") {
        pos.x = home.x;
        pos.y = home.y;
        deg = home.deg;
        rest = Math.min(1, rest + dt * 3);
        timer -= dt;
        if (mode === "rest") {
          pose(rest, 1);
          if (timer < 0) {
            mode = "shiver";
            timer = 0.9;
          }
        } else {
          // Warming up: the folded wings vibrate before take-off.
          pose(rest, 0.9 + Math.random() * 0.1);
          if (timer < 0) {
            mode = "flutter";
            timer = rand(4, 8);
            dir = -Math.PI / 2 + rand(-0.6, 0.6);
            speed = 150 * f.s;
          }
        }
      } else {
        rest = Math.max(0, rest - dt * 5);
        if (mode === "flutter") {
          // Jittery flight: a new heading every fraction of a second, pulled back toward home if it strays.
          if (now > turnAt) {
            turnAt = now + rand(120, 340);
            const cx = home.x + (leftHome(f) ? 1 : -1) * 90 * f.s;
            const cy = home.y - 140 * f.s;
            const away = Math.hypot(pos.x - cx, pos.y - cy);
            const back = Math.atan2(cy - pos.y, cx - pos.x);
            dir = away > 170 * f.s ? back + rand(-0.5, 0.5) : dir + rand(-1.3, 1.3);
            speed = rand(110, 210) * f.s;
          }
          const push = repel(pos, f, 22 * f.s);
          if (push.x || push.y) dir = Math.atan2(push.y, push.x);
          pos.x = clamp(pos.x + Math.cos(dir) * speed * dt, 12, f.w - 12);
          pos.y = clamp(pos.y + Math.sin(dir) * speed * dt, 90, f.h - 12);
          timer -= dt;
          if (timer < 0) mode = "return";
        } else {
          const dx = home.x - pos.x;
          const dy = home.y - pos.y;
          const d = Math.hypot(dx, dy);
          const v = Math.min(d * 3, 180 * f.s);
          dir = Math.atan2(dy, dx) + (d > 30 * f.s ? Math.sin(t * 9) * 0.5 : 0);
          pos.x += Math.cos(dir) * v * dt;
          pos.y += Math.sin(dir) * v * dt;
          if (d < 3 * f.s) {
            mode = "rest";
            timer = dark() ? rand(6, 12) : rand(14, 26);
          }
        }
        const heading = mode === "return" && Math.hypot(home.x - pos.x, home.y - pos.y) < 40 * f.s ? home.deg : (dir * 180) / Math.PI + 90;
        deg += ((((heading - deg + 540) % 360) + 360) % 360 - 180) * Math.min(1, dt * 12);
        // A fast, irregular wing beat.
        phase += dt * Math.PI * 2 * (5 + Math.random() * 2.5);
        pose(rest, 1 - (0.5 + 0.5 * Math.sin(phase)) * 0.82);
      }
      place(pos.x, pos.y, deg);
    };

    const p0 = stalk(performance.now() / 1000, false);
    place(p0.x, p0.y, p0.deg);
    pose(1, 1);
    el.style.opacity = "1";
    return subscribe(step);
  }, []);

  return (
    <div ref={wrap} data-creature="moth" className="absolute top-0 left-0 aspect-[84/56] w-[calc(80px*var(--s))] origin-[50%_46%] opacity-0 transition-opacity duration-1000 will-change-transform">
      <MothArt />
    </div>
  );
}
