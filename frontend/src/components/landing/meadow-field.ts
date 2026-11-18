"use client";

/*
 * The meadow's frame of reference. Every creature lives on one fixed layer in viewport coordinates: flight zones,
 * keep-out zones and perches are computed from the viewport size alone (once, then again on resize), never from the
 * scroll position or from any element's bounding box. Scrolling therefore cannot move, push or retarget a creature.
 *
 * Keep-out zones are static rectangles over the places a reader looks first: the header actions, and the statement with
 * its two actions (the left column from 1024 px; the top of the single column below that). Flyers never enter them.
 * Where they linger is chosen from "pockets" that hold no text at any scroll position on the landing: the page margins
 * beside the 1240 px content box and the channel between the statement and the picture (on one-column layouts, the
 * right edge and the band above the grass). They may cross other content in passing, never stop on it. Perches are the
 * foreground tufts drawn in the bottom corners, which are fixed too.
 */

export type Rect = { l: number; t: number; r: number; b: number };
export type Pt = { x: number; y: number };
/** A pocket belongs to the left or the right side of the page, so a creature can keep to its own side. */
export type Pocket = Rect & { side: "l" | "r" };
export type Field = {
  w: number;
  h: number;
  /** Creature scale: 1 from 1024 px, 0.8 from 640 px, 0.6 on phones (matches the layer's --s). */
  s: number;
  phone: boolean;
  wide: boolean;
  /** Static keep-out zones for flyers. */
  keep: Rect[];
  /** Open places flyers favour. */
  pockets: Pocket[];
  /** The left page margin, when it is wide enough to fly in. */
  marginL: Rect | null;
  /** Top of the band above the grass, open to everyone. */
  band: number;
  /** x of the two foreground tufts on the bottom edge. */
  tuftL: number;
  tuftR: number;
};

export const rand = (a: number, b: number) => a + Math.random() * (b - a);
export const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));
export const smooth = (k: number) => k * k * (3 - 2 * k);

function measure(): Field {
  const w = document.documentElement.clientWidth;
  const h = window.innerHeight;
  const phone = !window.matchMedia("(min-width: 40rem)").matches;
  const wide = window.matchMedia("(min-width: 64rem)").matches;
  const s = phone ? 0.6 : wide ? 1 : 0.8;
  // The landing's content box (page.tsx): at most 1240 px, 20 px side padding on phones and 32 px from 640 px.
  const box = Math.min(w, 1240);
  const pad = phone ? 20 : 32;
  const cl = (w - box) / 2 + pad;
  const cr = (w + box) / 2 - pad;
  const band = h - Math.max(64, 100 * s);
  const floor = h - 36 * s;
  let keep: Rect[];
  let pockets: Pocket[];
  let marginL: Rect | null = null;
  if (wide) {
    // Two columns from lg: the statement and its actions take 1.15 of 2.05 parts of the row, less the 56 px gap.
    const colR = cl + ((cr - cl - 56) * 1.15) / 2.05;
    keep = [
      { l: 0, t: 0, r: w, b: 84 },
      { l: cl - 32, t: 0, r: colR, b: band },
    ];
    pockets = [
      // The channel between the statement and the picture, above the height the stage cards can scroll up to.
      { side: "r", l: colR + 6, t: 100, r: colR + 50, b: Math.min(h * 0.62, 400) },
      // The right margin beside the picture and the cards (on narrower desktops, the right edge itself).
      { side: "r", l: Math.min(cr + 14, w - 84), t: 100, r: w - 20, b: floor },
    ];
    if (cl - 32 >= 84) {
      marginL = { l: 14, t: 100, r: cl - 32, b: floor };
      pockets.push({ side: "l", ...marginL });
    }
  } else {
    // One column: the statement, the actions and the picture fill the width, so flyers keep to the right edge and the
    // band above the grass, and never enter the top of the screen where the statement and actions sit.
    keep = [
      { l: 0, t: 0, r: w, b: h * 0.42 },
      { l: 0, t: 0, r: w * 0.72, b: band },
    ];
    pockets = [
      { side: "r", l: w * 0.76, t: h * 0.45, r: w - 14, b: band },
      { side: "r", l: 14, t: band, r: w - 14, b: floor },
    ];
  }
  // Far enough in that a butterfly basking on a corner daisy stays on screen.
  const tuftL = clamp((cl - 32) * 0.5, 92 * s, 150);
  return { w, h, s, phone, wide, keep, pockets, marginL, band, tuftL, tuftR: w - tuftL };
}

let field: Field | null = null;
const listeners = new Set<(f: Field) => void>();
let pending = 0;

function onWindowResize() {
  if (pending) return;
  pending = requestAnimationFrame(() => {
    pending = 0;
    field = measure();
    listeners.forEach((fn) => fn(field!));
  });
}

/** The current field; measured on first use and re-measured on resize only. */
export function getField(): Field {
  if (!field) {
    field = measure();
    window.addEventListener("resize", onWindowResize);
  }
  return field;
}

