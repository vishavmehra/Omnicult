"use client";

import { useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { Ants } from "./ants";
import { Bee } from "./bee";
import { Beetle } from "./beetle";
import { Butterflies } from "./butterflies";
import { Dragonfly } from "./dragonfly";
import { Fireflies } from "./fireflies";
import { Grasshopper } from "./grasshopper";
import { Moth } from "./moth";
import { Tufts } from "./tufts";

/*
 * The landing's meadow: the creatures and the foreground tufts they perch on, on one fixed layer portalled straight
 * into <body>. Being outside the page tree, no ancestor transform, filter or smooth-scroll wrapper can ever turn
 * `position: fixed` into "moves with the content", and nothing here listens to scroll: every position is computed in
 * viewport coordinates by meadow-field (resize only). One shared 30 fps ticker drives them all, paused in hidden tabs;
 * transforms and opacity only, no layout reads per frame. Under prefers-reduced-motion each creature is drawn once,
 * at rest, in place. pointer-events: none throughout; aria-hidden, since it is ornament.
 *
 * Paint order is depth: fireflies low in the grass, then the tufts, the ground walkers, and the flyers on top.
 * Landing only (DESIGN.md: the landing ornaments never come into the app).
 */

const noop = () => () => {};

export function Meadow() {
  const mounted = useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
  if (!mounted) return null;
  return createPortal(
    <div aria-hidden className="pointer-events-none fixed inset-0 z-[5] overflow-hidden [--s:0.6] sm:[--s:0.8] lg:[--s:1]">
      <Fireflies />
      <Tufts />
      <Beetle />
      <Ants />
      <Grasshopper />
      <Moth />
      <Dragonfly />
      <Bee />
      <Butterflies />
    </div>,
    document.body,
  );
}
