"use client";

import { useEffect, useId, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { PLANTS, airspace, clamp, getField, onField, perchAt, pickPoint, rand, route, type Plant, type Pt } from "./meadow-field";
import { buzz, panAt } from "./meadow-sound";

/*
 * A honeybee working the corner daisies, side view: banded amber abdomen with its sting, a fuzzy thorax, elbowed
 * antennae, a pollen load on the hind leg, and wings drawn as a translucent blur of two strokes. It hovers in front of
 * a flower with a fine, fast jitter, drops onto it to feed, then darts to the next daisy (crossing the page low, above
 * the grass) and sometimes rises for a quick look round the open sky before it comes back.
 */

function BeeArt({ id }: { id: string }) {
  const clip = `bee-abd-${id}`;
  const abdomen = "M-0.5 -4.2 C-6 -8.2 -15.5 -7.4 -19.6 -2.4 C-22.8 1.6 -21.2 7.6 -16 9.8 C-10.2 12.2 -3.2 9.4 0.2 3.8 C1.4 1.4 1 -2.2 -0.5 -4.2 Z";
  const fore = "M4 -6 C1 -14 -7.5 -19.5 -14.5 -18 C-18.5 -16.8 -17 -12.4 -11.2 -9.8 C-6 -7.6 -1 -6.4 4 -6 Z";
  const hind = "M2.4 -5.2 C-1.6 -9.6 -7.4 -12.4 -11.6 -11.4 C-14 -10.6 -12.4 -8 -8.6 -6.6 C-5 -5.6 -1.4 -5.2 2.4 -5.2 Z";
  return (
    <svg viewBox="-26 -22 52 40" className="block size-full overflow-visible" aria-hidden>
      <defs>
        <clipPath id={clip}>
          <path d={abdomen} />
        </clipPath>
      </defs>
      {/* legs, the hind one carrying its pollen load */}
      <path d="M6.4 3 L8.6 7.6 L8 11.6 M3.6 4 L3 9 L4.4 12.8 M0.4 3.8 L-2.6 8.8 L-1.4 13.4" stroke="var(--critter-ink)" strokeWidth="0.95" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <ellipse cx="-2.3" cy="9.6" rx="2.2" ry="1.6" fill="var(--bee-amber)" stroke="var(--critter-ink)" strokeWidth="0.35" />
      {/* banded abdomen and sting */}
      <path d="M-21 4.4 L-24.4 5.9 L-20.8 6.3 Z" fill="var(--critter-ink)" />
      <path d={abdomen} fill="var(--bee-amber)" />
      <g clipPath={`url(#${clip})`} stroke="var(--critter-ink)" fill="none">
        <path d="M-5.6 -9 L-7.6 12" strokeWidth="3" />
        <path d="M-11.2 -9 L-13.2 12" strokeWidth="3" />
        <path d="M-16.8 -8 L-18.8 12" strokeWidth="3.4" />
        <path d="M-22 -6 L-24 12" strokeWidth="4" />
      </g>
      <path d="M-3 -5.6 C-8 -7.6 -14 -6.8 -17.6 -3.4" stroke="rgb(255 255 255 / 0.35)" strokeWidth="0.9" fill="none" strokeLinecap="round" />
      {/* fuzzy thorax */}
      <circle cx="3.5" cy="-1.5" r="6" fill="var(--bee-fur)" />
      <circle cx="3.5" cy="-1.5" r="6" fill="none" stroke="var(--bee-amber)" strokeWidth="1.3" strokeDasharray="0.5 1.1" opacity="0.8" />
      {/* head, eye, antennae */}
      <ellipse cx="10.6" cy="1.2" rx="3.7" ry="4.4" fill="var(--critter-ink)" />
      <ellipse cx="11" cy="0" rx="1.9" ry="3.1" fill="rgb(255 255 255 / 0.14)" />
      <circle cx="11.6" cy="-1.4" r="0.6" fill="rgb(255 255 255 / 0.7)" />
      <path d="M11.8 -2.8 L12.6 -8.2 L16.8 -10" stroke="var(--critter-ink)" strokeWidth="0.9" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* wings: the up and down strokes drawn together as a blur, flickered per frame */}
      {[-30, 16].map((deg, i) => (
        <g key={deg} data-wing={i} transform={`rotate(${deg} 4 -6)`} opacity="0.55">
          <path d={hind} fill="var(--critter-wing)" stroke="var(--critter-wing-edge)" strokeWidth="0.4" />
          <path d={fore} fill="var(--critter-wing)" stroke="var(--critter-wing-edge)" strokeWidth="0.45" />
          <path d="M3 -6.4 C-2 -10 -8 -14 -13 -15.6" stroke="var(--critter-wing-edge)" strokeWidth="0.35" fill="none" />
        </g>
      ))}
    </svg>
  );
}

const FLOWERS: Plant[] = [PLANTS.daisyR1, PLANTS.daisyR2, PLANTS.daisyL];

