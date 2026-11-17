import Link from "next/link";

import { cn } from "@/lib/utils";

/** Seal mark: a stamped ring with seven ticks, one per workspace, around an ember centre (the receipt). */
export function OmnicultMark({ className }: { className?: string }) {
  const ticks = Array.from({ length: 7 }, (_, i) => {
    const a = (i / 7) * Math.PI * 2 - Math.PI / 2;
    return { x1: 14 + Math.cos(a) * 7.2, y1: 14 + Math.sin(a) * 7.2, x2: 14 + Math.cos(a) * 9.6, y2: 14 + Math.sin(a) * 9.6 };
  });
  return (
    <svg aria-hidden viewBox="0 0 28 28" className={cn("size-7 shrink-0", className)} fill="none">
      <circle cx="14" cy="14" r="12.4" stroke="currentColor" strokeWidth="1.6" />
      {ticks.map((t, i) => (
        <line key={i} {...t} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      ))}
      <circle cx="14" cy="14" r="3.1" fill="var(--pop)" />
    </svg>
  );
}

export function Wordmark({ href = "/app", className, size = "md" }: { href?: string; className?: string; size?: "md" | "lg" }) {
  return (
    <Link href={href} className={cn("inline-flex items-center gap-2.5 rounded-md", className)}>
      <OmnicultMark className={size === "lg" ? "size-8" : undefined} />
      <span className={cn("type-title", size === "lg" ? "text-[26px]" : "text-[22px]")}>Omnicult</span>
    </Link>
  );
}
