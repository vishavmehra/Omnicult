"use client";

import { MessageCircleQuestion } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Disclosure } from "./lab-parts";
import { PanelGrid, type PanelFace } from "./panel-grid";
import { REACTIONS, REACTION_LABEL, SURVIVAL_LABEL, isGrounded, langFor } from "./labels";
import type { GroundedPoint, GroundingClaim, PanelParticipant, QuickReadParticipant, ReactionCategory, StudyParticipant } from "./types";

export function ReactionTag({ value }: { value: ReactionCategory | null | undefined }) {
  const r = REACTIONS.find((x) => x.key === value);
  if (!r) return <span className="text-[12px] text-ink-muted">No reaction saved</span>;
  return (
    <span className="inline-flex items-center gap-1 text-[12.5px] font-medium text-ink">
      <r.Icon aria-hidden className="size-3.5" />
      {REACTION_LABEL[r.key]}
    </span>
  );
}

/** Who this participant is: a stable number and id, the sampling dimensions in words, and the seeded style knobs. Nothing else is assumed. */
export function Identity({ p }: { p: PanelParticipant }) {
  return (
    <div className="min-w-0 space-y-0.5">
      <p className="text-[13.5px] text-ink">
        <span className="font-semibold">Participant {p.ordinal + 1}</span> <span className="font-mono text-[11px] text-ink-muted">{p.id.slice(0, 8)}</span>
      </p>
      <p className="text-[13px] text-ink-secondary">{p.persona}</p>
    </div>
  );
}

