import { cn } from "@/lib/utils";

/**
 * EmptyIllustration: small clay scenes for empty and first-run states, drawn in the workspace role colours with one
 * element idling (a slow float, off under reduced motion). Pass to `EmptyState illustration={…}`.
 *
 *   ledger: an open ledger (briefs, reports, history)   film: an empty film strip (creatives, keyframes)
 *   map: a cluster of state tiles (regions)              panel: three empty speech bubbles (audience)
 *   chart: a flat line waiting for data (results)        stamp: a blank stamp on paper (verdicts, approvals)
 */
export type EmptyKind = "ledger" | "film" | "map" | "panel" | "chart" | "stamp";

const INK = "var(--ambient-ink)";

export function EmptyIllustration({ kind, className }: { kind: EmptyKind; className?: string }) {
  return (
    <svg viewBox="0 0 160 112" aria-hidden className={cn("h-24 w-auto shrink-0", className)} fill="none" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="80" cy="102" rx="54" ry="6" fill={INK} opacity={0.08} />
      {kind === "ledger" && (
        <>
          <path d="M22 30 C40 24 62 26 80 34 L80 94 C62 86 40 84 22 90 Z" fill="var(--role-desk)" stroke={INK} strokeOpacity={0.35} strokeWidth={1.5} />
          <path d="M138 30 C120 24 98 26 80 34 L80 94 C98 86 120 84 138 90 Z" fill="var(--surface-raised)" stroke={INK} strokeOpacity={0.35} strokeWidth={1.5} />
          {[46, 56, 66, 76].map((y) => (
            <path key={y} d={`M92 ${y - 4} C104 ${y - 7} 116 ${y - 7} 128 ${y - 5}`} stroke={INK} strokeOpacity={0.22} strokeWidth={1.5} />
          ))}
          <path className="float-idle" d="M110 22 L110 44 L116 38 L122 44 L122 22 Z" fill="var(--pop)" />
        </>
      )}
      {kind === "film" && (
        <g className="float-idle">
          <g transform="rotate(-6 80 60)">
            <rect x="18" y="34" width="124" height="52" rx="8" fill="#1f2026" />
            {[24, 36, 48, 60, 72, 84, 96, 108, 120, 132].map((x) => (
              <g key={x} fill="var(--surface-raised)" opacity={0.5}>
                <rect x={x} y="38" width="6" height="4" rx="1" />
                <rect x={x} y="78" width="6" height="4" rx="1" />
              </g>
            ))}
            {[26, 66, 106].map((x, i) => (
              <rect key={x} x={x} y="46" width="30" height="28" rx="4" fill={["var(--role-studio)", "var(--role-desk)", "var(--role-lab)"][i]} opacity={0.85} />
            ))}
          </g>
        </g>
      )}
      {kind === "map" && (
        <>
          {[
            [56, 22], [74, 22], [56, 40], [74, 40], [92, 40], [38, 58], [56, 58], [74, 58], [92, 58], [56, 76], [74, 76],
          ].map(([x, y], i) => (
            <rect key={i} x={x} y={y} width="16" height="16" rx="4" fill={i === 7 ? "var(--role-lens)" : "var(--surface-raised)"} stroke={INK} strokeOpacity={0.25} strokeWidth={1.2} />
          ))}
          <g className="float-idle">
            <path d="M82 48 C82 41 92 41 92 48 C92 54 87 58 87 62 C87 58 82 54 82 48 Z" fill="var(--pop)" />
            <circle cx="87" cy="48" r="2" fill="var(--surface-raised)" />
          </g>
        </>
      )}
      {kind === "panel" && (
        <>
          <path d="M24 30 h56 a10 10 0 0 1 10 10 v12 a10 10 0 0 1 -10 10 h-46 l-10 8 v-8 a10 10 0 0 1 0 -20 v-2 a10 10 0 0 1 0 -10 z" fill="var(--role-lab)" stroke={INK} strokeOpacity={0.3} strokeWidth={1.4} />
          <g className="float-idle">
            <path d="M136 46 h-44 a10 10 0 0 0 -10 10 v10 a10 10 0 0 0 10 10 h34 l10 8 v-8 a10 10 0 0 0 0 -20 z" fill="var(--surface-raised)" stroke={INK} strokeOpacity={0.3} strokeWidth={1.4} />
          </g>
          <circle cx="40" cy="46" r="2.5" fill={INK} opacity={0.35} />
          <circle cx="50" cy="46" r="2.5" fill={INK} opacity={0.35} />
          <circle cx="60" cy="46" r="2.5" fill={INK} opacity={0.35} />
        </>
      )}
      {kind === "chart" && (
        <>
          <rect x="20" y="20" width="120" height="74" rx="10" fill="var(--surface-raised)" stroke={INK} strokeOpacity={0.25} strokeWidth={1.4} />
          {[40, 56, 72].map((y) => (
            <path key={y} d={`M30 ${y} H130`} stroke={INK} strokeOpacity={0.1} strokeWidth={1} />
          ))}
          <path d="M30 78 H130" stroke="var(--role-pulse-strong)" strokeWidth={2.5} />
          <circle className="float-idle" cx="104" cy="78" r="5" fill="var(--pop)" />
        </>
      )}
      {kind === "stamp" && (
        <>
          <path d="M30 34 L122 26 L132 88 L40 96 Z" fill="var(--surface-raised)" stroke={INK} strokeOpacity={0.25} strokeWidth={1.4} />
          <g className="float-idle">
            <circle cx="82" cy="60" r="20" stroke="var(--role-launch-strong)" strokeWidth={3} strokeDasharray="5 4" />
            <circle cx="82" cy="60" r="13" stroke="var(--role-launch-strong)" strokeWidth={1.5} strokeOpacity={0.6} />
          </g>
        </>
      )}
    </svg>
  );
}
