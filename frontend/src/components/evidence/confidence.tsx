"use client";

import { Sigma } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { CONFIDENCE, type ConfidenceLevel } from "./confidence-rules";

export { CONFIDENCE, type ConfidenceLevel };

/**
 * Confidence as a four-cell inset track plus the word. Shape and text carry the level, colour only reinforces it.
 * Never a percentage: there is no calibrated probability behind these levels.
 */
export function ConfidenceIndicator({ level, className, showRule = true }: { level: ConfidenceLevel; className?: string; showRule?: boolean }) {
  const { label, filled, rule } = CONFIDENCE[level];
  const deterministic = level === "deterministic";
  const body = (
    <>
      <span aria-hidden className="clay-well inline-flex gap-[3px] rounded-[4px] p-[3px]">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={cn(
              "h-2.5 w-[7px] rounded-[2px]",
              i < filled ? (level === "low" ? "bg-ink-muted" : level === "moderate" ? "bg-ink-secondary" : "bg-ink") : "bg-transparent",
              i < filled && "shadow-[inset_0_1px_0_rgb(255_255_255/0.25)]",
            )}
          />
        ))}
      </span>
      {deterministic && <Sigma aria-hidden className="size-3.5 text-ink" />}
      <span className="font-medium text-ink">{label}</span>
    </>
  );
  const base = cn("inline-flex items-center gap-1.5 text-[12.5px] leading-none whitespace-nowrap", className);
  if (!showRule) {
    return (
      <span className={base} aria-label={`Confidence: ${label}`}>
        {body}
      </span>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger className={cn(base, "cursor-help rounded-sm")} aria-label={`Confidence: ${label}. ${rule}`}>
        {body}
      </TooltipTrigger>
      <TooltipContent className="max-w-72 flex-col items-start gap-1 text-left">
        <span className="font-medium">Confidence: {label}</span>
        <span>{rule}</span>
        <span className="opacity-80">A rule-based level, not a probability.</span>
      </TooltipContent>
    </Tooltip>
  );
}
