"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Swatch: a colour you can take. Click (or Enter) copies the hex; the chip lifts on hover and confirms the copy with a
 * check, announced politely. `contrastWith` adds computed WCAG 2.x ratios against other colours (the same formula the
 * API uses), each with its grade as a word.
 *
 *   <Swatch hex="#0E4D58" name="Peacock Teal" role="Primary: pack body" />
 *   <Swatch hex={c} name="Observed colour" contrastWith={[{ hex: "#FFFFFF", name: "white" }]} />
 *
 * Also exported: `contrastRatio(a, b)` and `contrastGrade(ratio)` for any colour pair.
 */
function luminance(hex: string) {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.replace(/./g, (c) => c + c) : h.slice(0, 6);
  const ch = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

export function contrastRatio(a: string, b: string) {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
}

export function contrastGrade(ratio: number) {
  return ratio >= 7 ? "AAA" : ratio >= 4.5 ? "AA" : ratio >= 3 ? "AA large" : "fail";
}

export type SwatchProps = {
  hex: string;
  name: string;
  role?: string | null;
  contrastWith?: { hex: string; name: string }[];
  size?: "md" | "lg";
  className?: string;
};

export function Swatch({ hex, name, role, contrastWith, size = "md", className }: SwatchProps) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(id);
  }, [copied]);
  const value = hex.toUpperCase();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      // Clipboard can be blocked (insecure context, permissions): the hex stays visible to copy by hand.
    }
  };
  const light = luminance(hex) > 0.45;

  return (
    <div className={cn("group/swatch rounded-xl border border-border/70 bg-surface p-2 shadow-clay", className)}>
      <button
        type="button"
        onClick={copy}
        aria-label={`Copy ${name}, ${value}`}
        className={cn(
          "relative flex w-full items-end justify-between overflow-hidden rounded-lg border border-black/10 px-2.5 pb-2 text-left transition-[scale] duration-200 ease-out hover:scale-[1.02] active:scale-[0.98]",
          size === "lg" ? "h-28" : "h-20",
        )}
        style={{ backgroundColor: hex, color: light ? "#1b1d22" : "#ffffff" }}
      >
        <span className="font-mono text-[11.5px] font-medium tracking-wide">{value}</span>
        <span className="inline-flex items-center gap-1 text-[11.5px] font-medium opacity-0 transition-opacity duration-150 group-hover/swatch:opacity-100 group-focus-within/swatch:opacity-100">
          {copied ? <Check aria-hidden className="size-3.5" /> : <Copy aria-hidden className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </span>
      </button>
      <span aria-live="polite" className="sr-only">
        {copied ? `${value} copied` : ""}
      </span>
      <div className="px-1 pt-2 pb-0.5">
        <p className="text-[13.5px] font-medium text-ink">{name}</p>
        {role && <p className="mt-0.5 text-[12px] leading-snug text-ink-secondary">{role}</p>}
        {contrastWith && contrastWith.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {contrastWith.map((c) => {
              const r = contrastRatio(hex, c.hex);
              return (
                <li key={c.hex} className="type-ledger flex items-center gap-1.5 text-[11.5px] text-ink-secondary">
                  <span aria-hidden className="size-2.5 rounded-full border border-border" style={{ backgroundColor: c.hex }} />
                  on {c.name} <span className="tabular-nums text-ink">{r.toFixed(2)}:1</span> {contrastGrade(r)}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
