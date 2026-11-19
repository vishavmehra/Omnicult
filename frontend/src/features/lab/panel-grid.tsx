"use client";

import { MessageCircleQuestion } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ChipToggleGroup, PersonaAvatar, ReactionBubble, type ChipOption, type Mood } from "@/components/creative";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { REACTIONS } from "./labels";

/** One synthetic participant on the panel grid: what the API saved for them, nothing else. */
export type PanelFace = {
  id: string;
  ordinal: number;
  persona: string;
  lang?: string;
  /** The saved reaction, or null when none was saved. */
  mood: Mood | null;
  /** The participant's own words (a first reaction or an interview answer), or null when none was saved. */
  quote: string | null;
  footer?: ReactNode;
};

const HINT = "Hover or focus a face to read what that participant said. Select it to keep it open.";

/**
 * The synthetic panel as a grid of drawn faces (an illustration, never a photograph: these are not real people). The
 * expression comes from each participant's saved reaction. Hover or focus previews their quote; a click pins it. The chips
 * dim the faces that do not match a reaction, with counts taken from this panel.
 */
export function PanelGrid({ faces, onAsk, ariaLabel }: { faces: PanelFace[]; onAsk(id: string): void; ariaLabel: string }) {
  const [filter, setFilter] = useState("all");
  const [hover, setHover] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const active = faces.find((f) => f.id === (hover ?? pinned)) ?? null;

  const counts = new Map<string, number>();
  for (const f of faces) if (f.mood) counts.set(f.mood, (counts.get(f.mood) ?? 0) + 1);
  const options: ChipOption[] = [
    { value: "all", label: "All", count: faces.length },
    ...REACTIONS.filter((r) => counts.has(String(r.key))).map((r) => ({ value: String(r.key), label: r.label, count: counts.get(String(r.key)) })),
  ];
  const matches = (f: PanelFace) => filter === "all" || f.mood === filter;

  return (
    <div className="space-y-3">
      {options.length > 2 && <ChipToggleGroup ariaLabel="Highlight participants by reaction" size="sm" value={filter} onChange={setFilter} options={options} />}
      <ul aria-label={ariaLabel} className="flex flex-wrap gap-1.5" onPointerLeave={() => setHover(null)}>
        {faces.map((f) => {
          const on = pinned === f.id;
          return (
            <li key={f.id}>
              <button
                type="button"
                aria-pressed={on}
                aria-label={`Participant ${f.ordinal + 1}, ${f.mood ?? "no reaction saved"}`}
                onPointerEnter={() => setHover(f.id)}
                onFocus={() => setHover(f.id)}
                onBlur={() => setHover(null)}
                onClick={() => setPinned(on ? null : f.id)}
                className={cn(
                  "grid size-11 place-items-center rounded-full transition-[transform,opacity] duration-200 ease-out hover:-translate-y-0.5 hover:scale-110 focus-visible:scale-110",
                  on && "ring-2 ring-pop ring-offset-2 ring-offset-surface",
                  (!matches(f) || !f.mood) && "opacity-35 hover:opacity-100 focus-visible:opacity-100",
                )}
              >
                <PersonaAvatar seed={f.id} mood={f.mood ?? "neutral"} size={40} />
              </button>
            </li>
          );
        })}
      </ul>
      <div aria-live="polite" className="min-h-[6.5rem]">
        {active ? (
          <div className="space-y-2">
            {active.quote && active.mood ? (
              <ReactionBubble
                quote={active.quote}
                lang={active.lang}
                mood={active.mood}
                persona={{ seed: active.id, caption: `Participant ${active.ordinal + 1} · ${active.persona}` }}
                footer={active.footer}
              />
            ) : (
              <p className="text-[13px] text-ink-muted">Participant {active.ordinal + 1} has no saved response, so there is no quote to show.</p>
            )}
            {active.quote && (
              <Button size="sm" variant="outline" onClick={() => onAsk(active.id)}>
                <MessageCircleQuestion aria-hidden />
                Ask this participant
              </Button>
            )}
          </div>
        ) : (
          <p className="text-[13px] text-ink-secondary">{HINT}</p>
        )}
      </div>
    </div>
  );
}