export function Traits({ p }: { p: PanelParticipant }) {
  const entries = Object.entries(p.traits);
  if (!entries.length) return null;
  return (
    <dl className="type-ledger flex flex-wrap gap-x-4 gap-y-0.5 text-[12px]">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-1">
          <dt className="text-ink-muted">{humanize(k)}:</dt>
          <dd className="text-ink-body">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function AskButton({ onAsk }: { onAsk(): void }) {
  return (
    <Button size="sm" variant="outline" onClick={onAsk}>
      <MessageCircleQuestion aria-hidden />
      Ask this participant
    </Button>
  );
}

function Points({ label, points, claims }: { label: string; points: GroundedPoint[]; claims: GroundingClaim[] }) {
  if (!points.length) return null;
  return (
    <div>
      <p className="type-meta">{label}</p>
      <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink-body marker:text-ink-muted">
        {points.map((p, i) => (
          <li key={i}>
            {p.text}{" "}
            <span className="text-[11.5px] text-ink-muted">({isGrounded(p, claims) ? "cites a claim" : "interpretation"})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const SHOWN = 12;

function ShowAll({ total, all, onToggle }: { total: number; all: boolean; onToggle(): void }) {
  if (total <= SHOWN) return null;
  return (
    <button type="button" onClick={onToggle} className="mt-2 text-[12.5px] font-medium text-ink-secondary underline underline-offset-2 hover:text-ink">
      {all ? "Show fewer participants" : `Show all ${total} participants`}
    </button>
  );
}

export function QuickReadParticipants({ participants, claims, onAsk }: { participants: QuickReadParticipant[]; claims: GroundingClaim[]; onAsk(id: string): void }) {
  const [all, setAll] = useState(false);
  const rows = all ? participants : participants.slice(0, SHOWN);
  const faces: PanelFace[] = participants.map((p) => ({
    id: p.id,
    ordinal: p.ordinal,
    persona: p.persona,
    lang: langFor(p.response?.first_reaction, p.language),
    mood: p.response?.sentiment ?? null,
    quote: p.response?.first_reaction ?? null,
  }));
  return (
    <div className="space-y-4">
      <PanelGrid faces={faces} onAsk={onAsk} ariaLabel="The panel" />
      <ul className="ledger-rules">
        {rows.map((p) => {
          const r = p.response;
          return (
            <li key={p.id} className="space-y-2 py-3">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                <Identity p={p} />
                <ReactionTag value={r?.sentiment} />
              </div>
              {r ? (
                <>
                  <p lang={langFor(r.first_reaction, p.language)} className="max-w-[68ch] text-[14px] leading-snug text-ink">{r.first_reaction}</p>
                  <Disclosure summary="Full response">
                    <div className="space-y-2.5 rounded-md bg-surface-muted/60 px-3 py-2.5">
                      <div>
                        <p className="type-meta">Message in their words · {SURVIVAL_LABEL[r.message.survival]}</p>
                        <p lang={langFor(r.message.restated, p.language)} className="text-[13px] text-ink-body">{r.message.restated}</p>
                      </div>
                      <Points label="Liked" points={r.positives} claims={claims} />
                      <Points label="Put off" points={r.negatives} claims={claims} />
                      <Points label="Confused by" points={r.confusion} claims={claims} />
                      <Points label="Regional concerns" points={r.regional_concerns} claims={claims} />
                      <p className="type-ledger text-[12.5px] text-ink-secondary">
                        Ratings (1 to 5): clarity {r.ratings.clarity ?? "n/a"}, cultural relevance {r.ratings.cultural_relevance ?? "n/a"}, cultural risk {r.ratings.cultural_risk ?? "n/a"} (5 is most risk)
                      </p>
                      {r.quoted_passage && (
                        <p className="text-[12.5px] text-ink-secondary">
                          Quoted from the creative (checked in code): <q lang={langFor(r.quoted_passage, p.language)} className="text-ink">{r.quoted_passage}</q>
                        </p>
                      )}
                      <Traits p={p} />
                    </div>
                  </Disclosure>
                </>
              ) : (
                <p className="text-[13px] text-ink-muted">No response was saved for this participant.</p>
              )}
              {r && <AskButton onAsk={() => onAsk(p.id)} />}
            </li>
          );
        })}
      </ul>
      <ShowAll total={participants.length} all={all} onToggle={() => setAll((v) => !v)} />
    </div>
  );
}

export function StudyParticipants({ participants, onAsk }: { participants: StudyParticipant[]; onAsk(id: string): void }) {
  const [all, setAll] = useState(false);
  const rows = all ? participants : participants.slice(0, SHOWN);
  const faces: PanelFace[] = participants.map((p) => {
    const first = p.interview?.status === "completed" ? p.interview.answers[0] : undefined;
    return {
      id: p.id,
      ordinal: p.ordinal,
      persona: p.persona,
      lang: langFor(first?.answer, p.language),
      mood: p.interview?.status === "completed" ? (p.interview.reaction ?? null) : null,
      quote: first?.answer ?? null,
      footer: first ? <span className="text-ink-muted">Asked: {first.question}</span> : undefined,
    };
  });
  return (
    <div className="space-y-4">
      <PanelGrid faces={faces} onAsk={onAsk} ariaLabel="The panel" />
      <ul className="ledger-rules">
        {rows.map((p) => {
          const iv = p.interview;
          const done = iv?.status === "completed";
          return (
            <li key={p.id} className="space-y-2 py-3">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                <Identity p={p} />
                {done ? <ReactionTag value={iv?.reaction} /> : <span className="text-[12px] text-ink-muted">{iv ? "Interview failed" : "No interview saved"}</span>}
              </div>
              {done && iv ? (
                <>
                  <p className="type-ledger text-[12.5px] text-ink-secondary">
                    {iv.comprehension ? `Message: ${SURVIVAL_LABEL[iv.comprehension]}` : "Message understanding not recorded"}
                    {iv.themes.length > 0 && ` · Themes: ${iv.themes.join(", ")}`}
                    {iv.concerns.length > 0 && ` · Concerns: ${iv.concerns.join(", ")}`}
                  </p>
                  {iv.misunderstanding && <p className="text-[13px] text-ink-body">Misread as: {iv.misunderstanding}</p>}
                  <Disclosure summary={`Interview, ${iv.answers.length} ${iv.answers.length === 1 ? "answer" : "answers"}`}>
                    <dl className="space-y-2 rounded-md bg-surface-muted/60 px-3 py-2.5">
                      {iv.answers.map((a) => (
                        <div key={a.question_id}>
                          <dt className="type-meta">{a.question}</dt>
                          <dd lang={langFor(a.answer, p.language)} className="text-[13px] text-ink-body">{a.answer}</dd>
                        </div>
                      ))}
                      <Traits p={p} />
                    </dl>
                  </Disclosure>
                </>
              ) : (
                <p className={cn("text-[13px] text-ink-muted")}>This participant has no usable interview, so they are counted as not responding.</p>
              )}
              {done && <AskButton onAsk={() => onAsk(p.id)} />}
            </li>
          );
        })}
      </ul>
      <ShowAll total={participants.length} all={all} onToggle={() => setAll((v) => !v)} />
    </div>
  );
}

