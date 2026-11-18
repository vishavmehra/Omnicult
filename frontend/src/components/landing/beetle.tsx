"use client";

import { useEffect, useId, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { getField, onField, rand, type Field } from "./meadow-field";

/*
 * A ground beetle on the bottom edge, side view: domed elytra with a faint iridescent sheen and fine striae, a rounded
 * pronotum, a head with mandibles and long beaded antennae, six jointed legs in the tripod gait. It patrols a stretch of
 * the ground slowly, stops to sweep its antennae, and turns round at the ends of its beat (or on a whim).
 */

const LEGS: { d: string; cx: number; cy: number; set: 0 | 1; far: boolean }[] = [
  { d: "M7.4 -3.6 L11.4 -7.4 L15.6 2.6", cx: 7.4, cy: -3.6, set: 1, far: true },
  { d: "M2.2 -3.6 L3.4 -8 L5.6 2.6", cx: 2.2, cy: -3.6, set: 0, far: true },
  { d: "M-3.6 -3.6 L-7.6 -7.6 L-13.6 2.6", cx: -3.6, cy: -3.6, set: 1, far: true },
  { d: "M6.4 -3.2 L10.2 -7 L14.2 3", cx: 6.4, cy: -3.2, set: 0, far: false },
  { d: "M1.2 -3.2 L2.2 -7.6 L4.2 3", cx: 1.2, cy: -3.2, set: 1, far: false },
  { d: "M-4.6 -3.2 L-8.8 -7.2 L-15 3", cx: -4.6, cy: -3.2, set: 0, far: false },
];

function BeetleArt({ id }: { id: string }) {
  const sheen = `beetle-sheen-${id}`;
  const leg = (l: (typeof LEGS)[number]) => (
    <path
      key={l.d}
      data-leg={l.set}
      data-cx={l.cx}
      data-cy={l.cy}
      d={l.d}
      stroke="var(--critter-ink)"
      strokeOpacity={l.far ? 0.55 : 1}
      strokeWidth={l.far ? 0.9 : 1.1}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
  return (
    <svg viewBox="-26 -18 56 22" className="block size-full overflow-visible" aria-hidden>
      <defs>
        <linearGradient id={sheen} x1="0" y1="-16" x2="0" y2="-3" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--beetle-sheen)" />
          <stop offset="0.55" stopColor="var(--critter-ink)" />
        </linearGradient>
      </defs>
      {LEGS.filter((l) => l.far).map(leg)}
      <g data-antenna>
        <path d="M18.6 -8.6 C21 -12 24.6 -15 28.4 -16.2" stroke="var(--critter-ink)" strokeWidth="0.9" fill="none" strokeLinecap="round" strokeDasharray="1.6 0.5" />
      </g>
      {/* elytra, striae and a highlight along the dome */}
      <path d="M-21 -4 C-22 -10 -16 -15 -6 -15.5 C2 -15.8 7 -13 8 -8 L8 -3.5 C0 -2.4 -13 -2.4 -21 -4 Z" fill={`url(#${sheen})`} />
      <path d="M-19 -6.6 C-17 -11 -11 -13.6 -3 -13.8 M-17.4 -5 C-15 -8.8 -9.6 -11 -2.6 -11.2 M-15 -4 C-12.6 -6.6 -8 -8.2 -2.4 -8.4" stroke="var(--critter-rim)" strokeWidth="0.4" fill="none" opacity="0.6" />
      <path d="M-15 -12.6 C-9 -14.8 -1 -14.8 4 -12.6" stroke="rgb(255 255 255 / 0.32)" strokeWidth="1.1" fill="none" strokeLinecap="round" />
      {/* pronotum, head, eye, mandibles */}
      <path d="M7 -12.4 C10 -13.6 14 -12.6 15 -9.6 L15 -4 C12 -3 9 -3 7 -3.6 Z" fill="var(--critter-ink)" />
      <path d="M8 -12 C10.6 -12.8 13.4 -12.2 14.4 -10" stroke="var(--critter-rim)" strokeWidth="0.5" fill="none" />
      <path d="M14.5 -9 C17.5 -10 20 -8.5 20.5 -6 C20.5 -4 18.5 -3.2 15 -3.6 Z" fill="var(--critter-ink)" />
      <circle cx="17.6" cy="-7.2" r="1" fill="var(--critter-rim)" />
      <path d="M20 -5.2 C22 -5.4 23.6 -4.6 24 -3.4" stroke="var(--critter-ink)" strokeWidth="0.9" fill="none" strokeLinecap="round" />
      {LEGS.filter((l) => !l.far).map(leg)}
    </svg>
  );
}

const beat = (f: Field) => (f.wide ? [0.3, 0.56] : [0.12, 0.46]);

export function Beetle() {
  const wrap = useRef<HTMLDivElement>(null);
  const id = useId().replace(/:/g, "");

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const legs = Array.from(el.querySelectorAll<SVGPathElement>("[data-leg]")).map((p) => ({ p, set: Number(p.dataset.leg), pivot: `${p.dataset.cx} ${p.dataset.cy}` }));
    const antenna = el.querySelector<SVGGElement>("[data-antenna]");
    let facing = 1;
    let flip = 1; // scaleX during a turn
    let u = 0.35; // position within its beat, 0..1
    const place = (f: Field, bob = 0) => {
      const [a, b] = beat(f);
      const x = f.w * (a + (b - a) * u);
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${(f.h + bob).toFixed(2)}px, 0) translate(-50%, -100%) scaleX(${(flip * facing).toFixed(3)})`;
    };

    if (prefersReducedMotion()) {
      const off = onField((f) => {
        place(f);
        el.style.opacity = "1";
      });
      return off;
    }

    let mode: "walk" | "stop" | "turn" = "walk";
    let timer = rand(4, 9);
    let gait = 0;
    let k = 0;

    const step = (dt: number, now: number) => {
      const f = getField();
      const [a, b] = beat(f);
      const span = Math.max(1, f.w * (b - a));
      let swing = 0;
      if (mode === "walk") {
        u += (facing * 16 * f.s * dt) / span;
        gait += dt * 6;
        swing = Math.sin(gait) * 12;
        timer -= dt;
        if (u > 0.98 || u < 0.02 || (timer < 0 && Math.random() < 0.3)) {
          mode = "turn";
          k = 0;
        } else if (timer < 0) {
          mode = "stop";
          timer = rand(1.4, 3);
        }
      } else if (mode === "stop") {
        timer -= dt;
        if (timer < 0) {
          mode = "walk";
          timer = rand(5, 11);
        }
      } else {
        // Turning round on the spot: seen from the side, it narrows to end-on and widens facing the other way.
        k += dt / 0.5;
        flip = Math.cos(Math.min(1, k) * Math.PI);
        gait += dt * 8;
        swing = Math.sin(gait) * 8;
        if (k >= 1) {
          facing = -facing;
          flip = 1;
          mode = "walk";
          timer = rand(5, 11);
        }
      }
      u = Math.min(1, Math.max(0, u));
      for (const l of legs) l.p.setAttribute("transform", `rotate(${(l.set ? swing : -swing).toFixed(1)} ${l.pivot})`);
      const sweep = mode === "stop" ? Math.sin(now / 260) * 12 : Math.sin(now / 700) * 4;
      antenna?.setAttribute("transform", `rotate(${sweep.toFixed(1)} 18.6 -8.6)`);
      place(f, mode === "walk" ? -Math.abs(Math.sin(gait)) * 0.4 : 0);
    };

    place(getField());
    el.style.opacity = "1";
    return subscribe(step);
  }, []);

  return (
    <div ref={wrap} data-creature="beetle" className="absolute top-0 left-0 aspect-[56/22] w-[calc(60px*var(--s))] opacity-0 transition-opacity duration-1000 will-change-transform">
      <BeetleArt id={id} />
    </div>
  );
}
