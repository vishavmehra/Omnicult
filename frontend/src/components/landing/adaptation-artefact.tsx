import { GitBranch, Repeat2 } from "lucide-react";

import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { Verdict } from "@/components/workflow/verdict";

function Chip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-raised px-2.5 py-1 text-[11.5px] text-ink-body shadow-clay">
      <span className="text-ink-muted">{label}</span>
      {children}
    </span>
  );
}

/**
 * The product in one picture, built from the product's own pieces: an original Marathi line, its Tamil Nadu adaptation with
 * an English back-translation, the reason for the change, evidence tags, a version branch and a readiness verdict.
 * The point it makes: the moment changed (Diwali to Pongal), not just the language.
 */
export function AdaptationArtefact() {
  return (
    <figure data-perch="artefact" aria-label="Example of one adaptation" className="clay-well relative rounded-[28px] p-3 sm:p-4">
      <figcaption className="flex items-center justify-between gap-3 px-2 pt-1 pb-3">
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-ink-secondary">
          <GitBranch aria-hidden className="size-3.5" />
          Festive greeting · v1 to v2
        </span>
      </figcaption>

      <div className="relative grid gap-3">
        {/* Original, slightly recessed: it stays visible and is never overwritten. */}
        <div className="rounded-2xl border border-border/60 bg-surface px-4 py-3.5 shadow-clay">
          <div className="flex items-center justify-between gap-2 text-[11.5px] text-ink-muted">
            <span>Original · v1 · Maharashtra</span>
            <span className="font-mono">mr</span>
          </div>
          <p lang="mr" className="mt-1 text-[20px] text-ink-body">
            दिवाळीच्या हार्दिक शुभेच्छा
          </p>
          <p className="text-[12px] text-ink-muted">Warm Diwali greetings</p>
        </div>

        {/* The adaptation, raised: the moment changes with the region. */}
        <div className="relative rounded-2xl border border-border/60 bg-surface-raised px-4 py-4 shadow-float sm:-mr-6 sm:ml-6">
          <div className="flex items-center justify-between gap-2 text-[11.5px]">
            <span className="font-medium text-ink-secondary">
              Adapted · v2 · <span className="text-ink">Tamil Nadu</span>
            </span>
            <span className="font-mono text-ink-muted">ta</span>
          </div>
          <p lang="ta" className="mt-1 text-[22px] text-ink">
            இனிய பொங்கல் நல்வாழ்த்துகள்
          </p>
          <p className="text-[12.5px] text-ink-secondary">
            <span className="text-ink-muted">Back-translation: </span>Sweet Pongal greetings
          </p>
          <p className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-pop-soft px-2 py-1 text-[12px] text-ink">
            <Repeat2 aria-hidden className="size-3.5 text-pop" />
            Moment swapped: Diwali to Pongal, the Tamil harvest festival
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Chip label="Source">Wikipedia</Chip>
            <Chip label="Kind">Observed</Chip>
            <Chip label="Scope">IN-TN</Chip>
            <span className="inline-flex items-center rounded-full bg-surface-raised px-2.5 py-1 shadow-clay">
              <ConfidenceIndicator level="low" showRule={false} className="text-[11.5px]" />
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 px-1 pt-1">
          <Verdict value="fix" />
          <span className="text-[12px] text-ink-secondary">One source only: add an independent one before launch.</span>
        </div>
      </div>
    </figure>
  );
}
