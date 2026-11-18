"use client";

import { useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";

import { VERDICT } from "@/components/workflow/verdict";
import { cn } from "@/lib/utils";

/**
 * IndiaTileMap: the 36 states and union territories as equal clay tiles laid out roughly where they sit on the map
 * (the north-east as its own cluster past the Siliguri corridor). Every tile is the same size, so small states read as
 * clearly as large ones.
 *
 * Tiles with data take a tone: a verdict (`go`, `fix`, `rethink`, drawn as the verdict's soft fill plus its icon), a
 * `heat` from 0 to 1 in the role colour (evidence depth, language share), `role` (marked), or `muted`. Hover or focus
 * previews a tile through `renderReadout(code)`; click or Enter selects (`onSelect`, again to clear). Arrow keys move
 * between tiles spatially. `animate` lands the verdict tiles one after another (the focal moment on readiness views).
 *
 *   <IndiaTileMap ariaLabel="Readiness by region" tiles={{ "IN-TN": { tone: "go" }, "IN-KL": { tone: "fix" } }}
 *     selected={region} onSelect={setRegion} renderReadout={(code) => <Readout code={code} />} />
 */
export const INDIA_TILES: Record<string, { x: number; y: number; name: string }> = {
  "IN-JK": { x: 1, y: 0, name: "Jammu and Kashmir" },
  "IN-LA": { x: 2, y: 0, name: "Ladakh" },
  "IN-PB": { x: 0, y: 1, name: "Punjab" },
  "IN-CH": { x: 1, y: 1, name: "Chandigarh" },
  "IN-HP": { x: 2, y: 1, name: "Himachal Pradesh" },
  "IN-UT": { x: 3, y: 1, name: "Uttarakhand" },
  "IN-AR": { x: 7, y: 1, name: "Arunachal Pradesh" },
  "IN-RJ": { x: 0, y: 2, name: "Rajasthan" },
  "IN-HR": { x: 1, y: 2, name: "Haryana" },
  "IN-DL": { x: 2, y: 2, name: "Delhi" },
  "IN-UP": { x: 3, y: 2, name: "Uttar Pradesh" },
  "IN-BR": { x: 4, y: 2, name: "Bihar" },
  "IN-SK": { x: 5, y: 2, name: "Sikkim" },
  "IN-AS": { x: 6, y: 2, name: "Assam" },
  "IN-NL": { x: 7, y: 2, name: "Nagaland" },
  "IN-GJ": { x: 0, y: 3, name: "Gujarat" },
  "IN-MP": { x: 1, y: 3, name: "Madhya Pradesh" },
  "IN-CG": { x: 2, y: 3, name: "Chhattisgarh" },
  "IN-JH": { x: 3, y: 3, name: "Jharkhand" },
  "IN-WB": { x: 4, y: 3, name: "West Bengal" },
  "IN-ML": { x: 6, y: 3, name: "Meghalaya" },
  "IN-MN": { x: 7, y: 3, name: "Manipur" },
  "IN-DH": { x: 0, y: 4, name: "Dadra and Nagar Haveli and Daman and Diu" },
  "IN-MH": { x: 1, y: 4, name: "Maharashtra" },
  "IN-TS": { x: 2, y: 4, name: "Telangana" },
  "IN-OD": { x: 3, y: 4, name: "Odisha" },
  "IN-TR": { x: 6, y: 4, name: "Tripura" },
  "IN-MZ": { x: 7, y: 4, name: "Mizoram" },
  "IN-GA": { x: 0, y: 5, name: "Goa" },
  "IN-KA": { x: 1, y: 5, name: "Karnataka" },
  "IN-AP": { x: 2, y: 5, name: "Andhra Pradesh" },
  "IN-LD": { x: 0, y: 6, name: "Lakshadweep" },
  "IN-KL": { x: 1, y: 6, name: "Kerala" },
  "IN-TN": { x: 2, y: 6, name: "Tamil Nadu" },
  "IN-PY": { x: 3, y: 6, name: "Puducherry" },
  "IN-AN": { x: 6, y: 6, name: "Andaman and Nicobar Islands" },
};
const COLS = 8;
const ROWS = 7;

export type TileTone = "go" | "fix" | "rethink" | "heat" | "role" | "muted";
export type TileDatum = { tone?: TileTone; value?: number; label?: string; mark?: ReactNode };

export type IndiaTileMapProps = {
  tiles: Record<string, TileDatum>;
  ariaLabel: string;
  selected?: string | null;
  onSelect?: (code: string | null) => void;
  renderReadout?: (code: string | null) => ReactNode;
  /** Called as hover or focus moves across tiles (null when it leaves), for a readout drawn elsewhere. */
  onHover?: (code: string | null) => void;
  /** "data": only tiles with data are interactive (default); "all": every state is. */
  interactive?: "data" | "all";
  /** Colour for `role` and `heat` tones; defaults to ember. */
  color?: string;
  animate?: boolean;
  className?: string;
};

const VERDICT_TONE: Record<"go" | "fix" | "rethink", string> = {
  go: "bg-success-soft text-success border-success/45",
  fix: "bg-warning-soft text-warning border-warning/45",
  rethink: "bg-danger-soft text-danger border-danger/45",
};

export function IndiaTileMap({ tiles, ariaLabel, selected = null, onSelect, renderReadout, onHover, interactive = "data", color = "var(--pop)", animate = false, className }: IndiaTileMapProps) {
  const [hover, setHoverCode] = useState<string | null>(null);
  const setHover = (code: string | null) => {
    setHoverCode(code);
    onHover?.(code);
  };
  const refs = useRef<Record<string, HTMLElement | null>>({});
  const codes = Object.keys(INDIA_TILES);
  const live = (code: string) => Boolean(onSelect) && (interactive === "all" || Boolean(tiles[code]));
  const order = codes.filter((c) => tiles[c]?.tone && tiles[c]?.tone !== "muted");

  const move = (e: KeyboardEvent<HTMLElement>, code: string) => {
    const dir = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[e.key];
    if (!dir) {
      if (e.key === "Escape" && selected) onSelect?.(null);
      return;
    }
    e.preventDefault();
    const from = INDIA_TILES[code];
    let best: string | null = null;
    let score = Infinity;
    for (const c of codes) {
      if (c === code || !live(c)) continue;
      const t = INDIA_TILES[c];
      const dx = t.x - from.x;
      const dy = t.y - from.y;
      const along = dx * dir[0] + dy * dir[1];
      if (along <= 0) continue;
      const s = along + Math.abs(dir[0] ? dy : dx) * 2.5;
      if (s < score) {
        score = s;
        best = c;
      }
    }
    if (best) refs.current[best]?.focus();
  };

  const readout = renderReadout?.(hover ?? selected);

  return (
    <div className={cn("space-y-3", className)}>
      <div role="group" aria-label={ariaLabel} className="grid gap-1 sm:gap-1.5" style={{ gridTemplateColumns: `repeat(${COLS}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${ROWS}, auto)` }}>
        {codes.map((code) => {
          const t = INDIA_TILES[code];
          const d = tiles[code];
          const tone = d?.tone;
          const verdict = tone === "go" || tone === "fix" || tone === "rethink" ? tone : null;
          const Icon = verdict ? VERDICT[verdict].Icon : null;
          const isSel = selected === code;
          const isLive = live(code);
          const stamp = animate && verdict ? order.indexOf(code) : -1;
          const style: CSSProperties = { gridColumn: t.x + 1, gridRow: t.y + 1 };
          if (tone === "heat") style.backgroundColor = `color-mix(in oklab, ${color} ${Math.round(18 + (d?.value ?? 0) * 70)}%, var(--surface))`;
          if (tone === "role") style.backgroundColor = `color-mix(in oklab, ${color} 55%, var(--surface))`;
          const label = `${t.name}${d?.label ? `: ${d.label}` : verdict ? `: ${VERDICT[verdict].label}` : ""}`;
          const body = (
            <>
              <span className={cn("font-mono text-[9.5px] leading-none sm:text-[10.5px]", !tone || tone === "muted" ? "text-ink-muted" : "")}>{code.slice(3)}</span>
              {Icon && <Icon aria-hidden className="size-3 sm:size-3.5" />}
              {d?.mark}
            </>
          );
          const cls = cn(
            "relative flex aspect-square min-w-0 flex-col items-center justify-center gap-0.5 rounded-[7px] border text-ink transition-[scale,box-shadow] duration-200 ease-out sm:rounded-lg",
            verdict ? VERDICT_TONE[verdict] : tone && tone !== "muted" ? "border-transparent" : "border-border/60 bg-surface-muted/70",
            verdict && "shadow-clay",
            isLive && "cursor-pointer hover:z-10 hover:scale-110 hover:shadow-float focus-visible:z-10",
            isSel && "z-10 scale-110 shadow-float ring-2 ring-pop ring-offset-2 ring-offset-surface",
            stamp >= 0 && "stamp-in",
          );
          return isLive ? (
            <button
              key={code}
              ref={(el) => {
                refs.current[code] = el;
              }}
              type="button"
              aria-label={label}
              aria-pressed={isSel}
              onClick={() => onSelect?.(isSel ? null : code)}
              onPointerEnter={() => setHover(code)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(code)}
              onBlur={() => setHover(null)}
              onKeyDown={(e) => move(e, code)}
              className={cls}
              style={{ ...style, ...(stamp >= 0 ? { animationDelay: `${200 + stamp * 140}ms`, "--stamp-rot": "0deg" } : null) } as CSSProperties}
            >
              {body}
            </button>
          ) : tone ? (
            <span key={code} role="img" aria-label={label} title={t.name} className={cls} style={style}>
              {body}
            </span>
          ) : (
            // A state without data is context, not content.
            <span key={code} aria-hidden title={t.name} className={cls} style={style}>
              {body}
            </span>
          );
        })}
      </div>
      {renderReadout && <div aria-live="polite">{readout}</div>}
    </div>
  );
}
