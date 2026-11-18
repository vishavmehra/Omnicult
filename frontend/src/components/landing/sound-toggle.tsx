"use client";

import { Volume2, VolumeX } from "lucide-react";
import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

import { setSound, soundOn, subscribeSound } from "./meadow-sound";

/** Turns the meadow's sounds on and off (they start only after a first click or key press). The choice is remembered. */
export function SoundToggle({ className }: { className?: string }) {
  const on = useSyncExternalStore(subscribeSound, soundOn, () => true);
  return (
    <button
      type="button"
      data-sound-toggle
      onClick={() => setSound(!on)}
      aria-pressed={on}
      aria-label="Meadow sounds"
      title={on ? "Meadow sounds on" : "Meadow sounds off"}
      className={cn("inline-flex size-9 items-center justify-center rounded-lg text-ink-secondary transition-colors hover:bg-surface-muted hover:text-ink", className)}
    >
      {on ? <Volume2 aria-hidden className="size-[18px]" /> : <VolumeX aria-hidden className="size-[18px]" />}
    </button>
  );
}
