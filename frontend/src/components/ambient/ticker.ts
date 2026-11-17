"use client";

/**
 * One shared animation loop for every ambient element (grass, motes, butterflies, grasshopper). Capped at 30 fps, stopped
 * whenever the tab is hidden or nothing is subscribed. `dt` is in seconds and clamped, so a resumed tab never jumps.
 */
type Subscriber = (dt: number, now: number) => void;

const subscribers = new Set<Subscriber>();
const FRAME_MS = 1000 / 30;
let raf = 0;
let last = 0;
let listening = false;

function frame(now: number) {
  raf = requestAnimationFrame(frame);
  if (last && now - last < FRAME_MS - 1) return;
  const dt = last ? Math.min(0.1, (now - last) / 1000) : 1 / 30;
  last = now;
  subscribers.forEach((fn) => fn(dt, now));
}

function start() {
  if (raf || document.hidden || subscribers.size === 0) return;
  last = 0;
  raf = requestAnimationFrame(frame);
}

function stop() {
  cancelAnimationFrame(raf);
  raf = 0;
}

export function subscribe(fn: Subscriber) {
  if (!listening) {
    listening = true;
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  }
  subscribers.add(fn);
  start();
  return () => {
    subscribers.delete(fn);
    if (subscribers.size === 0) stop();
  };
}

export function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
