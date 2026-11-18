"use client";

import { useEffect, useLayoutEffect, useRef } from "react";

import { cn } from "@/lib/utils";

import { useReducedMotion } from "./motion";

/**
 * CountUp: a number from the API that counts up (expo ease-out) the first time it scrolls into view, and glides from
 * the old value when it changes. The server render and screen readers always get the final value; only the visible
 * digits animate. Reduced motion shows the final value at once.
 *
 *   <CountUp value={card.readiness.filter((r) => r.verdict === "go").length} />
 *   <CountUp value={spend} format={(n) => formatMoney("INR", n)} />
 *
 * Use for counts and totals the API returned. Never for a number you computed to look busy, and never for confidence.
 */
const plain = new Intl.NumberFormat("en-IN");

export function CountUp({ value, format, duration = 900, className }: { value: number; format?: (n: number) => string; duration?: number; className?: string }) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef<number | null>(null);
  const fmt = useRef(format);
  useEffect(() => {
    fmt.current = format;
  });
  const text = (n: number) => (fmt.current ?? ((v: number) => plain.format(v)))(n);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const integer = Number.isInteger(value);
    if (reduced) {
      el.textContent = text(value);
      shown.current = value;
      return;
    }
    const from = shown.current ?? 0;
    if (from === value) {
      el.textContent = text(value);
      return;
    }
    let raf = 0;
    let start = 0;
    const tick = (now: number) => {
      if (!start) start = now;
      const k = Math.min(1, (now - start) / duration);
      const eased = k === 1 ? 1 : 1 - Math.pow(2, -10 * k);
      const n = from + (value - from) * eased;
      shown.current = n;
      el.textContent = text(integer ? Math.round(n) : n);
      if (k < 1) raf = requestAnimationFrame(tick);
      else shown.current = value;
    };
    const run = () => {
      el.textContent = text(from);
      raf = requestAnimationFrame(tick);
    };
    // On screen now: count at once (before paint, so the final value never flashes). Below the fold: keep showing the
    // true value until it scrolls in, then count; a print, a screenshot or a stalled observer never shows a wrong number.
    const r = el.getBoundingClientRect();
    if (r.bottom > 0 && r.top < window.innerHeight) {
      run();
      return () => cancelAnimationFrame(raf);
    }
    el.textContent = text(value);
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      run();
    });
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
    // `text` reads the latest format through a ref; restarting on every render would replay the count.
  }, [value, reduced, duration]);

  const final = (format ?? ((v: number) => plain.format(v)))(value);
  return (
    <span className={cn("tabular-nums", className)}>
      <span ref={ref} aria-hidden>
        {final}
      </span>
      <span className="sr-only">{final}</span>
    </span>
  );
}
