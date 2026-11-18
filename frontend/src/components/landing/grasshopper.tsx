"use client";

import { useEffect, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { getField, onField, rand, type Field } from "./meadow-field";
import { crackle, panAt, stridulate } from "./meadow-sound";

/*
 * A grasshopper on the bottom edge, side view: short antennae, a big compound eye, the saddle-shaped pronotum, leathery
 * forewings along the back, a segmented abdomen, and the long hind leg folded at the knee (a striped drumstick femur, a
 * spined tibia). It sits still with small antenna twitches and now and then rubs a hind leg against its wing; every 8 to
 * 16 seconds it crouches, kicks the hind legs straight and leaps on a parabola to another spot on the ground, flashing
 * amber hindwings on the longer jumps. Its spots are fractions of the viewport width on the ground line, so nothing it
 * does depends on the page.
 */

function HopperArt({
  femur,
  tibia,
  antenna,
  fan,
}: {
  femur: React.Ref<SVGGElement>;
  tibia: React.Ref<SVGGElement>;
  antenna: React.Ref<SVGGElement>;
  fan: React.Ref<SVGGElement>;
}) {
  return (
    <svg viewBox="-4 -24 108 60" className="block size-full overflow-visible" aria-hidden>
      {/* far antenna and far legs, in shade */}
      <path d="M85 0 C87 -8 91 -15 96.5 -21" stroke="var(--hopper-shade)" strokeWidth="1" fill="none" strokeLinecap="round" />
      <path d="M64 20 L68.5 26 L69.4 34 L72.6 34.4 M76 20 L79.2 27 L80.6 34 L83.4 34.3" stroke="var(--hopper-shade)" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* hindwing fan, folded away until a long leap */}
      <g ref={fan} opacity="0" transform="scale(1 0.2)">
        <path d="M56 7 C46 -12 26 -19 10 -13 C16 -6 26 1 40 6 Z" fill="var(--hopper-glow)" />
        <path d="M51 -3 C43 -10.5 29 -14.5 16 -11.5" stroke="var(--hopper-shade)" strokeWidth="2.6" fill="none" opacity="0.75" />
        <path d="M56 7 L17 -11 M56 7 L29 -15.5 M56 7 L42 -12" stroke="var(--hopper-shade)" strokeWidth="0.6" opacity="0.6" />
      </g>
      {/* abdomen, segmented */}
      <path d="M8 21 C10 15.5 25 13.5 46 14.5 L47 25.5 C35 28.5 19 28.5 11 25.5 C8 24.5 7 22.5 8 21 Z" fill="var(--hopper-body)" />
      {[15, 20, 25, 30, 35, 40].map((x) => (
        <path key={x} d={`M${x} ${15.6 - (x - 15) * 0.04} L${x - 0.6} 27.4`} stroke="var(--hopper-shade)" strokeWidth="0.7" />
      ))}
      {/* forewings (tegmina) along the back, veined and spotted */}
      <path d="M62 5.5 C47 3.5 27 5.5 5 12.5 C3.6 13.6 4.2 16 6.4 16 C25 13.5 45 12.2 62 12.6 Z" fill="var(--hopper-wing)" stroke="var(--hopper-shade)" strokeWidth="0.5" />
      <path d="M60 7.2 C45 6.4 27 8.4 8 13.6 M60 10.2 C46 9.6 30 10.8 12 14.6" stroke="var(--hopper-shade)" strokeWidth="0.45" fill="none" opacity="0.7" />
      {[
        [44, 8.8],
        [34, 9.9],
        [24, 11.4],
        [15, 13.2],
      ].map(([cx, cy]) => (
        <ellipse key={cx} cx={cx} cy={cy} rx="1.7" ry="0.9" fill="var(--hopper-shade)" opacity="0.7" />
      ))}
      {/* pronotum saddle */}
      <path d="M58 3.8 C62 0.6 72 -0.2 76.5 2.6 L77.4 19.4 C72 22 63 22 58 20 Z" fill="var(--hopper-body)" />
      <path d="M59 9 C64 7.4 70.5 7.4 76.5 9" stroke="var(--hopper-wing)" strokeWidth="0.8" fill="none" />
      <path d="M67.5 2 L68 20.6" stroke="var(--hopper-shade)" strokeWidth="0.45" />
      {/* near middle and front legs */}
      <path d="M65.5 19.5 L68.8 26 L66.2 34 L62.6 34.4 M77.5 19.8 L81.8 26.4 L83.6 34 L86.8 34.4" stroke="var(--hopper-body)" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* head: tall, with the face slanting back; compound eye; mouthparts */}
      <path d="M76 2.4 C79 -2 87 -2.6 90.2 1.8 C92.8 6 92.8 14 90.2 19 C88 22.6 83 23.6 79.6 21.6 C77 19.6 76 15 76 10 Z" fill="var(--hopper-body)" />
      <path d="M79.6 14.4 C83 17.2 87 18 90.4 16" stroke="var(--hopper-shade)" strokeWidth="0.6" fill="none" />
      <ellipse cx="84.6" cy="6.6" rx="3.5" ry="4.6" fill="var(--hopper-shade)" />
      <circle cx="85.7" cy="5" r="1" fill="var(--hopper-rim)" />
      <path d="M88.4 19.4 C90.6 20.4 91.6 22.4 90.6 24.4" stroke="var(--hopper-shade)" strokeWidth="1" fill="none" strokeLinecap="round" />
      <path d="M86.2 21 L86.6 25.6 M88.8 21.6 L90.2 25.2" stroke="var(--hopper-body)" strokeWidth="0.8" strokeLinecap="round" />
      {/* dusk rim light along the top of the head, saddle and wings */}
      <path d="M8 13 C27 6 47 4 58.6 4 C62 1 72 0 76.4 2.6 C79 -1.6 86 -2.6 90 1.6" stroke="var(--hopper-rim)" strokeWidth="0.8" fill="none" strokeLinecap="round" />
      <g ref={antenna}>
        <path d="M86.6 0.6 C90 -8 96 -15 103 -19.5" stroke="var(--hopper-body)" strokeWidth="1.25" fill="none" strokeLinecap="round" />
      </g>
      {/* near hind leg: femur from the hip at (53, 19) up and back to the knee, tibia folded beneath it */}
      <g ref={femur}>
        <path d="M53 13.6 C44 7 33 2 24 0 C21.8 -0.4 21.4 3.4 24.4 4.2 C33 8 43 15 51 24 C55 26 57 17 53 13.6 Z" fill="var(--hopper-body)" stroke="var(--hopper-shade)" strokeWidth="0.5" />
        <path d="M47 9.6 L44.4 15.2 M42 7.2 L39.4 12.6 M37 5.2 L34.6 10 M32 3.4 L29.8 7.6" stroke="var(--hopper-wing)" strokeWidth="0.85" strokeLinecap="round" />
        <path d="M24 0 C21.8 -0.4 21.4 3.4 24.4 4.2 C23.4 3 23.2 1.2 24 0 Z" fill="var(--hopper-shade)" />
        <path d="M51.5 13.4 C44 8 34 3 25 0.6" stroke="var(--hopper-rim)" strokeWidth="0.6" fill="none" strokeLinecap="round" />
        <g ref={tibia}>
          <path d="M23.6 2.6 L49.6 32.6" stroke="var(--hopper-shade)" strokeWidth="2" strokeLinecap="round" />
          <path d="M29.4 9.8 l1.7 -0.9 M33.6 14.6 l1.7 -0.9 M37.8 19.4 l1.7 -0.9 M42 24.2 l1.7 -0.9 M46.2 29 l1.7 -0.9" stroke="var(--hopper-shade)" strokeWidth="0.7" strokeLinecap="round" />
          <path d="M49.6 32.6 L43.4 34.2 L42 33.4" stroke="var(--hopper-shade)" strokeWidth="1.3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      </g>
    </svg>
  );
}

