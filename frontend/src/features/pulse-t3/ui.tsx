"use client";

import { useId, type ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { PULSE_THEME } from "@/features/pulse/ui";
import { cn } from "@/lib/utils";

/** The page of one Tier 3 tab: the Pulse chart colours are defined on the dashboard root, so each tab carries them too. */
export function PulseTabPage({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("space-y-8", PULSE_THEME, className)}>{children}</div>;
}

/** The one quiet source line of a view. */
export function SourceLine({ children = "Source: sample dataset." }: { children?: ReactNode }) {
  return <p className="type-meta max-w-[78ch]">{children}</p>;
}

/** A labelled number input with its unit after it and its error under it, as in the alert preview. */
export function NumberField({
  label,
  suffix,
  value,
  error,
  onChange,
  step,
}: {
  label: string;
  suffix: string;
  value: string;
  error?: string;
  onChange: (v: string) => void;
  step: string;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-[12.5px] font-medium text-ink">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          className="w-20 text-right tabular-nums md:text-[13px]"
        />
        <span className="text-[12.5px] text-ink-secondary">{suffix}</span>
      </div>
      {error && (
        <p id={`${id}-error`} role="alert" className="max-w-[30ch] text-[12px] font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
