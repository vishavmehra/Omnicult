"use client";

import { useEffect, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { getField, onField, rand } from "./meadow-field";

/*
 * A loose file of ants walking right to left along the bottom edge, side view: gaster, petiole node, mesosoma, head
 * with mandibles and elbowed antennae, six legs moving in the alternating tripod gait. They stop and go, wave their
 * antennae while stopped, and the second one carries a seed. When one leaves the screen it rejoins at the back of the
 * file. Four on wider screens, two on phones.
 */

// Legs: coxa, knee, foot. Near legs in front of the body, far legs behind it and fainter. Tripod sets alternate.
const LEGS: { d: string; cx: number; cy: number; set: 0 | 1; far: boolean }[] = [
  { d: "M3.2 -2.8 L5.8 -5.2 L8.2 2.6", cx: 3.2, cy: -2.8, set: 1, far: true },
  { d: "M1.4 -2.8 L2.4 -5 L3.4 2.6", cx: 1.4, cy: -2.8, set: 0, far: true },
  { d: "M-0.4 -2.8 L-3.2 -5.2 L-6.2 2.6", cx: -0.4, cy: -2.8, set: 1, far: true },
  { d: "M2.4 -2.4 L4.8 -5 L7.2 3", cx: 2.4, cy: -2.4, set: 0, far: false },
  { d: "M0.6 -2.4 L1.6 -4.8 L2.4 3", cx: 0.6, cy: -2.4, set: 1, far: false },
  { d: "M-1.2 -2.4 L-4 -5 L-7.2 3", cx: -1.2, cy: -2.4, set: 0, far: false },
];

function AntArt({ seed }: { seed?: boolean }) {
  const leg = (l: (typeof LEGS)[number]) => (
    <path
      key={l.d}
      data-leg={l.set}
      data-cx={l.cx}
      data-cy={l.cy}
      d={l.d}
      stroke="var(--critter-ink)"
      strokeOpacity={l.far ? 0.55 : 1}
      strokeWidth={l.far ? 0.7 : 0.85}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
  return (
    <svg viewBox="-14 -11 28 15" className="block size-full overflow-visible" aria-hidden>
      {LEGS.filter((l) => l.far).map(leg)}
      <ellipse cx="-8" cy="-3.4" rx="4.6" ry="3.3" transform="rotate(-12 -8 -3.4)" fill="var(--critter-ink)" />
      <ellipse cx="-3.2" cy="-3.1" rx="1.2" ry="1.5" fill="var(--critter-ink)" />
      <path d="M-2.4 -2.6 C-2.6 -4.6 -1 -5.6 0.6 -5 C2 -4.6 2.8 -5.4 3.8 -4.4 C4.4 -3.6 4 -2.4 3 -2.2 Z" fill="var(--critter-ink)" />
      <ellipse cx="6.2" cy="-4.4" rx="2.7" ry="2.3" fill="var(--critter-ink)" />
      <path d="M8.4 -3.6 L9.9 -2.6" stroke="var(--critter-ink)" strokeWidth="0.7" strokeLinecap="round" />
      <path d="M-11.8 -5.2 C-9.6 -6.8 -6.2 -7 -4.2 -5.6 M4.6 -6.2 C5.6 -6.8 7 -6.8 7.8 -6" stroke="var(--critter-rim)" strokeWidth="0.5" fill="none" strokeLinecap="round" />
      <circle cx="6.9" cy="-4.9" r="0.5" fill="var(--critter-rim)" />
      <g data-antenna>
        <path d="M6.8 -6.4 L7.2 -9.4 L10.6 -8" stroke="var(--critter-ink)" strokeWidth="0.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </g>
      {seed ? <ellipse cx="10.9" cy="-3.2" rx="1.9" ry="1.3" fill="var(--daisy)" stroke="var(--daisy-edge)" strokeWidth="0.4" /> : null}
      {LEGS.filter((l) => !l.far).map(leg)}
    </svg>
  );
}

const COUNT = 4;

export function Ants() {
  const wraps = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const ants = wraps.current.map((el, i) => ({
      el: el!,
      legs: Array.from(el!.querySelectorAll<SVGPathElement>("[data-leg]")).map((p) => ({
        p,
        set: Number(p.dataset.leg),
        pivot: `${p.dataset.cx} ${p.dataset.cy}`,
      })),
      antenna: el!.querySelector<SVGGElement>("[data-antenna]"),
      x: 0,
      i,
      speed: rand(24, 34),
      gait: rand(0, Math.PI * 2),
      pauseUntil: 0,
    }));
    const place = (a: (typeof ants)[number], y: number, bob = 0) => {
      a.el.style.transform = `translate3d(${a.x.toFixed(1)}px, ${(y + bob).toFixed(2)}px, 0) translate(-50%, -100%) scaleX(-1)`;
    };
    const lineUp = () => {
      const f = getField();
      ants.forEach((a) => {
        a.x = f.w * (0.6 + a.i * 0.09);
        a.el.style.display = a.i < (f.phone ? 2 : COUNT) ? "" : "none";
        place(a, f.h);
        a.el.style.opacity = "1";
      });
    };

    if (prefersReducedMotion()) return onField(lineUp);
    lineUp();

    return subscribe((dt, now) => {
      const f = getField();
      const n = f.phone ? 2 : COUNT;
      for (const a of ants) {
        if (a.i >= n) {
          a.el.style.display = "none";
          continue;
        }
        a.el.style.display = "";
        const paused = now < a.pauseUntil;
        if (!paused && Math.random() < dt * 0.07) a.pauseUntil = now + rand(400, 1300);
        if (!paused) {
          a.x -= a.speed * f.s * dt;
          a.gait += dt * a.speed * 0.42;
        }
        // Off the left edge: rejoin at the back of the file, off the right edge.
        if (a.x < -30) {
          const last = Math.max(...ants.slice(0, n).map((o) => o.x));
          a.x = Math.max(f.w + 20, last + rand(40, 140) * f.s);
          a.speed = rand(24, 34);
        }
        const swing = paused ? 0 : Math.sin(a.gait) * 16;
        for (const l of a.legs) l.p.setAttribute("transform", `rotate(${(l.set ? swing : -swing).toFixed(1)} ${l.pivot})`);
        const wave = Math.sin(now / (paused ? 90 : 240) + a.i) * (paused ? 14 : 6);
        a.antenna?.setAttribute("transform", `rotate(${wave.toFixed(1)} 6.8 -6.4)`);
        place(a, f.h, paused ? 0 : Math.abs(Math.sin(a.gait)) * -0.5);
      }
    });
  }, []);

  return (
    <>
      {Array.from({ length: COUNT }, (_, i) => (
        <div
          key={i}
          ref={(el) => {
            wraps.current[i] = el;
          }}
          data-creature="ant"
          className="absolute top-0 left-0 aspect-[28/15] w-[calc(26px*var(--s))] opacity-0 transition-opacity duration-1000"
        >
          <AntArt seed={i === 1} />
        </div>
      ))}
    </>
  );
}
