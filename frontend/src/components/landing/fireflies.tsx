"use client";

import { useEffect, useRef } from "react";

import { prefersReducedMotion, subscribe } from "@/components/ambient/ticker";

import { getField, onField, rand } from "./meadow-field";

/*
 * Fireflies over the grass, in the dark theme only (in the light theme they are not rendered and cost nothing). Each is
 * a small beetle with a lantern at the tip of its abdomen; it drifts slowly on its own loop above the grass band and
 * signals in its own rhythm: one to three short flashes, then several seconds dark. The glow is an opacity change on a
 * pre-drawn radial gradient, so it composites without repainting. Under reduced motion they glow steadily, still.
 */

const COUNT = 6;

export function Fireflies() {
  const wraps = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const flies = wraps.current.map((el, i) => ({
      el: el!,
      glow: el!.querySelector<HTMLDivElement>("[data-glow]")!,
      lamp: el!.querySelector<SVGPathElement>("[data-lamp]")!,
      i,
      period: rand(4.5, 7.5),
      offset: rand(0, 7),
      flashes: 1 + Math.floor(Math.random() * 3),
      fx: rand(0.05, 0.1),
      fy: rand(0.08, 0.16),
      px: rand(0, Math.PI * 2),
      py: rand(0, Math.PI * 2),
    }));
    const dark = () => document.documentElement.classList.contains("dark");
    const at = (fl: (typeof flies)[number], t: number) => {
      const f = getField();
      const n = f.phone ? 3 : COUNT;
      // Desktop: half in each page margin. One column: spread along the band above the grass.
      const box = Math.min(f.w, 1240);
      const margin = (f.w - box) / 2;
      const split = f.wide && margin > 60;
      const half = Math.ceil(n / 2);
      const lane = split ? (margin - 16) / half : f.w / n;
      const left = split ? (fl.i < half ? 8 : f.w - margin + 8) + lane * ((fl.i % half) + 0.5) : lane * (fl.i + 0.5);
      return {
        x: left + Math.sin(t * Math.PI * 2 * fl.fx + fl.px) * lane * (split ? 0.6 : 0.42),
        y: f.h - (90 + 60 * Math.sin(t * Math.PI * 2 * fl.fy + fl.py)) * f.s,
        on: fl.i < n,
      };
    };
    const show = (fl: (typeof flies)[number], x: number, y: number, light: number) => {
      fl.el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -50%)`;
      fl.glow.style.opacity = light.toFixed(3);
      fl.lamp.setAttribute("opacity", (0.25 + 0.75 * light).toFixed(2));
    };

    if (prefersReducedMotion()) {
      return onField(() => {
        flies.forEach((fl) => {
          const p = at(fl, 0);
          fl.el.style.display = p.on ? "" : "none";
          show(fl, p.x, p.y, 0.55);
        });
      });
    }

    return subscribe((_, now) => {
      if (!dark()) return;
      const t = now / 1000;
      for (const fl of flies) {
        const p = at(fl, t);
        if (!p.on) {
          fl.el.style.display = "none";
          continue;
        }
        fl.el.style.display = "";
        // One to three 0.32 s flashes, half a second apart, at the start of each period; dark the rest of the time.
        const tau = (t + fl.offset) % fl.period;
        let light = 0;
        for (let k = 0; k < fl.flashes; k++) {
          const x = tau - k * 0.5;
          if (x > 0 && x < 0.32) light = Math.max(light, Math.sin((x / 0.32) * Math.PI));
        }
        show(fl, p.x, p.y, 0.04 + 0.9 * light);
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
          data-creature="firefly"
          className="absolute top-0 left-0 hidden size-[calc(46px*var(--s))] dark:block"
        >
          <div
            data-glow
            className="absolute inset-0 rounded-full opacity-0 will-change-[opacity]"
            style={{ background: "radial-gradient(circle, var(--firefly) 0 7%, color-mix(in oklab, var(--firefly) 38%, transparent) 22%, transparent 64%)" }}
          />
          <svg viewBox="-6 -4 12 7" className="absolute top-1/2 left-1/2 w-[calc(13px*var(--s))] -translate-x-1/2 -translate-y-1/2 overflow-visible" aria-hidden>
            <path d="M-5 0 C-5 -2.6 -1 -3.6 2.5 -2.8 L3.5 -0.5 C1 0.6 -3 0.8 -5 0 Z" fill="var(--critter-ink)" />
            <circle cx="4" cy="-1.4" r="1.1" fill="var(--critter-ink)" />
            <path d="M3.8 -2.4 L6 -3.6" stroke="var(--critter-ink)" strokeWidth="0.4" />
            <path data-lamp d="M-5.6 0.2 C-5.4 -1.2 -3.6 -1.2 -3 0.4 C-3.6 1.3 -5.2 1.2 -5.6 0.2 Z" fill="var(--firefly)" opacity="0.25" />
          </svg>
        </div>
      ))}
    </>
  );
}
