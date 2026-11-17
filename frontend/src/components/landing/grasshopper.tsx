"use client";

import { useEffect, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

/*
 * A grasshopper that perches on the page: the top edge of the product picture, the top of a stage card, or the grass
 * line. It sits still with small antenna twitches, then every 6 to 12 seconds crouches, leaps on a parabola with its hind
 * legs extended, and settles on the next perch. Side-view SVG in the ember palette; transform-only motion on the shared
 * ticker; perched and still under prefers-reduced-motion. pointer-events: none.
 */

// Side view, facing right; feet rest on y = 34. Hip at (25, 22); knee at (9, 8).
function Hopper({ femur, tibia, antenna }: { femur: React.Ref<SVGGElement>; tibia: React.Ref<SVGGElement>; antenna: React.Ref<SVGGElement> }) {
  return (
    <svg viewBox="0 -6 68 42" className="block size-full overflow-visible" aria-hidden>
      <ellipse cx="30" cy="35" rx="20" ry="2.2" fill="rgb(0 0 0 / 0.22)" />
      {/* far legs */}
      <path d="M37 24 L33 34 M44 24 L49 34" stroke="var(--hopper-shade)" strokeWidth="1.3" strokeLinecap="round" fill="none" />
      {/* abdomen, segmented */}
      <path d="M6 21 C10 17 22 17 31 19 L31 26 C22 27.5 11 27 6 24 Z" fill="var(--hopper-body)" />
      {[12, 17, 22, 27].map((x) => (
        <path key={x} d={`M${x} 18.6 L${x - 0.8} 26.6`} stroke="var(--hopper-shade)" strokeWidth="0.7" />
      ))}
      {/* wing case over the back */}
      <path d="M38 15.5 C28 14 14 15 4 19.5 C14 18.6 27 18.4 37 19.4 Z" fill="var(--hopper-shade)" stroke="var(--hopper-glow)" strokeWidth="0.5" strokeOpacity="0.55" />
      {/* thorax and pronotum saddle */}
      <path d="M31 17.5 C34 13.5 42 13 45 16 L45.5 24.5 C41 26.5 34 26.5 31 25 Z" fill="var(--hopper-body)" />
      <path d="M32 18 C35 15 41.5 14.6 44.5 17" stroke="var(--hopper-glow)" strokeWidth="0.7" fill="none" opacity="0.7" />
      {/* head */}
      <path d="M44.5 15.5 C48 11.5 54.5 12 56.5 16.5 C58 20.5 56 25.5 51.5 26 C47.5 26.2 45 23 44.5 19.5 Z" fill="var(--hopper-body)" />
      <circle cx="51.5" cy="16.8" r="2.1" fill="var(--hopper-shade)" />
      <circle cx="52.2" cy="16.2" r="0.7" fill="var(--hopper-glow)" />
      <g ref={antenna}>
        <path d="M50.5 13.5 C54 5 59 0 66 -3 M52 13.8 C56.5 7 61 3.5 67 2" stroke="var(--hopper-body)" strokeWidth="0.8" strokeLinecap="round" fill="none" />
      </g>
      {/* near front and middle legs */}
      <path d="M46.5 24.5 L48 29.5 L51 34 M38 25.5 L36.5 30 L34.5 34" stroke="var(--hopper-body)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* hind leg: femur up and back, tibia folded under it */}
      <g ref={femur}>
        <path d="M27 23.5 C22 19 15 12 9.5 7.5 C8 6.4 6.6 7.8 7.5 9.4 C12 15 18.5 21.5 24.5 26 Z" fill="var(--hopper-body)" />
        <path d="M24.5 21.5 C19.5 17 14 11.5 10 8.4" stroke="var(--hopper-glow)" strokeWidth="0.8" fill="none" opacity="0.8" />
        <g ref={tibia}>
          <path d="M9 8.6 L19 33.6 L22.5 34.2" stroke="var(--hopper-body)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </g>
      </g>
    </svg>
  );
}

type Perch = { el: Element | null; ox: number };
const rand = (a: number, b: number) => a + Math.random() * (b - a);

export function Grasshopper() {
  const wrap = useRef<HTMLDivElement>(null);
  const femur = useRef<SVGGElement>(null);
  const tibia = useRef<SVGGElement>(null);
  const antenna = useRef<SVGGElement>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const small = window.innerWidth < 768;
    const W = small ? 42 : 58;
    const H = (W * 42) / 68;
    const footY = (H * 40) / 42; // feet line inside the box (y = 34 of a -6..36 view box)
    const grassY = () => window.innerHeight - (small ? 22 : 34);

    const perchPoint = (p: Perch) => {
      if (!p.el) return { x: p.ox * window.innerWidth, y: grassY(), ok: true };
      const r = p.el.getBoundingClientRect();
      return { x: r.left + p.ox * r.width, y: r.top + 1, ok: r.top > 70 && r.top < window.innerHeight - 30 && r.width > 0 };
    };
    const candidates = (): Perch[] => {
      const list: Perch[] = [{ el: null, ox: rand(0.45, 0.95) }];
      const art = document.querySelector("[data-perch='artefact']");
      if (art) list.push({ el: art, ox: rand(0.55, 0.9) });
      document.querySelectorAll("[data-card]").forEach((card) => {
        const r = card.getBoundingClientRect();
        if (r.left > 0 && r.right < window.innerWidth && r.top > 70 && r.top < window.innerHeight - 60) list.push({ el: card, ox: rand(0.25, 0.75) });
      });
      return list;
    };

    let pos = { x: window.innerWidth * 0.8, y: grassY() };
    let perch: Perch = { el: null, ox: 0.8 };
    let facing = -1;
    const render = (x: number, y: number, rot = 0, squash = 1) => {
      el.style.transform = `translate3d(${(x - W * 0.45).toFixed(1)}px, ${(y - footY).toFixed(1)}px, 0) scale(${facing}, ${squash.toFixed(3)}) rotate(${(rot * facing).toFixed(1)}deg)`;
    };

    if (prefersReducedMotion()) {
      const art = document.querySelector("[data-perch='artefact']");
      perch = art ? { el: art, ox: 0.78 } : perch;
      const p = perchPoint(perch);
      render(p.x, p.y);
      el.style.opacity = "1";
      return;
    }

    let state: "perch" | "crouch" | "leap" | "settle" = "perch";
    let timer = rand(2.5, 5);
    let twitch = rand(1.2, 3);
    let antennaAngle = 0;
    let antennaTarget = 0;
    let from = pos;
    let to: Perch = perch;
    let T = 0.7;
    let s = 0;

    const setLegs = (f: number, t: number) => {
      femur.current?.setAttribute("transform", `rotate(${f.toFixed(1)} 25 22)`);
      tibia.current?.setAttribute("transform", `rotate(${t.toFixed(1)} 9 8)`);
    };

    const step = (dt: number) => {
      // Antenna twitches.
      twitch -= dt;
      if (twitch < 0) {
        antennaTarget = antennaTarget === 0 ? rand(-9, 6) : 0;
        twitch = antennaTarget === 0 ? rand(1.2, 3.2) : rand(0.18, 0.35);
      }
      antennaAngle += (antennaTarget - antennaAngle) * Math.min(1, dt * 14);
      antenna.current?.setAttribute("transform", `rotate(${antennaAngle.toFixed(1)} 51 13.6)`);

      if (state === "perch") {
        const p = perchPoint(perch);
        if (!p.ok) timer = Math.min(timer, 0.4);
        pos = { x: p.x, y: p.y };
        render(pos.x, pos.y);
        setLegs(0, 0);
        timer -= dt;
        if (timer < 0) {
          const options = candidates().filter((c) => c.el !== perch.el || !c.el);
          to = options[Math.floor(Math.random() * options.length)];
          const target = perchPoint(to);
          if (!target.ok) to = { el: null, ox: rand(0.4, 0.95) };
          facing = perchPoint(to).x >= pos.x ? -1 : 1;
          facing = -facing; // the drawing faces right; scale(-1) faces left
          state = "crouch";
          s = 0;
        }
      } else if (state === "crouch") {
        s += dt / 0.22;
        const k = Math.min(1, s);
        render(pos.x, pos.y + k * 1.5, 0, 1 - k * 0.06);
        setLegs(k * 9, k * 6);
        if (s >= 1) {
          state = "leap";
          s = 0;
          from = { ...pos };
          const target = perchPoint(to);
          T = 0.55 + Math.min(0.6, Math.hypot(target.x - from.x, target.y - from.y) / 1400);
        }
      } else if (state === "leap") {
        s += dt / T;
        const k = Math.min(1, s);
        const target = perchPoint(to);
        const apex = Math.min(170, 46 + Math.hypot(target.x - from.x, target.y - from.y) * 0.25);
        const x = from.x + (target.x - from.x) * k;
        const y = from.y + (target.y - from.y) * k - apex * 4 * k * (1 - k);
        const dx = target.x - from.x;
        const dy = target.y - from.y - apex * 4 * (1 - 2 * k);
        const tangent = (Math.atan2(dy, Math.abs(dx) + 1e-3) * 180) / Math.PI;
        render(x, y, Math.max(-38, Math.min(38, tangent)));
        // Legs kick out at take-off, fold back in flight.
        const kick = k < 0.3 ? k / 0.3 : 1 - (k - 0.3) / 0.7;
        setLegs(-14 * kick, -62 * kick);
        if (s >= 1) {
          perch = to;
          state = "settle";
          s = 0;
        }
      } else {
        s += dt / 0.24;
        const k = Math.min(1, s);
        const p = perchPoint(perch);
        pos = { x: p.x, y: p.y };
        render(pos.x, pos.y, 0, 1 - Math.sin(k * Math.PI) * 0.08);
        setLegs(Math.sin(k * Math.PI) * 6, 0);
        if (s >= 1) {
          state = "perch";
          timer = rand(6, 12);
        }
      }
    };

    render(pos.x, pos.y);
    el.style.opacity = "1";
    return subscribe(step);
  }, []);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-[5] overflow-hidden">
      <div ref={wrap} className="absolute top-0 left-0 h-[26px] w-[42px] opacity-0 transition-opacity duration-1000 will-change-transform md:h-[36px] md:w-[58px]">
        <Hopper femur={femur} tibia={tibia} antenna={antenna} />
      </div>
    </div>
  );
}
