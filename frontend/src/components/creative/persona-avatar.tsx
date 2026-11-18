import { CircleHelp, Frown, Meh, Scale, Smile, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * PersonaAvatar and ReactionBubble: synthetic respondents drawn, never photographed.
 *
 * PersonaAvatar is a deterministic clay face from a seed (the respondent id): the same seed always draws the same face
 * (background role colour, skin tone, hair, glasses or earrings). `mood` sets the expression from the respondent's
 * reaction. It is an illustration of a synthetic participant, so it never implies a real person.
 *
 * ReactionBubble is one synthetic quote in a speech bubble with its mood as icon plus word, the persona caption and the
 * quote's `lang`. Clickable when `onSelect` is given (pin it, open the respondent).
 *
 *   <PersonaAvatar seed={r.id} mood="positive" size={44} />
 *   <ReactionBubble quote={r.quote} lang="ta" mood="confused" persona={{ seed: r.id, caption: "Synthetic, 25-34, Chennai" }} />
 */
export type Mood = "positive" | "mixed" | "neutral" | "negative" | "confused";

function hash(seed: string) {
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

const BACK = ["desk", "lens", "studio", "lab", "launch", "pulse", "proof"];
const SKIN = ["#f1c9a5", "#e3ae85", "#d49a6a", "#c68642", "#a86b3c", "#8d5524"];
const HAIR = ["#1f1a17", "#2b201b", "#3a2a20", "#4a3426", "#6b6e75"];

export function PersonaAvatar({ seed, mood = "neutral", size = 40, label, className }: { seed: string; mood?: Mood; size?: number; label?: string; className?: string }) {
  const h = hash(seed);
  const pick = <T,>(list: T[], shift: number) => list[(h >>> shift) % list.length];
  const back = pick(BACK, 0);
  const skin = pick(SKIN, 3);
  const hair = pick(HAIR, 7);
  const style = (h >>> 11) % 5;
  const extra = (h >>> 15) % 6; // 0 glasses, 1 earrings, else nothing
  const mouth = {
    positive: "M25 41 Q32 47 39 41",
    mixed: "M26 43 Q32 43 38 40",
    neutral: "M27 42 L37 42",
    negative: "M26 44 Q32 39 38 44",
    confused: "M26 43 Q29 40 32 43 T38 42",
  }[mood];
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("shrink-0 rounded-full shadow-clay", className)}
    >
      <circle cx="32" cy="32" r="32" fill={`var(--role-${back})`} />
      <path d="M10 64 C12 50 22 46 32 46 C42 46 52 50 54 64 Z" fill={`var(--role-${pick(BACK, 19)}-strong)`} opacity={0.85} />
      {style === 2 && <path d="M17 30 C17 14 47 14 47 30 L48 50 C42 52 22 52 16 50 Z" fill={hair} />}
      <rect x="28" y="38" width="8" height="10" rx="3" fill={skin} />
      <ellipse cx="32" cy="31" rx="13" ry="14" fill={skin} />
      {style === 0 && <path d="M19 28 C19 15 45 15 45 28 C42 22 36 20 32 20 C27 20 22 22 19 28 Z" fill={hair} />}
      {style === 1 && <path d="M19 30 C18 16 44 13 45 27 C39 21 30 19 25 24 C23 26 21 28 19 30 Z" fill={hair} />}
      {style === 2 && <path d="M19 29 C20 17 44 17 45 29 C40 22 24 22 19 29 Z" fill={hair} />}
      {style === 3 && (
        <>
          <circle cx="32" cy="14" r="6" fill={hair} />
          <path d="M19 28 C19 16 45 16 45 28 C40 21 24 21 19 28 Z" fill={hair} />
        </>
      )}
      {style === 4 && (
        <g fill={hair}>
          <circle cx="22" cy="22" r="5" />
          <circle cx="28" cy="18" r="5.5" />
          <circle cx="35" cy="18" r="5.5" />
          <circle cx="42" cy="22" r="5" />
          <circle cx="45" cy="28" r="3.5" />
          <circle cx="19" cy="28" r="3.5" />
        </g>
      )}
      <circle cx="26.5" cy="32" r="1.7" fill="#2a2230" />
      <circle cx="37.5" cy="32" r="1.7" fill="#2a2230" />
      {mood === "confused" && <path d="M34.5 27.5 L40 26" stroke="#2a2230" strokeWidth="1.4" strokeLinecap="round" />}
      <circle cx="23.5" cy="37" r="2.6" fill="#f08aa8" opacity={0.35} />
      <circle cx="40.5" cy="37" r="2.6" fill="#f08aa8" opacity={0.35} />
      <path d={mouth} fill="none" stroke="#2a2230" strokeWidth="1.8" strokeLinecap="round" />
      {extra === 0 && (
        <g fill="none" stroke="#2a2230" strokeWidth="1.2" opacity={0.8}>
          <circle cx="26.5" cy="32" r="4.2" />
          <circle cx="37.5" cy="32" r="4.2" />
          <path d="M30.7 32 L33.3 32" />
        </g>
      )}
      {extra === 1 && (
        <g fill="var(--role-launch-strong)">
          <circle cx="19.3" cy="36" r="1.5" />
          <circle cx="44.7" cy="36" r="1.5" />
        </g>
      )}
    </svg>
  );
}

const MOOD: Record<Mood, { label: string; Icon: LucideIcon; className: string }> = {
  positive: { label: "Positive", Icon: Smile, className: "text-success" },
  mixed: { label: "Mixed", Icon: Scale, className: "text-ink-secondary" },
  neutral: { label: "Neutral", Icon: Meh, className: "text-ink-secondary" },
  negative: { label: "Negative", Icon: Frown, className: "text-danger" },
  confused: { label: "Confused", Icon: CircleHelp, className: "text-warning" },
};

export function ReactionBubble({
  quote,
  lang,
  mood,
  persona,
  side = "left",
  selected,
  onSelect,
  footer,
  className,
}: {
  quote: string;
  lang?: string;
  mood: Mood;
  persona?: { seed: string; caption: string };
  side?: "left" | "right";
  selected?: boolean;
  onSelect?: () => void;
  footer?: ReactNode;
  className?: string;
}) {
  const m = MOOD[mood];
  const bubble = (
    <span
      className={cn(
        "relative block rounded-2xl bg-surface-raised px-3.5 py-2.5 text-left shadow-clay transition-[translate,box-shadow] duration-200 ease-out",
        side === "left" ? "rounded-bl-md" : "rounded-br-md",
        onSelect && "group-hover/bubble:-translate-y-0.5 group-hover/bubble:shadow-float",
        selected && "ring-2 ring-pop",
      )}
    >
      <span lang={lang} className="block text-[14px] leading-relaxed text-ink">
        {quote}
      </span>
      <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px]">
        <span className={cn("inline-flex items-center gap-1 font-medium", m.className)}>
          <m.Icon aria-hidden className="size-3.5" />
          {m.label}
        </span>
        {persona && <span className="text-ink-muted">{persona.caption}</span>}
        {footer}
      </span>
    </span>
  );
  return (
    <div className={cn("flex items-end gap-2.5", side === "right" && "flex-row-reverse", className)}>
      {persona && <PersonaAvatar seed={persona.seed} mood={mood} size={36} />}
      {onSelect ? (
        <button type="button" aria-pressed={selected} onClick={onSelect} className="group/bubble min-w-0 flex-1 rounded-2xl text-left">
          {bubble}
        </button>
      ) : (
        <div className="min-w-0 flex-1">{bubble}</div>
      )}
    </div>
  );
}
