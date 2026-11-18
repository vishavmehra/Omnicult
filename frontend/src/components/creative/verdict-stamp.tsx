import type { CSSProperties } from "react";

import { VERDICT, type VerdictValue } from "@/components/workflow/verdict";
import { cn } from "@/lib/utils";

/**
 * VerdictStamp: Go, Fix or Rethink landing like a rubber stamp (a slight overshoot and an ink ring), then resting at a
 * small tilt. Icon, word and colour all carry the verdict, so it survives greyscale and print. The verdict always comes
 * from the API (readiness rules); this only animates it. Reduced motion: it simply appears.
 *
 *   <VerdictStamp value={r.verdict} delay={i * 120} />
 *
 * `delay` (ms) staggers a row of stamps into one focal moment. Set `animate={false}` in lists that refresh.
 */
export type VerdictStampProps = {
  value: VerdictValue;
  size?: "sm" | "md" | "lg";
  animate?: boolean;
  delay?: number;
  /** Resting tilt in degrees (a stamp is never perfectly straight). */
  tilt?: number;
  className?: string;
};

const SIZE = {
  sm: { box: "gap-1 px-1.5 py-0.5 text-[11.5px]", icon: "size-3.5" },
  md: { box: "gap-1.5 px-2 py-1 text-[13px]", icon: "size-4" },
  lg: { box: "gap-2 px-3 py-1.5 text-[17px]", icon: "size-5" },
};

export function VerdictStamp({ value, size = "md", animate = true, delay = 0, tilt = -3, className }: VerdictStampProps) {
  const { label, Icon, meaning, className: tone } = VERDICT[value];
  const s = SIZE[size];
  const style = { "--stamp-rot": `${tilt}deg`, animationDelay: `${delay}ms`, rotate: animate ? undefined : `${tilt}deg` } as CSSProperties;
  return (
    <span
      title={meaning}
      className={cn(
        "relative inline-flex items-center rounded-stamp border-[3px] border-double font-semibold tracking-[0.08em] whitespace-nowrap uppercase",
        s.box,
        tone,
        animate && "stamp-in",
        className,
      )}
      style={style}
    >
      {animate && <span aria-hidden className="stamp-ring" style={{ animationDelay: `${delay + 160}ms` }} />}
      <Icon aria-hidden className={s.icon} />
      {label}
      <span className="sr-only">: {meaning}</span>
    </span>
  );
}