// Fractions of the width along the ground line, clear of the corner tufts.
const spots = (f: Field) => (f.wide ? [0.58, 0.68, 0.78] : [0.42, 0.56, 0.68]);
const spotX = (f: Field, i: number) => {
  const list = spots(f);
  return list[Math.min(i, list.length - 1)] * f.w;
};

export function Grasshopper() {
  const wrap = useRef<HTMLDivElement>(null);
  const femur = useRef<SVGGElement>(null);
  const tibia = useRef<SVGGElement>(null);
  const antenna = useRef<SVGGElement>(null);
  const fan = useRef<SVGGElement>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    let facing = -1; // the drawing faces right; -1 mirrors it to face left
    let spot = 1;
    const groundY = (f: Field) => f.h + 2 * f.s;
    const render = (x: number, y: number, rot = 0, squash = 1) => {
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -100%) scale(${facing}, ${squash.toFixed(3)}) rotate(${rot.toFixed(1)}deg)`;
    };
    const setLegs = (fm: number, tb: number) => {
      femur.current?.setAttribute("transform", `rotate(${fm.toFixed(1)} 53 19)`);
      tibia.current?.setAttribute("transform", `rotate(${tb.toFixed(1)} 23.6 2.2)`);
    };
    const setFan = (k: number) => {
      fan.current?.setAttribute("opacity", k.toFixed(2));
      fan.current?.setAttribute("transform", `translate(0 ${(7 * (1 - k)).toFixed(2)}) scale(1 ${(0.2 + 0.8 * k).toFixed(3)})`);
    };

    if (prefersReducedMotion()) {
      const off = onField((f) => render(spotX(f, spot), groundY(f)));
      el.style.opacity = "1";
      return off;
    }

    let state: "perch" | "crouch" | "leap" | "settle" = "perch";
    let timer = rand(3, 6);
    let twitch = rand(1.2, 3);
    let antennaAngle = 0;
    let antennaTarget = 0;
    let rub = rand(5, 9);
    let rubbing = 0;
    let next = spot;
    let fromX = 0;
    let T = 0.7;
    let s = 0;
    let flash = false;

    const step = (dt: number, now: number) => {
      const f = getField();
      // Antenna twitches.
      twitch -= dt;
      if (twitch < 0) {
        antennaTarget = antennaTarget === 0 ? rand(-10, 6) : 0;
        twitch = antennaTarget === 0 ? rand(1.2, 3.2) : rand(0.18, 0.35);
      }
      antennaAngle += (antennaTarget - antennaAngle) * Math.min(1, dt * 14);
      antenna.current?.setAttribute("transform", `rotate(${antennaAngle.toFixed(1)} 86.6 0.6)`);

      const x0 = spotX(f, spot);
      const y0 = groundY(f);
      if (state === "perch") {
        render(x0, y0);
        // Now and then it rubs a hind leg against its wing (stridulation): a quick small saw of the femur.
        rub -= dt;
        if (rub < 0 && rubbing <= 0) {
          rubbing = rand(0.6, 1);
          rub = rand(9, 18);
          stridulate(panAt(x0, f.w), rubbing);
        }
        if (rubbing > 0) {
          rubbing -= dt;
          setLegs(Math.sin(now / 1000 * Math.PI * 2 * 6) * 3.5 + 2, 0);
        } else setLegs(0, 0);
        timer -= dt;
        if (timer < 0 && rubbing <= 0) {
          const list = spots(f);
          do next = Math.floor(Math.random() * list.length);
          while (next === spot);
          facing = spotX(f, next) >= x0 ? 1 : -1;
          state = "crouch";
          s = 0;
        }
      } else if (state === "crouch") {
        s += dt / 0.24;
        const k = Math.min(1, s);
        render(x0, y0 + k * 1.5 * f.s, 0, 1 - k * 0.06);
        setLegs(k * 6, 0);
        if (s >= 1) {
          state = "leap";
          s = 0;
          fromX = x0;
          const d = Math.abs(spotX(f, next) - fromX);
          T = 0.55 + Math.min(0.6, d / 1400);
          flash = d > 200 * f.s;
          if (flash) crackle(panAt((fromX + spotX(f, next)) / 2, f.w), T * 0.7);
        }
      } else if (state === "leap") {
        s += dt / T;
        const k = Math.min(1, s);
        const toX = spotX(f, next);
        const d = Math.abs(toX - fromX);
        const apex = Math.min(170 * f.s, 46 * f.s + d * 0.3);
        const x = fromX + (toX - fromX) * k;
        const y = y0 - apex * 4 * k * (1 - k);
        const tangent = (Math.atan2(-apex * 4 * (1 - 2 * k), d + 1e-3) * 180) / Math.PI;
        render(x, y, Math.max(-36, Math.min(36, tangent)));
        // Hind legs kick straight at take-off, trail in flight, fold again for landing.
        const kick = k < 0.25 ? k / 0.25 : k < 0.8 ? 1 - (k - 0.25) * 0.4 : (1 - (k - 0.8) / 0.2) * 0.78;
        setLegs(-20 * kick, 82 * kick);
        setFan(flash ? Math.max(0, Math.min(1, Math.sin(Math.min(1, Math.max(0, (k - 0.12) / 0.76)) * Math.PI) * 1.6)) * (0.85 + Math.random() * 0.15) : 0);
        if (s >= 1) {
          spot = next;
          setFan(0);
          state = "settle";
          s = 0;
        }
      } else {
        s += dt / 0.26;
        const k = Math.min(1, s);
        render(x0, y0, 0, 1 - Math.sin(k * Math.PI) * 0.08);
        setLegs(Math.sin(k * Math.PI) * 6, 0);
        if (s >= 1) {
          state = "perch";
          timer = rand(8, 16);
        }
      }
    };

    const f0 = getField();
    render(spotX(f0, spot), groundY(f0));
    el.style.opacity = "1";
    return subscribe(step);
  }, []);

  return (
    <div ref={wrap} data-creature="grasshopper" className="absolute top-0 left-0 aspect-[108/60] w-[calc(104px*var(--s))] opacity-0 transition-opacity duration-1000 will-change-transform">
      <HopperArt femur={femur} tibia={tibia} antenna={antenna} fan={fan} />
    </div>
  );
}
