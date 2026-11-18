import type { CSSProperties, ElementType, HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Reveal and Stagger: first-paint entrances in CSS only (no JS, so a failed script never hides content).
 *
 * - `<Reveal index={2}>`: one element rises 12px and fades in over --dur-4, delayed by index × 45ms.
 * - `<Stagger as="ul">`: each direct child arrives 40ms after the previous one, capped at the 9th.
 *
 * Use on bento tiles and short lists when a view first paints. Do not wrap lists that refresh every few seconds (each
 * refresh would replay). Reduced motion: the global rule removes the movement and the delay.
 */
type Props = { as?: ElementType; className?: string; style?: CSSProperties; children: ReactNode } & Omit<HTMLAttributes<HTMLElement>, "children">;

export function Reveal({ as: Tag = "div", index = 0, className, style, children, ...rest }: Props & { index?: number }) {
  return (
    <Tag className={cn("reveal", className)} style={{ ...style, "--i": Math.min(index, 12) } as CSSProperties} {...rest}>
      {children}
    </Tag>
  );
}

export function Stagger({ as: Tag = "div", className, children, ...rest }: Props) {
  return (
    <Tag className={cn("stagger", className)} {...rest}>
      {children}
    </Tag>
  );
}
