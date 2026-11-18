"use client";

import { useEffect, useRef } from "react";

import { subscribe } from "@/components/ambient/ticker";

import { LadybirdBlades } from "./ladybird";
import { PLANTS, TUFT_H, TUFT_W, getField, onField, sway, type Plant } from "./meadow-field";

/*
 * Two foreground tufts on the bottom edge, one in each corner: grass blades, daisies, a seed stalk and a reed. They are
 * the meadow's fixed perches (butterflies bask on the daisies, the bee works them, the dragonfly returns to the reed, the
 * moth rests on the seed stalk, the ladybird climbs its own two blades). They stand in front of the page like foreground
 * grass in a diorama, sway in the same slow breeze as the grass band behind, and never move with the page.
 */

type Blade = { b: number; h: number; lean: number; phase: number };
const BLADES: Record<"L" | "R", Blade[]> = {
  L: [
    { b: 30, h: 70, lean: -12, phase: 0.2 },
    { b: 44, h: 104, lean: -5, phase: 1.7 },
    { b: 58, h: 86, lean: 6, phase: 3.1 },
    { b: 72, h: 118, lean: 13, phase: 4.4 },
    { b: 88, h: 64, lean: 17, phase: 5.2 },
  ],
  R: [
    { b: 32, h: 66, lean: -17, phase: 0.9 },
    { b: 48, h: 112, lean: -12, phase: 2.4 },
    { b: 62, h: 90, lean: -5, phase: 3.6 },
    { b: 76, h: 106, lean: 6, phase: 4.9 },
    { b: 90, h: 70, lean: 12, phase: 5.7 },
  ],
};

const bladePath = ({ b, h, lean }: Blade) =>
  `M${b - 2.6} ${TUFT_H} Q${b + lean * 0.35 - 1} ${TUFT_H - h * 0.55} ${b + lean} ${TUFT_H - h} Q${b + lean * 0.35 + 1.8} ${TUFT_H - h * 0.55} ${b + 2.6} ${TUFT_H} Z`;
const bladeRim = ({ b, h, lean }: Blade) => `M${b + lean * 0.12 + 1} ${TUFT_H - h * 0.28} Q${b + lean * 0.42 + 1} ${TUFT_H - h * 0.68} ${b + lean} ${TUFT_H - h}`;
const stem = (p: Plant) => `M${p.base} ${TUFT_H} Q${p.base + (p.hx - p.base) * 0.15} ${(TUFT_H + p.hy) / 2} ${p.hx} ${p.hy}`;

function Daisy({ p }: { p: Plant }) {
  return (
    <>
      <path d={stem(p)} stroke="var(--tuft)" strokeWidth="1.9" fill="none" strokeLinecap="round" />
      <path d={`M${p.base + (p.hx - p.base) * 0.1} ${TUFT_H - 34} q-9 -4 -12 -13 q9 2 12 13 Z`} fill="var(--tuft)" />
      {Array.from({ length: 12 }, (_, i) => (
        <ellipse key={i} cx={p.hx} cy={p.hy - 4.7} rx="1.75" ry="3.9" transform={`rotate(${i * 30} ${p.hx} ${p.hy})`} fill="var(--daisy)" stroke="var(--daisy-edge)" strokeWidth="0.45" />
      ))}
      <circle cx={p.hx} cy={p.hy} r="2.9" fill="var(--bee-amber)" />
      <circle cx={p.hx - 0.8} cy={p.hy - 0.9} r="0.9" fill="rgb(255 255 255 / 0.35)" />
    </>
  );
}

function SeedStalk({ p, slim }: { p: Plant; slim?: boolean }) {
  // A grass stem with its seed head: spikelets alternating down the top of the stem.
  const n = slim ? 5 : 7;
  return (
    <>
      <path d={stem(p)} stroke="var(--tuft)" strokeWidth={slim ? 1.5 : 1.7} fill="none" strokeLinecap="round" />
      {Array.from({ length: n }, (_, i) => {
        const y = p.hy + 3 + i * 3.6;
        const x = p.hx + (p.base - p.hx) * ((y - p.hy) / (TUFT_H - p.hy)) * 0.15;
        const side = i % 2 ? 1 : -1;
        return <ellipse key={i} cx={x + side * 1.6} cy={y} rx="1.3" ry="3" transform={`rotate(${side * 24} ${x + side * 1.6} ${y})`} fill="var(--tuft)" stroke="var(--tuft-rim)" strokeWidth="0.4" />;
      })}
      <path d={`M${p.hx} ${p.hy + 1} l0 -3.5`} stroke="var(--tuft)" strokeWidth="1.2" strokeLinecap="round" />
    </>
  );
}

function Tuft({ side, children }: { side: "L" | "R"; children?: React.ReactNode }) {
  const svg = useRef<SVGSVGElement>(null);
  const plants = Object.values(PLANTS).filter((p) => p.side === side) as Plant[];

  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const groups = Array.from(el.querySelectorAll<SVGGElement>(":scope > [data-sway]"));
    const place = () => {
      const f = getField();
      el.style.transform = `translate3d(${(side === "L" ? f.tuftL : f.tuftR).toFixed(1)}px, ${f.h}px, 0) translate(-50%, -100%)`;
      el.style.opacity = "1";
    };
    const offField = onField(place);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return offField;
    const off = subscribe((_, now) => {
      const f = getField();
      const x = side === "L" ? f.tuftL : f.tuftR;
      const t = now / 1000;
      for (const g of groups) {
        const a = (sway(Number(g.dataset.phase), x, t) * 180) / Math.PI;
        g.setAttribute("transform", `rotate(${a.toFixed(2)} ${g.dataset.base} ${TUFT_H})`);
      }
    });
    return () => {
      off();
      offField();
    };
  }, [side]);

  return (
    <svg
      ref={svg}
      data-creature={`tuft-${side}`}
      viewBox={`0 0 ${TUFT_W} ${TUFT_H}`}
      className="absolute top-0 left-0 h-[calc(170px*var(--s))] w-[calc(120px*var(--s))] overflow-visible opacity-0 transition-opacity duration-1000"
      aria-hidden
    >
      {BLADES[side].map((b) => (
        <g key={b.b} data-sway data-base={b.b} data-phase={b.phase}>
          <path d={bladePath(b)} fill="var(--tuft)" />
          <path d={bladeRim(b)} stroke="var(--tuft-rim)" strokeWidth="0.8" fill="none" strokeLinecap="round" />
        </g>
      ))}
      {plants.map((p) => (
        <g key={`${p.base}-${p.hx}`} data-sway data-base={p.base} data-phase={p.phase}>
          {p.kind === "daisy" ? <Daisy p={p} /> : <SeedStalk p={p} slim={p.kind === "reed"} />}
        </g>
      ))}
      {children}
    </svg>
  );
}

export function Tufts() {
  return (
    <>
      <Tuft side="L">
        <LadybirdBlades />
      </Tuft>
      <Tuft side="R" />
    </>
  );
}
