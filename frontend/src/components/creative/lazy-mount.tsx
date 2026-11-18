"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * LazyMount: renders its children only once the placeholder comes within `rootMargin` of the viewport, then keeps
 * them. Use for heavy visuals below the fold (maps, graphs, charts, film strips with many frames); the placeholder holds
 * `minHeight` so the page does not jump.
 *
 *   <LazyMount minHeight={320}><EvidenceMap … /></LazyMount>
 */
export function LazyMount({ children, minHeight, rootMargin = "240px", className }: { children: ReactNode; minHeight: number; rootMargin?: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || shown) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        io.disconnect();
        setShown(true);
      },
      { rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [shown, rootMargin]);
  return (
    <div ref={ref} className={className} style={shown ? undefined : { minHeight }}>
      {shown ? children : <div aria-hidden className="dough h-full rounded-xl" style={{ minHeight }} />}
    </div>
  );
}
