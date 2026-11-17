import { CircleCheck, OctagonAlert, Wrench, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type VerdictValue = "go" | "fix" | "rethink";

export const VERDICT: Record<VerdictValue, { label: string; Icon: LucideIcon; meaning: string; className: string }> = {
  go: { label: "Go", Icon: CircleCheck, meaning: "Ready to launch under the current rules.", className: "border-success/70 text-success bg-success-soft" },
  fix: { label: "Fix", Icon: Wrench, meaning: "Launchable after the named fixes.", className: "border-warning/70 text-warning bg-warning-soft" },
  rethink: { label: "Rethink", Icon: OctagonAlert, meaning: "Do not launch this version; revisit the approach.", className: "border-danger/70 text-danger bg-danger-soft" },
};

/**
 * Readiness verdict as a ledger stamp: double rule, icon, word, colour. All three carry the verdict, so it survives
 * greyscale, colour blindness and print.
 */
export function Verdict({ value, size = "sm", className }: { value: VerdictValue; size?: "sm" | "lg"; className?: string }) {
  const { label, Icon, meaning, className: tone } = VERDICT[value];
  return (
    <span
      title={meaning}
      className={cn(
        "inline-flex items-center rounded-stamp border-[3px] border-double font-semibold tracking-[0.08em] uppercase",
        size === "lg" ? "gap-2 px-3 py-1.5 text-[17px]" : "gap-1 px-1.5 py-0.5 text-[11.5px]",
        tone,
        className,
      )}
    >
      <Icon aria-hidden className={size === "lg" ? "size-5" : "size-3.5"} />
      {label}
      <span className="sr-only">: {meaning}</span>
    </span>
  );
}
