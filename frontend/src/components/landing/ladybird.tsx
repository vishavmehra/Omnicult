"use client";

import { useEffect, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { TUFT_H, getField, rand, smooth, sway } from "./meadow-field";

/*
 * A seven-spot ladybird on two blades of the left tuft, drawn in the tuft's own coordinates. She climbs a blade to its
 * tip, pauses, lifts her red elytra, unfolds the membranous wings beneath, flies a short arc to the neighbouring blade
 * and climbs again. Seen from the front of the blade, so her back (spots, the white-patched pronotum) faces us.
 */

type Blade = { p0: [number, number]; p1: [number, number]; p2: [number, number]; phase: number };
const BLADES: Blade[] = [
  { p0: [48, TUFT_H], p1: [44, 104], p2: [54, 42], phase: 1.1 },
  { p0: [84, TUFT_H], p1: [90, 114], p2: [96, 64], phase: 3.8 },
];

const bladeShape = ({ p0, p1, p2 }: Blade) =>
  `M${p0[0] - 3} ${p0[1]} Q${p1[0] - 2.4} ${p1[1]} ${p2[0]} ${p2[1]} Q${p1[0] + 2.8} ${p1[1]} ${p0[0] + 3} ${p0[1]} Z`;

/** Point and heading (degrees, 0 = head up) at u along a blade's centreline, before the blade's own sway. */
function along(b: Blade, u: number) {
  const v = 1 - u;
  const x = v * v * b.p0[0] + 2 * v * u * b.p1[0] + u * u * b.p2[0];
  const y = v * v * b.p0[1] + 2 * v * u * b.p1[1] + u * u * b.p2[1];
  const tx = 2 * v * (b.p1[0] - b.p0[0]) + 2 * u * (b.p2[0] - b.p1[0]);
  const ty = 2 * v * (b.p1[1] - b.p0[1]) + 2 * u * (b.p2[1] - b.p1[1]);
  return { x, y, deg: (Math.atan2(ty, tx) * 180) / Math.PI + 90 };
}

/** The same point after the blade sways by `a` radians about its base. */
function rotated(b: Blade, pt: { x: number; y: number; deg: number }, a: number) {
  const dx = pt.x - b.p0[0];
  const dy = pt.y - b.p0[1];
  return {
    x: b.p0[0] + dx * Math.cos(a) - dy * Math.sin(a),
    y: b.p0[1] + dx * Math.sin(a) + dy * Math.cos(a),
    deg: pt.deg + (a * 180) / Math.PI,
  };
}

export function LadybirdBlades() {
  const blades = useRef<(SVGGElement | null)[]>([]);
  const bug = useRef<SVGGElement>(null);
  const elytra = useRef<(SVGGElement | null)[]>([]);
  const wings = useRef<(SVGGElement | null)[]>([]);
  const legs = useRef<(SVGGElement | null)[]>([]);

  useEffect(() => {
    const SCALE = 1.2;
    let on = 1; // which blade she is on (the outer one is never behind a basking butterfly)
    let u = 0.22;
    let mode: "climb" | "pause" | "open" | "fly" | "close" = "climb";
    let timer = 0;
    let gait = 0;
    let from = { x: 0, y: 0, deg: 0 };
    let landU = 0.34;

    const angle = (i: number, t: number) => sway(BLADES[i].phase, getField().tuftL, t);
    const setOpen = (k: number) => {
      // Each half swings its rear tip outward about a hinge at the front.
      elytra.current[0]?.setAttribute("transform", `rotate(${(34 * k).toFixed(1)} -1 -5)`);
      elytra.current[1]?.setAttribute("transform", `rotate(${(-34 * k).toFixed(1)} 1 -5)`);
      wings.current.forEach((w, i) => w?.setAttribute("transform", `translate(${i ? 1.5 : -1.5} -2) scale(${(i ? 1 : -1) * k} ${0.4 + 0.6 * k})`));
    };
    const draw = (pt: { x: number; y: number; deg: number }) =>
      bug.current?.setAttribute("transform", `translate(${pt.x.toFixed(2)} ${pt.y.toFixed(2)}) rotate(${pt.deg.toFixed(1)}) scale(${SCALE})`);

    if (prefersReducedMotion()) {
      draw(along(BLADES[1], 0.6));
      setOpen(0);
      return;
    }

    return subscribe((dt, now) => {
      const t = now / 1000;
      const a0 = angle(0, t);
      const a1 = angle(1, t);
      blades.current[0]?.setAttribute("transform", `rotate(${((a0 * 180) / Math.PI).toFixed(2)} ${BLADES[0].p0[0]} ${TUFT_H})`);
      blades.current[1]?.setAttribute("transform", `rotate(${((a1 * 180) / Math.PI).toFixed(2)} ${BLADES[1].p0[0]} ${TUFT_H})`);
      const sw = on === 0 ? a0 : a1;
      const here = () => rotated(BLADES[on], along(BLADES[on], u), sw);

      if (mode === "climb") {
        u += (dt * 6.5) / 140; // about 6.5 units a second up a 140-unit blade
        gait += dt * 7;
        legs.current[0]?.setAttribute("transform", `rotate(${(Math.sin(gait * Math.PI) * 9).toFixed(1)})`);
        legs.current[1]?.setAttribute("transform", `rotate(${(-Math.sin(gait * Math.PI) * 9).toFixed(1)})`);
        // Tiny wobble on each step, the way a beetle's dome rocks as it walks.
        const p = here();
        draw({ ...p, deg: p.deg + Math.sin(gait * Math.PI) * 4 });
        if (u >= 0.95) {
          mode = "pause";
          timer = rand(1.6, 3.2);
        }
      } else if (mode === "pause") {
        draw(here());
        timer -= dt;
        if (timer < 0) {
          mode = "open";
          timer = 0;
        }
      } else if (mode === "open") {
        timer += dt / 0.45;
        setOpen(smooth(Math.min(1, timer)));
        draw(here());
        if (timer >= 1) {
          mode = "fly";
          timer = 0;
          from = here();
          on = 1 - on;
          landU = rand(0.3, 0.42);
        }
      } else if (mode === "fly") {
        timer += dt / 1.3;
        const k = Math.min(1, timer);
        const e = smooth(k);
        const to = rotated(BLADES[on], along(BLADES[on], landU), on === 0 ? a0 : a1);
        const x = from.x + (to.x - from.x) * e;
        const y = from.y + (to.y - from.y) * e - Math.sin(k * Math.PI) * 26;
        const dx = to.x - from.x;
        const dy = to.y - from.y - Math.cos(k * Math.PI) * 26 * Math.PI;
        const heading = (Math.atan2(dy, dx) * 180) / Math.PI + 90;
        // Wings buzz: a fast flicker in the span of the membranes.
        wings.current.forEach((w, i) =>
          w?.setAttribute("transform", `translate(${i ? 1.5 : -1.5} -2) scale(${(i ? 1 : -1) * (0.75 + Math.random() * 0.25)} 1)`),
        );
        // Fly facing the way she travels, then turn to face up the blade for the last stretch.
        const turn = ((to.deg - heading + 540) % 360) - 180;
        draw({ x, y, deg: heading + turn * Math.max(0, (k - 0.8) / 0.2) });
        if (k >= 1) {
          u = landU;
          mode = "close";
          timer = 1;
        }
      } else {
        timer -= dt / 0.35;
        setOpen(smooth(Math.max(0, timer)));
        draw(here());
        if (timer <= 0) mode = "climb";
      }
    });
  }, []);

  return (
    <g aria-hidden>
      {BLADES.map((b, i) => (
        <g
          key={b.phase}
          ref={(el) => {
            blades.current[i] = el;
          }}
        >
          <path d={bladeShape(b)} fill="var(--tuft)" />
          <path d={`M${b.p0[0] + 1} ${b.p0[1] - 30} Q${b.p1[0] + 1.6} ${b.p1[1]} ${b.p2[0]} ${b.p2[1]}`} stroke="var(--tuft-rim)" strokeWidth="0.8" fill="none" />
        </g>
      ))}
      <g ref={bug} data-creature="ladybird">
        {/* legs in two alternating sets, peeking out from under the dome */}
        {[0, 1].map((set) => (
          <g
            key={set}
            ref={(el) => {
              legs.current[set] = el;
            }}
            stroke="var(--critter-ink)"
            strokeWidth="0.9"
            strokeLinecap="round"
          >
            {(set ? [[-1, -3], [1, 1], [-1, 5]] : [[1, -3], [-1, 1], [1, 5]]).map(([sx, y]) => (
              <path key={`${sx}${y}`} d={`M${sx * 6.6} ${y} l${sx * 3} ${y < 0 ? -1.8 : y > 2 ? 2 : 0.4}`} />
            ))}
          </g>
        ))}
        {/* membranous hind wings, folded away until she flies */}
        {[0, 1].map((i) => (
          <g
            key={i}
            ref={(el) => {
              wings.current[i] = el;
            }}
            transform={`translate(${i ? 1.5 : -1.5} -2) scale(0 0.4)`}
          >
            <path d="M0 0 C6 -5 15 -4.5 19 1 C15.5 5 7 4.5 0 2 Z" fill="var(--critter-wing)" stroke="var(--critter-wing-edge)" strokeWidth="0.4" />
            <path d="M1 1 C7 -1 13 -0.5 17 1.6" stroke="var(--critter-wing-edge)" strokeWidth="0.35" fill="none" />
          </g>
        ))}
        {/* elytra: each half hinges at the front, carrying its own spots */}
        {[-1, 1].map((sx, i) => (
          <g
            key={sx}
            ref={(el) => {
              elytra.current[i] = el;
            }}
          >
            <path d={`M0 -5.6 C${sx * -0.4} -5.6 ${sx * 9} -3.6 ${sx * 9.2} 2.6 C${sx * 9.2} 8.4 ${sx * 4.8} 11.8 0 11.8 Z`} fill="var(--ladybird)" stroke="var(--critter-ink)" strokeWidth="0.5" />
            <circle cx={sx * 4.4} cy="-0.6" r="1.85" fill="var(--critter-ink)" />
            <circle cx={sx * 5.6} cy="5" r="2.05" fill="var(--critter-ink)" />
            <circle cx={sx * 2.6} cy="8.8" r="1.45" fill="var(--critter-ink)" />
            <path d={`M0 -5.4 A1.6 1.6 0 0 ${sx > 0 ? 1 : 0} 0 -2.2 Z`} fill="var(--critter-ink)" />
            <ellipse cx={sx * 4.2} cy="-3.1" rx="1.7" ry="0.9" transform={`rotate(${sx * -25} ${sx * 4.2} -3.1)`} fill="rgb(255 255 255 / 0.5)" />
          </g>
        ))}
        {/* pronotum with its two white patches, head, eyes, antennae */}
        <path d="M-6.2 -5 C-5.8 -9.2 5.8 -9.2 6.2 -5 C3 -4.1 -3 -4.1 -6.2 -5 Z" fill="var(--critter-ink)" />
        <ellipse cx="-3.7" cy="-6.6" rx="1.5" ry="1.1" fill="rgb(255 255 255 / 0.92)" />
        <ellipse cx="3.7" cy="-6.6" rx="1.5" ry="1.1" fill="rgb(255 255 255 / 0.92)" />
        <ellipse cx="0" cy="-9.4" rx="3.1" ry="1.9" fill="var(--critter-ink)" />
        <circle cx="-1.6" cy="-9.9" r="0.55" fill="rgb(255 255 255 / 0.8)" />
        <circle cx="1.6" cy="-9.9" r="0.55" fill="rgb(255 255 255 / 0.8)" />
        <path d="M-1.3 -10.9 l-1.3 -2 M1.3 -10.9 l1.3 -2" stroke="var(--critter-ink)" strokeWidth="0.6" strokeLinecap="round" />
      </g>
    </g>
  );
}
