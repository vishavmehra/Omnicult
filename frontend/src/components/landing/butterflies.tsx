"use client";

import { useEffect, useId, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { PLANTS, airspace, getField, onField, perchAt, pickPoint, rand, repel, route, taken, type Field, type Plant, type Pt } from "./meadow-field";

/*
 * Two butterflies, drawn from above with real anatomy so they never read as flowers: a pointed forewing over a rounded
 * hindwing, each pane framed by a dark margin with two rows of white spots (the monarch's pattern), dark veins radiating
 * from the body, a fuzzy thorax, a segmented abdomen that runs past the hindwings, and long antennae ending in clubs.
 * One ember, one hot pink (the approved pinch of pink). In the dark theme a dusk rim light traces the wing edges.
 *
 * Behaviour: each keeps to its own side of the page (the ember one to the right margin and the channel beside the
 * statement, the pink one to the left margin when there is one) and wanders there with a steering loop (target,
 * sideways wander, banking turns, an irregular wing beat with glides). It stays out of the static keep-out zones, keeps
 * its distance from every other flyer, and every half minute or so lands on its daisy in a corner tuft to bask, opening
 * and closing its wings slowly before it lifts off again.
 */

// Left wings around the body axis (x = 0), head up. The right pair is the same drawing mirrored.
const FORE = "M-3 -9 C-10 -20 -26 -33 -42 -35 C-49 -35.5 -52 -30 -49.5 -24 C-46 -15 -38 -6 -28 -1.5 C-20 1 -10 0.5 -3 -1.5 Z";
const FORE_PANE = "M-5 -8.5 C-12 -18 -25 -29 -39 -30.5 C-43 -30.5 -44.5 -27 -43 -23.5 C-40 -16 -33 -8.5 -26 -4.5 C-19 -2.2 -11 -2.4 -5 -3.4 Z";
const HIND = "M-3 -1 C-14 -2.5 -29 0 -36.5 7 C-42.5 13 -41 24 -33.5 29.5 C-28 33.5 -20 33.5 -15 30 C-10 26.5 -6.5 20 -4.8 13 C-3.8 8.5 -3.2 3.5 -3 -1 Z";
const HIND_PANE = "M-5 1 C-14 0 -26 2.5 -32.5 8.5 C-37 13 -36 21 -30.5 25.5 C-26.5 28.5 -21 28.5 -17 26 C-12.5 23 -9 17.5 -7 12 C-6 8 -5.3 4.5 -5 1 Z";
const VEINS = [
  "M-5 -6.4 C-15 -15 -27 -25 -38.5 -29.2",
  "M-5 -5.8 C-16 -12 -30 -19 -42.5 -22.5",
  "M-5 -5 C-17 -8.5 -29 -11 -39.5 -13.5",
  "M-6 -4.4 C-17 -5.4 -26 -5.8 -33 -7.6",
  "M-6 -6.2 C-13 -10.6 -19.5 -12.8 -24 -12.2 C-21 -9 -14 -5.6 -6 -4.6",
  "M-5 2 C-15 3.6 -24 6.6 -31.5 11",
  "M-5.5 3 C-15 8 -23 14 -30 21",
  "M-6 4 C-13 11 -19 18 -23 26",
  "M-6.2 5 C-10 12 -13 19 -15.5 25",
  "M-6 3 C-12 4.4 -17 7.4 -19 11 C-14 10 -9.6 7.4 -6 5",
];
// White spots in the dark margins: subapical spots, an outer row on the forewing, a row round the hindwing.
const SPOTS: [number, number, number][] = [
  [-37.2, -32.6, 1.25],
  [-41, -32.8, 1.15],
  [-44.6, -31.4, 1],
  [-47.6, -28.4, 0.85],
  [-47.2, -24.6, 0.85],
  [-45.2, -20, 0.85],
  [-42.2, -15.2, 0.8],
  [-38.6, -10.6, 0.8],
  [-34.6, -6.6, 0.75],
  [-30.4, -3.4, 0.7],
  [-35.6, 9.6, 0.85],
  [-38.2, 15, 0.85],
  [-38, 21, 0.85],
  [-35.2, 26.4, 0.85],
  [-30.6, 30, 0.8],
  [-24.6, 31.4, 0.8],
  [-18.8, 30.2, 0.75],
];

function Wing({ side, pane }: { side: "l" | "r"; pane: string }) {
  return (
    <g data-wing={side} transform={side === "r" ? "scale(-1,1)" : undefined}>
      <path d={HIND} fill="var(--bfly-edge)" stroke="var(--bfly-rim)" strokeWidth="0.8" strokeLinejoin="round" />
      <path d={HIND_PANE} fill={`url(#${pane})`} />
      <path d={FORE} fill="var(--bfly-edge)" stroke="var(--bfly-rim)" strokeWidth="0.8" strokeLinejoin="round" />
      <path d={FORE_PANE} fill={`url(#${pane})`} />
      {VEINS.map((d) => (
        <path key={d} d={d} stroke="var(--bfly-vein)" strokeWidth="0.85" fill="none" strokeLinecap="round" />
      ))}
      {SPOTS.map(([cx, cy, r]) => (
        <circle key={`${cx}${cy}`} cx={cx} cy={cy} r={r} fill="var(--bfly-spot)" />
      ))}
    </g>
  );
}

function ButterflyArt({ id, tone }: { id: string; tone: "ember" | "pink" }) {
  const pane = `bfly-pane-${id}`;
  return (
    <svg viewBox="-53 -41 106 76" className="block size-full overflow-visible" aria-hidden>
      <defs>
        <linearGradient id={pane} x1="-4" y1="0" x2="-44" y2="-18" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor={`var(--bfly-${tone}-in)`} />
          <stop offset="1" stopColor={`var(--bfly-${tone}-out)`} />
        </linearGradient>
      </defs>
      <Wing side="l" pane={pane} />
      <Wing side="r" pane={pane} />
      {/* antennae with clubs */}
      <path d="M-1 -15 C-3 -22 -6 -29 -9.6 -35.6 M1 -15 C3 -22 6 -29 9.6 -35.6" stroke="var(--bfly-body)" strokeWidth="1.15" fill="none" strokeLinecap="round" />
      <ellipse cx="-10.1" cy="-36.6" rx="1.45" ry="2.5" transform="rotate(-28 -10.1 -36.6)" fill="var(--bfly-body)" />
      <ellipse cx="10.1" cy="-36.6" rx="1.45" ry="2.5" transform="rotate(28 10.1 -36.6)" fill="var(--bfly-body)" />
      {/* abdomen, segmented, running past the hindwings */}
      <path d="M-2.6 2 C-3.4 10 -2.9 20 -1.2 29 C-0.6 31.6 0.6 31.6 1.2 29 C2.9 20 3.4 10 2.6 2 Z" fill="var(--bfly-body)" />
      {[8, 13, 18, 23].map((y) => (
        <path key={y} d={`M-2.8 ${y} Q0 ${y + 1.3} 2.8 ${y}`} stroke="var(--bfly-spot)" strokeOpacity="0.35" strokeWidth="0.5" fill="none" />
      ))}
      {/* fuzzy thorax, head and eyes */}
      <ellipse cx="0" cy="-4" rx="3.9" ry="6.4" fill="var(--bfly-body)" />
      <ellipse cx="-1.1" cy="-6" rx="1.2" ry="3.2" fill="var(--bfly-spot)" opacity="0.22" />
      <circle cx="0" cy="-12.6" r="3.1" fill="var(--bfly-body)" />
      <circle cx="-2.1" cy="-13.4" r="1.35" fill="var(--bfly-eye)" />
      <circle cx="2.1" cy="-13.4" r="1.35" fill="var(--bfly-eye)" />
      <circle cx="-1.6" cy="-13.9" r="0.4" fill="var(--bfly-spot)" />
      <circle cx="2.6" cy="-13.9" r="0.4" fill="var(--bfly-spot)" />
    </svg>
  );
}

type Props = {
  tone: "ember" | "pink";
  /** Wingspan in px at desktop scale. */
  span: number;
  /** Daisies this one likes to bask on, in order of preference. */
  flowers: Plant[];
  /** Its side of the page; the pink one falls back to the right when the left margin is too narrow. */
  side: "l" | "r";
  /** Seconds before it flies in from the edge on its side. */
  delay: number;
  /** Height it enters at, as a fraction of the viewport. */
  enterY: number;
  /** Wing beats per second. */
  rate: number;
};

function Butterfly({ tone, span, flowers, side, delay, enterY, rate: baseRate }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const id = useId().replace(/:/g, "");

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const wings = Array.from(el.querySelectorAll<SVGGElement>("[data-wing]"));
    const setWings = (sx: number) => {
      wings[0]?.setAttribute("transform", `scale(${sx.toFixed(3)},1)`);
      wings[1]?.setAttribute("transform", `scale(${(-sx).toFixed(3)},1)`);
    };
    const place = (x: number, y: number, deg: number, roll = 1) => {
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -50%) rotate(${deg.toFixed(1)}deg) scale(${roll.toFixed(3)}, 1)`;
    };

    // Reduced motion: basking on its daisy, wings open, still.
    if (prefersReducedMotion()) {
      const off = onField((f) => {
        const p = perchAt(flowers[0], f, 0, true);
        place(p.x, p.y - 2 * f.s, p.deg);
        setWings(0.94);
        el.style.opacity = "1";
      });
      return off;
    }

    const sides = (f: Field) => (side === "l" && f.marginL ? "l" : "r");
    const f0 = getField();
    // Fly in from the edge on its side: at the given height on desktop, low on one-column layouts (the top is kept clear).
    const me: Pt = {
      x: sides(f0) === "l" ? -90 * f0.s : f0.w + 90 * f0.s,
      y: f0.wide ? f0.h * enterY : rand(f0.h * 0.5, f0.band),
    };
    airspace.add(me);
    const start = performance.now() + delay * 1000;
    let vx = -30;
    let vy = 0;
    let angle = -90;
    let turn = 0;
    let target = pickPoint(f0, span * 0.3 * f0.s, sides(f0), me);
    let retargetAt = 0;
    let mode: "wait" | "fly" | "land" | "bask" = "wait";
    let perch: Plant | null = null;
    let nextLanding = start + rand(14000, 26000);
    let baskUntil = 0;
    let breathAt = 0;
    let phase = rand(0, Math.PI * 2);
    const wanderPhase = rand(0, Math.PI * 2);
    let amp = 1;
    let glideUntil = 0;
    let nextGlide = start + rand(3500, 7000);
    place(me.x, me.y, angle);
    el.style.opacity = "1";

    const step = (dt: number, now: number) => {
      if (mode === "wait") {
        if (now < start) return;
        mode = "fly";
      }
      const f = getField();
      const t = now / 1000;
      const speed = 40 * f.s * (tone === "ember" ? 1 : 0.85);
      const m = span * 0.3 * f.s;

      if (mode === "bask" && perch) {
        const p = perchAt(perch, f, t, false);
        me.x = p.x;
        me.y = p.y - 2 * f.s;
        angle = p.deg;
        // Basking: wings held open, closed slowly now and then.
        if (now > breathAt + 2600) breathAt = now + rand(800, 2600);
        const k = now > breathAt ? Math.min(1, (now - breathAt) / 2600) : 0;
        setWings(0.95 - 0.7 * Math.sin(k * Math.PI));
        place(me.x, me.y, angle);
        if (now > baskUntil) {
          taken.delete(perch);
          perch = null;
          mode = "fly";
          vy = -speed * 1.4;
          vx = rand(-0.6, 0.6) * speed;
          target = pickPoint(f, m, sides(f), me);
          retargetAt = now + rand(6000, 10000);
          nextLanding = now + rand(22000, 40000);
        }
        return;
      }

      if (mode === "fly" && now > nextLanding) {
        const free = flowers.find((p) => !taken.has(p));
        if (free) {
          perch = free;
          taken.add(free);
          mode = "land";
        } else nextLanding = now + rand(8000, 14000);
      }

      const goal = mode === "land" && perch ? perchAt(perch, f, t, false) : target;
      // The last stretch to a daisy is flown straight in: the flower may sit inside a zone's margin on small screens.
      const landing = mode === "land" && Math.hypot(goal.x - me.x, goal.y - me.y) < 90 * f.s;
      const via = landing ? goal : route(me, goal, f, m);
      const dx = via.x - me.x;
      const dy = via.y - me.y;
      const d = Math.hypot(dx, dy) || 1;
      const want = landing ? Math.min(speed, d * 1.5 + 6) : speed;
      const wander = landing ? 0 : Math.sin(now / 1700 + wanderPhase) * 0.55;
      let ax = (dx / d) * want - vx + (-dy / d) * want * wander;
      let ay = (dy / d) * want - vy + (dx / d) * want * wander;
      if (!landing) {
        const push = repel(me, f, m);
        ax += push.x * speed * 3;
        ay += push.y * speed * 3;
      }
      for (const o of airspace) {
        if (o === me || landing) continue;
        const ox = me.x - o.x;
        const oy = me.y - o.y;
        const od = Math.hypot(ox, oy);
        if (od > 0 && od < 130 * f.s) {
          ax += (ox / od) * speed * 1.2;
          ay += (oy / od) * speed * 1.2;
        }
      }
      vx += ax * dt * (landing ? 2.2 : 0.9);
      vy += ay * dt * (landing ? 2.2 : 0.9);
      const v = Math.hypot(vx, vy) || 1;
      const cap = speed * 1.35;
      if (v > cap) {
        vx = (vx / v) * cap;
        vy = (vy / v) * cap;
      }
      // Each wing beat lifts the body a little.
      const lift = landing ? 0 : Math.sin(phase) * 0.6 * 14 * f.s;
      me.x += vx * dt;
      me.y += (vy + lift) * dt;

      if (landing && d < 4 * f.s && perch) {
        mode = "bask";
        baskUntil = now + rand(7000, 13000);
        breathAt = now + 1500;
        return;
      }
      if (mode === "fly" && (now > retargetAt || d < 40 * f.s)) {
        target = pickPoint(f, m, sides(f), me);
        retargetAt = now + rand(6000, 11000);
      }

      // Heading and bank: the body points along travel; turning tilts it further and narrows it (roll). On the final
      // approach to a daisy it turns head-up to match the flower instead.
      const heading = landing && d < 40 * f.s && perch ? perchAt(perch, f, t, false).deg : (Math.atan2(vy, vx) * 180) / Math.PI + 90;
      let delta = heading - angle;
      delta = ((delta + 540) % 360) - 180;
      turn += (delta - turn) * Math.min(1, dt * 3);
      angle += delta * Math.min(1, dt * (landing ? 4 : 2.2));
      const bank = Math.max(-16, Math.min(16, turn * 0.35));
      const roll = 1 - Math.min(0.18, Math.abs(turn) * 0.004);

      // Wing beat: irregular rate, occasional glides, half-open on the final approach.
      if (now > nextGlide && glideUntil < now) {
        glideUntil = now + rand(1200, 2800);
        nextGlide = glideUntil + rand(2500, 6000);
      }
      const ampTarget = landing && d < 60 * f.s ? 0.45 : now < glideUntil ? 0.08 : 1;
      amp += (ampTarget - amp) * Math.min(1, dt * 4);
      phase += dt * Math.PI * 2 * baseRate * (1 + Math.sin(now / 2300 + wanderPhase) * 0.12);
      const beat = Math.pow(0.5 + 0.5 * Math.sin(phase), 1.3);
      setWings(1 - amp * beat * 0.82);
      place(me.x, me.y, angle + bank, roll);
    };
    const off = subscribe(step);
    return () => {
      off();
      airspace.delete(me);
      if (perch) taken.delete(perch);
    };
  }, [tone, span, flowers, side, delay, enterY, baseRate]);

  return (
    <div
      ref={wrap}
      data-creature={`butterfly-${tone}`}
      className="absolute top-0 left-0 aspect-[106/76] opacity-0 transition-opacity duration-700 will-change-transform"
      style={{ width: `calc(${span}px * var(--s))` }}
    >
      <ButterflyArt id={id} tone={tone} />
    </div>
  );
}

const EMBER_FLOWERS = [PLANTS.daisyR1, PLANTS.daisyR2];
const PINK_FLOWERS = [PLANTS.daisyL];

export function Butterflies() {
  return (
    <>
      <Butterfly tone="ember" span={120} flowers={EMBER_FLOWERS} side="r" delay={0.6} enterY={0.3} rate={1.45} />
      <Butterfly tone="pink" span={100} flowers={PINK_FLOWERS} side="l" delay={2.4} enterY={0.55} rate={1.15} />
    </>
  );
}
