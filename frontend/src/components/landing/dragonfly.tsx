"use client";

import { useEffect, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { PLANTS, airspace, crosses, getField, onField, perchAt, pickPoint, rand, route, smooth, type Pt } from "./meadow-field";
import { flutter, panAt } from "./meadow-sound";

/*
 * A dragonfly, seen from above: two pairs of long glassy wings held flat (the hindwings broader at the base), a dark
 * pterostigma near each wing tip, huge compound eyes that meet on top of the head, a striped thorax and a long,
 * ringed abdomen. It hunts the way dragonflies do: perched on the reed in the right-hand tuft, it sallies out, darts in
 * straight lines between hover points, stops dead and holds there with shimmering wings, swivels to a new heading in a
 * blink, and after a few legs returns to its reed.
 */

const FORE = "M-2.5 -23 C-12 -27 -34 -29.5 -52 -27.5 C-56.5 -27 -57.5 -23.5 -54 -22 C-40 -19.2 -18 -18.6 -2.5 -19.6 Z";
const HIND = "M-2.5 -17 C-14 -17.6 -34 -15.4 -50 -11.4 C-54.6 -10.2 -55 -6.4 -51.4 -6 C-38 -4.8 -20 -6.4 -9 -9 C-6 -9.8 -3.6 -12 -2.5 -14 Z";

function DragonflyArt() {
  return (
    <svg viewBox="-60 -40 120 104" className="block size-full overflow-visible" aria-hidden>
      {[1, -1].map((sx) => (
        <g key={sx} data-wing={sx} transform={sx < 0 ? "scale(-1,1)" : undefined}>
          <g data-pair="hind">
            <path d={HIND} fill="var(--critter-wing)" stroke="var(--critter-wing-edge)" strokeWidth="0.55" />
            <path d="M-3 -16 C-18 -16 -36 -13 -50.6 -9.6 M-4 -13.4 C-18 -12 -32 -9.8 -44 -7.2" stroke="var(--critter-wing-edge)" strokeWidth="0.35" fill="none" />
            <path d="M-12 -15.6 l-1 6 M-20 -15 l-1 7.4 M-28 -14 l-1 7 M-36 -12.8 l-1 6" stroke="var(--critter-wing-edge)" strokeWidth="0.25" opacity="0.7" />
            <rect x="-47.5" y="-12.9" width="4.6" height="1.5" rx="0.4" transform="rotate(-9 -45 -12)" fill="var(--dragonfly-deep)" />
            <path d="M-2.5 -16.5 C-7 -16.4 -10 -13.4 -9 -9.2 C-6 -10 -3.6 -12 -2.5 -14 Z" fill="var(--dragonfly)" opacity="0.28" />
          </g>
          <g data-pair="fore">
            <path d={FORE} fill="var(--critter-wing)" stroke="var(--critter-wing-edge)" strokeWidth="0.55" />
            <path d="M-3 -22.4 C-18 -25.6 -38 -27.4 -53.6 -26 M-4 -20.6 C-20 -21.6 -38 -22 -52 -23.2" stroke="var(--critter-wing-edge)" strokeWidth="0.35" fill="none" />
            <path d="M-14 -24.6 l0.4 5.2 M-23 -25.8 l0.4 6 M-32 -26.4 l0.4 6.2 M-41 -26.6 l0.4 5.6" stroke="var(--critter-wing-edge)" strokeWidth="0.25" opacity="0.7" />
            <rect x="-50.5" y="-28.1" width="4.6" height="1.5" rx="0.4" transform="rotate(3 -48 -27.4)" fill="var(--dragonfly-deep)" />
          </g>
        </g>
      ))}
      {/* abdomen: long and ringed, darker at the tip, with its claspers */}
      <path d="M-1.9 -11 C-2.5 5 -2 30 -1.5 52 L0 56 L1.5 52 C2 30 2.5 5 1.9 -11 Z" fill="var(--dragonfly)" />
      <path d="M-1.6 40 C-1.6 46 -1.5 50 -1.5 52 L0 56 L1.5 52 C1.5 50 1.6 46 1.6 40 Z" fill="var(--dragonfly-deep)" />
      {[-4, 2.5, 9, 15.5, 22, 28.5, 35].map((y) => (
        <path key={y} d={`M-2.3 ${y} L2.3 ${y}`} stroke="var(--dragonfly-deep)" strokeWidth="1.1" />
      ))}
      <path d="M-0.8 55.4 L-1.8 59.6 M0.8 55.4 L1.8 59.6" stroke="var(--dragonfly-deep)" strokeWidth="0.8" strokeLinecap="round" />
      {/* thorax with its pale shoulder stripes */}
      <ellipse cx="0" cy="-18" rx="4.7" ry="7.4" fill="var(--dragonfly-deep)" />
      <path d="M-2 -23.5 L-1.4 -13.5 M2 -23.5 L1.4 -13.5" stroke="var(--dragonfly)" strokeWidth="1.1" strokeLinecap="round" />
      {/* head: eyes meeting on top, face below */}
      <circle cx="-3.3" cy="-28.6" r="3.7" fill="var(--dragonfly)" />
      <circle cx="3.3" cy="-28.6" r="3.7" fill="var(--dragonfly)" />
      <ellipse cx="0" cy="-25" rx="2.7" ry="1.5" fill="var(--dragonfly-deep)" />
      <circle cx="-4.3" cy="-29.8" r="1" fill="rgb(255 255 255 / 0.55)" />
      <circle cx="2.3" cy="-29.8" r="1" fill="rgb(255 255 255 / 0.55)" />
    </svg>
  );
}

export function Dragonfly() {
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const pairs = Array.from(el.querySelectorAll<SVGGElement>("[data-pair]"));
    const place = (x: number, y: number, deg: number) => {
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -21.15%) rotate(${deg.toFixed(1)}deg)`;
    };
    // Perched on the reed tip, its thorax on the stem and its body along it.
    const reed = (t: number, still: boolean) => {
      const f = getField();
      const r = perchAt(PLANTS.reedR, f, t, still);
      return { x: r.x, y: r.y + 4 * f.s, deg: r.deg };
    };

    if (prefersReducedMotion()) {
      const off = onField(() => {
        const r = reed(0, true);
        place(r.x, r.y, r.deg);
        el.style.opacity = "1";
      });
      return off;
    }

    let mode: "perch" | "turn" | "dart" | "hover" | "home" = "perch";
    let timer = rand(2, 4);
    let legs = 0;
    const pos: Pt = { ...reed(performance.now() / 1000, false) };
    airspace.add(pos);
    let deg = 0;
    let from: Pt = { ...pos };
    let to: Pt = { ...pos };
    let fromDeg = 0;
    let toDeg = 0;
    let T = 1;
    let s = 0;
    let shimmer = 0;

    let afterTurn: "dart" | "home" = "dart";
    const aim = (a: Pt, b: Pt) => (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI + 90;
    const nearest = (a: number, b: number) => a + ((((b - a + 540) % 360) + 360) % 360) - 180;
    // A patrol point it can reach in a straight line without crossing a keep-out zone, at least a short hop away.
    const patrol = (f: ReturnType<typeof getField>, m: number): Pt | null => {
      for (let i = 0; i < 14; i++) {
        const p = pickPoint(f, m, "lr", pos);
        if (!crosses(pos, p, f, m * 0.5) && Math.hypot(p.x - pos.x, p.y - pos.y) > 120 * f.s) return p;
      }
      return null;
    };
    const go = (target: Pt, next: "dart" | "home") => {
      from = { ...pos };
      to = target;
      fromDeg = deg;
      toDeg = nearest(deg, aim(pos, target));
      mode = "turn";
      s = 0;
      T = Math.max(0.35, Math.hypot(to.x - from.x, to.y - from.y) / (520 * getField().s));
      afterTurn = next;
    };

    const step = (dt: number, now: number) => {
      const f = getField();
      const t = now / 1000;
      const m = 40 * f.s;
      // Wings: still when perched; a fast shimmer (the two pairs out of phase) whenever it is airborne.
      shimmer += dt * 38;
      const air = mode !== "perch";
      pairs.forEach((g, i) => {
        const a = air ? Math.sin(shimmer + (i % 2) * Math.PI) * 4 : 0;
        g.setAttribute("transform", `rotate(${a.toFixed(2)} -2.5 ${i % 2 ? -21 : -15})`);
        g.setAttribute("opacity", air ? (0.7 + Math.random() * 0.3).toFixed(2) : "1");
      });

      if (mode === "perch") {
        const r = reed(t, false);
        pos.x = r.x;
        pos.y = r.y;
        deg = r.deg;
        timer -= dt;
        if (timer < 0) {
          legs = Math.floor(rand(2, 5));
          const target = patrol(f, m);
          if (target) go(target, "dart");
          else timer = rand(2, 4);
        }
      } else if (mode === "turn") {
        // Swivel to the new heading in a blink, lifting off the reed if it was perched.
        s += dt / 0.16;
        const k = smooth(Math.min(1, s));
        deg = fromDeg + (toDeg - fromDeg) * k;
        if (s >= 1) {
          mode = afterTurn === "home" ? "home" : "dart";
          s = 0;
        }
      } else if (mode === "dart" || mode === "home") {
        s += dt / T;
        const k = Math.min(1, s);
        const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        const target = mode === "home" ? reed(t, false) : to;
        pos.x = from.x + (target.x - from.x) * e;
        pos.y = from.y + (target.y - from.y) * e;
        if (k >= 1) {
          if (mode === "home") {
            mode = "perch";
            timer = rand(3, 7);
          } else {
            mode = "hover";
            timer = rand(1.2, 3.4);
          }
        }
      } else {
        // Hover: held still in the air with a small drift; then the next leg, or home to the reed.
        pos.y += Math.sin(t * 2.6) * 6 * f.s * dt;
        pos.x += Math.sin(t * 1.7) * 4 * f.s * dt;
        timer -= dt;
        if (timer < 0) {
          legs -= 1;
          const target = legs > 0 ? patrol(f, m) : null;
          if (target) go(target, "dart");
          else {
            // Home to the reed, by way of the band above the grass if the straight line would cross a keep-out zone.
            const r = reed(t, false);
            const via = route(pos, r, f, m * 0.5);
            if (via === r) go({ x: r.x, y: r.y }, "home");
            else go(via, "dart");
          }
        }
      }
      if (mode === "home" && s > 0.75) {
        // Settle head-up along the reed for the landing.
        const r = reed(t, false);
        deg = deg + (nearest(deg, r.deg) - deg) * Math.min(1, dt * 10);
      }
      place(pos.x, pos.y, deg);
      // Its wings are heard on a dart, faintly while it hovers, not at all on the reed.
      flutter(mode === "perch" ? 0 : mode === "dart" || mode === "home" ? 1 : 0.4, panAt(pos.x, f.w));
    };

    place(pos.x, pos.y, deg);
    el.style.opacity = "1";
    const off = subscribe(step);
    return () => {
      off();
      airspace.delete(pos);
    };
  }, []);

  return (
    <div ref={wrap} data-creature="dragonfly" className="absolute top-0 left-0 aspect-[120/104] w-[calc(130px*var(--s))] origin-[50%_21.15%] opacity-0 transition-opacity duration-1000 will-change-transform">
      <DragonflyArt />
    </div>
  );
}
