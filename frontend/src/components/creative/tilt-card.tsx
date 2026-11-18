"use client";

import { useRef, type ElementType, type HTMLAttributes, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { useFinePointer, useReducedMotion } from "./motion";

/**
 * TiltCard: a clay tile that tilts toward the pointer (at most `max` degrees) with a soft glare that follows it.
 * Transform-only, rAF-batched, mouse only (touch and pen keep the card still), off under reduced motion.
 *
 * Use for image tiles, hero tiles, creative thumbnails and campaign cards. Not for forms, tables or long text.
 * The card is a plain container: put a Link or button inside it for the action (a stretched link works well).
 *
 *   <TiltCard className="bento tint-desk"><ApiImage … /><Link href=… className="after:absolute after:inset-0">Open</Link></TiltCard>
 */
export type TiltCardProps = {
  as?: "div" | "article" | "li" | "section";
  /** Largest tilt in degrees. 4 to 6 reads as clay; more reads as a toy. */
  max?: number;
  /** The moving glare highlight. */
  glare?: boolean;
  className?: string;
  children: ReactNode;
} & Omit<HTMLAttributes<HTMLElement>, "children">;

export function TiltCard({ as = "div", max = 5, glare = true, className, children, onPointerEnter, onPointerMove, onPointerLeave, ...rest }: TiltCardProps) {
  const Tag = as as ElementType;
  const ref = useRef<HTMLElement>(null);
  const rect = useRef<DOMRect | null>(null);
  const raf = useRef(0);
  const fine = useFinePointer();
  const reduced = useReducedMotion();
  const enabled = fine && !reduced;

  const enter = (e: ReactPointerEvent<HTMLElement>) => {
    onPointerEnter?.(e);
    if (!enabled || e.pointerType !== "mouse" || !ref.current) return;
    rect.current = ref.current.getBoundingClientRect();
    ref.current.setAttribute("data-tilting", "");
  };

  const move = (e: ReactPointerEvent<HTMLElement>) => {
    onPointerMove?.(e);
    const el = ref.current;
    const r = rect.current;
    if (!enabled || e.pointerType !== "mouse" || !el || !r) return;
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(() => {
      el.style.setProperty("--tilt-x", `${(-py * max * 2).toFixed(2)}deg`);
      el.style.setProperty("--tilt-y", `${(px * max * 2).toFixed(2)}deg`);
      el.style.setProperty("--glare-x", `${(px * r.width).toFixed(1)}px`);
      el.style.setProperty("--glare-y", `${(py * r.height).toFixed(1)}px`);
    });
  };

  const leave = (e: ReactPointerEvent<HTMLElement>) => {
    onPointerLeave?.(e);
    const el = ref.current;
    if (!el) return;
    cancelAnimationFrame(raf.current);
    el.removeAttribute("data-tilting");
    el.style.setProperty("--tilt-x", "0deg");
    el.style.setProperty("--tilt-y", "0deg");
    rect.current = null;
  };

  return (
    <Tag ref={ref} className={cn("tilt relative", className)} onPointerEnter={enter} onPointerMove={move} onPointerLeave={leave} {...rest}>
      {children}
      {glare && enabled && <span aria-hidden className="tilt-glare" />}
    </Tag>
  );
}