export function Bee() {
  const wrap = useRef<HTMLDivElement>(null);
  const id = useId().replace(/:/g, "");

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const wings = Array.from(el.querySelectorAll<SVGGElement>("[data-wing]"));
    let facing = -1;
    const place = (x: number, y: number, tilt: number) => {
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -50%) scale(${facing}, 1) rotate(${tilt.toFixed(1)}deg)`;
    };
    // Hover point beside a flower head: a little above it, on the side the bee faces it from.
    const beside = (p: Plant, side: number, t: number, still = false): Pt => {
      const f = getField();
      const h = perchAt(p, f, t, still);
      return { x: h.x + side * 22 * f.s, y: h.y - 12 * f.s };
    };

    if (prefersReducedMotion()) {
      const off = onField(() => {
        const p = beside(FLOWERS[0], 1, 0, true);
        place(p.x, p.y, 0);
        el.style.opacity = "1";
      });
      return off;
    }

    let flower = 0;
    let side = 1;
    let mode: "hover" | "feed" | "dart" | "look" = "hover";
    let timer = rand(1.2, 2.4);
    let look: Pt | null = null;
    const start = beside(FLOWERS[0], side, performance.now() / 1000);
    const p = { ...start };
    airspace.add(p);
    const v = { x: 0, y: 0 };

    const step = (dt: number, now: number) => {
      const f = getField();
      const t = now / 1000;
      const head = perchAt(FLOWERS[flower], f, t, false);
      let goal: Pt;
      if (mode === "look" && look) goal = look;
      else if (mode === "feed") goal = { x: head.x + side * 8 * f.s, y: head.y - 6 * f.s + Math.sin(t * 9) * 0.8 };
      else goal = beside(FLOWERS[flower], side, t);
      const via = mode === "dart" || mode === "look" ? route(p, goal, f) : goal;

      // A stiff, well-damped spring: quick darts that stop dead, the way bees do.
      const k = mode === "dart" ? 10 : 22;
      const c = mode === "dart" ? 6 : 9;
      v.x += ((via.x - p.x) * k - v.x * c) * dt;
      v.y += ((via.y - p.y) * k - v.y * c) * dt;
      const sp = Math.hypot(v.x, v.y);
      const cap = 420 * f.s;
      if (sp > cap) {
        v.x = (v.x / sp) * cap;
        v.y = (v.y / sp) * cap;
      }
      p.x += v.x * dt;
      p.y += v.y * dt;
      const dist = Math.hypot(goal.x - p.x, goal.y - p.y);

      timer -= dt;
      if (mode === "hover" && timer < 0) {
        mode = "feed";
        timer = rand(1.4, 3);
      } else if (mode === "feed" && timer < 0) {
        // Next: another daisy, or now and then a short look round the open sky.
        const peek = pickPoint(f, 16 * f.s, FLOWERS[flower].side === "L" ? "l" : "r", p);
        if (Math.random() < 0.3 && route(p, peek, f) === peek) {
          look = peek;
          mode = "look";
          timer = rand(2.2, 3.4);
        } else {
          flower = (flower + 1 + Math.floor(Math.random() * 2)) % FLOWERS.length;
          side = perchAt(FLOWERS[flower], f, t, false).x > p.x ? -1 : 1;
          mode = "dart";
        }
      } else if (mode === "dart" && dist < 10 * f.s) {
        mode = "hover";
        timer = rand(1, 2.2);
      } else if (mode === "look" && timer < 0) {
        look = null;
        side = perchAt(FLOWERS[flower], f, t, false).x > p.x ? -1 : 1;
        mode = "dart";
      }

      // Face the way it flies; when hovering or feeding, face the flower.
      if (Math.abs(v.x) > 40 * f.s) facing = v.x > 0 ? 1 : -1;
      else if (mode === "hover" || mode === "feed") facing = head.x >= p.x ? 1 : -1;
      const tilt = clamp(v.x * facing * 0.05, -18, 22) + Math.sin(t * 2.3) * 3;
      // A fine, fast tremor while hovering; the wings flicker between their two strokes.
      const jx = Math.sin(t * 31) * 0.9 + Math.sin(t * 17.3) * 0.7;
      const jy = Math.sin(t * 27 + 1) * 1.1 + Math.sin(t * 3.1) * 2;
      const r = Math.random();
      wings[0]?.setAttribute("opacity", (0.3 + 0.45 * r).toFixed(2));
      wings[1]?.setAttribute("opacity", (0.3 + 0.45 * (1 - r)).toFixed(2));
      place(p.x + jx * f.s, p.y + jy * f.s, tilt);
      // Its buzz: loudest on a dart, softer while hovering, silent while it feeds.
      buzz(mode === "feed" ? 0 : mode === "hover" ? 0.5 : 1, panAt(p.x, f.w));
    };

    place(p.x, p.y, 0);
    el.style.opacity = "1";
    const off = subscribe(step);
    return () => {
      off();
      airspace.delete(p);
    };
  }, []);

  return (
    <div ref={wrap} data-creature="bee" className="absolute top-0 left-0 aspect-[52/40] w-[calc(56px*var(--s))] opacity-0 transition-opacity duration-1000 will-change-transform">
      <BeeArt id={id} />
    </div>
  );
}