/** Calls `fn` now and after every resize. Returns the unsubscribe function. */
export function onField(fn: (f: Field) => void) {
  fn(getField());
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function inside(p: Pt, r: Rect, m = 0) {
  return p.x > r.l - m && p.x < r.r + m && p.y > r.t - m && p.y < r.b + m;
}

export function blocked(p: Pt, f: Field, m = 0) {
  return f.keep.some((k) => inside(p, k, m));
}

/** Unit push out of the keep-out zones, through the nearest edge that leads back on screen; zero when clear. */
export function repel(p: Pt, f: Field, m: number): Pt {
  let x = 0;
  let y = 0;
  for (const k of f.keep) {
    if (!inside(p, k, m)) continue;
    let best = Infinity;
    let ex = 0;
    let ey = 0;
    const consider = (d: number, dx: number, dy: number, ok: boolean) => {
      if (ok && d < best) {
        best = d;
        ex = dx;
        ey = dy;
      }
    };
    consider(p.x - (k.l - m), -1, 0, k.l - m > 8);
    consider(k.r + m - p.x, 1, 0, k.r + m < f.w - 8);
    consider(p.y - (k.t - m), 0, -1, k.t - m > 8);
    consider(k.b + m - p.y, 0, 1, k.b + m < f.h - 8);
    x += ex;
    y += ey;
  }
  return { x, y };
}

/** True when the straight path from a to b crosses a keep-out zone. */
export function crosses(a: Pt, b: Pt, f: Field, m = 0) {
  for (let i = 1; i <= 12; i++) {
    const k = i / 12;
    if (blocked({ x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k }, f, m)) return true;
  }
  return false;
}

/** The next point to steer for on the way from a to b: b itself, or a detour through the open band above the grass. */
export function route(a: Pt, b: Pt, f: Field, m = 0): Pt {
  if (!crosses(a, b, f, m)) return b;
  const lane = (f.band + f.h) / 2 - 10 * f.s;
  const down = { x: a.x, y: lane };
  if (Math.abs(a.y - lane) > 24 && !crosses(a, down, f, m)) return down;
  const under = { x: b.x, y: lane };
  if (!crosses(a, under, f, m)) return under;
  return b;
}

/** Where every flyer is right now, so they keep a little apart. */
export const airspace = new Set<Pt>();

export function crowded(p: Pt, me: Pt | null, d: number) {
  for (const o of airspace) if (o !== me && Math.hypot(o.x - p.x, o.y - p.y) < d) return true;
  return false;
}

/**
 * A random point in one of the pockets on the given sides ("l", "r" or "lr"), clear of every keep-out zone by m and,
 * when `me` is given, preferably of the other flyers.
 */
export function pickPoint(f: Field, m = 0, sides = "lr", me: Pt | null = null): Pt {
  const own = f.pockets.filter((p) => sides.includes(p.side));
  const list = own.length ? own : f.pockets;
  for (let i = 0; i < 24; i++) {
    const r = list[Math.floor(Math.random() * list.length)];
    const p = { x: rand(r.l, Math.max(r.l, r.r)), y: rand(r.t, Math.max(r.t, r.b)) };
    if (!blocked(p, f, m) && (i > 16 || !me || !crowded(p, me, 150 * f.s))) return p;
  }
  return { x: f.w - 70 * f.s, y: (f.band + f.h) / 2 };
}

/*
 * Foreground plants. Two tufts stand on the bottom edge, one in each corner, drawn in a 120 x 170 box (ground at
 * y = 170) whose bottom centre sits at (tuftL or tuftR, h). Perches are the heads of these plants; they sway in a slow
 * breeze, so their position is a function of time and of the field, never of the page.
 */
export const TUFT_W = 120;
export const TUFT_H = 170;
export type Plant = { side: "L" | "R"; kind: "daisy" | "seed" | "reed"; base: number; hx: number; hy: number; phase: number };

// Placed so resting creatures do not overlap: the pink butterfly's daisy, the moth's seed stalk and the ladybird's blades
// on the left; the dragonfly's tall reed above the ember butterfly's daisy, and the bee's second daisy, on the right.
export const PLANTS = {
  daisyL: { side: "L", kind: "daisy", base: 30, hx: 22, hy: 92, phase: 0.6 },
  seedL: { side: "L", kind: "seed", base: 70, hx: 64, hy: 12, phase: 2.1 },
  daisyR1: { side: "R", kind: "daisy", base: 92, hx: 96, hy: 112, phase: 1.3 },
  daisyR2: { side: "R", kind: "daisy", base: 40, hx: 28, hy: 96, phase: 4.0 },
  reedR: { side: "R", kind: "reed", base: 70, hx: 66, hy: 2, phase: 2.9 },
} satisfies Record<string, Plant>;

/** Breeze angle (radians) for a plant at viewport x; a gust travels left to right like the grass behind it. */
export function sway(phase: number, x: number, t: number) {
  return 0.045 * Math.sin(0.9 * t + phase) + 0.07 * (0.5 + 0.5 * Math.sin(0.35 * t - x * 0.004)) - 0.035;
}

/** A plant's head in viewport pixels, and the creature rotation (degrees, head up along the stem). */
export function perchAt(p: Plant, f: Field, t: number, still: boolean) {
  const tx = p.side === "L" ? f.tuftL : f.tuftR;
  const a = still ? 0 : sway(p.phase, tx, t);
  const dx = p.hx - p.base;
  const dy = p.hy - TUFT_H;
  const rx = dx * Math.cos(a) - dy * Math.sin(a);
  const ry = dx * Math.sin(a) + dy * Math.cos(a);
  return { x: tx + (p.base - TUFT_W / 2 + rx) * f.s, y: f.h + ry * f.s, deg: ((a + Math.atan2(dx, -dy)) * 180) / Math.PI };
}

/** Plants already taken by a resting creature, so two never share a flower. */
export const taken = new Set<Plant>();
