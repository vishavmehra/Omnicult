"use client";

import { Check, CornerDownRight } from "lucide-react";

import { Tag } from "@/components/evidence/badges";
import { cn } from "@/lib/utils";

import { CITY_TIER_LABEL, langFor } from "../labels";
import { ReactionTag } from "../participants";
import type { FocusGroupResult, FocusTurn } from "./focus-api";

const RELATION: Record<NonNullable<FocusTurn["relation"]>, string> = {
  agrees: "agrees",
  disagrees: "disagrees",
  builds_on: "builds on it",
  new_point: "makes a new point",
};

export const turnId = (index: number) => `fg-turn-${index}`;

/** Scroll to a saved turn and move focus there, so a jump link works for keyboard and screen-reader users too. */
export function jumpToTurn(index: number) {
  const el = document.getElementById(turnId(index));
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  el.focus({ preventScroll: true });
}

function ParticipantTurn({ turn, result }: { turn: FocusTurn; result: FocusGroupResult }) {
  const speaker = result.speakers.find((s) => s.id === turn.participant_id);
  const replied = turn.reply_to_turn_index != null ? result.turns.find((t) => t.turn_index === turn.reply_to_turn_index) : undefined;
  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <p className="text-[13.5px] text-ink">
          <span className="font-semibold">Participant {(turn.ordinal ?? 0) + 1}</span>
          {speaker && (
            <span className="ml-2 text-[12.5px] text-ink-secondary">
              {speaker.state_name}, {speaker.language_name}, {CITY_TIER_LABEL[speaker.city_tier] ?? speaker.city_tier}, age {speaker.age_band}
            </span>
          )}
        </p>
        <ReactionTag value={turn.stance} />
      </div>
      {replied && turn.relation && (
        <p className="mt-0.5 flex flex-wrap items-center gap-1 text-[12.5px] text-ink-secondary">
          <CornerDownRight aria-hidden className="size-3.5 shrink-0" />
          Replying to
          <button
            type="button"
            onClick={() => jumpToTurn(replied.turn_index)}
            className="rounded-sm font-medium text-ink underline underline-offset-2 outline-none hover:text-rose focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {replied.kind === "participant" ? `Participant ${(replied.ordinal ?? 0) + 1}` : "the question"}
          </button>
          <span aria-hidden>·</span>
          {RELATION[turn.relation]}
        </p>
      )}
      <p lang={langFor(turn.text, speaker?.language ?? "en")} className="mt-1 max-w-[72ch] text-[14px] leading-relaxed text-ink">
        {turn.text}
      </p>
      {(turn.themes.length > 0 || turn.basis === "claim_supported") && (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {turn.themes.map((t) => (
            <Tag key={t} className="border-border-strong/50 bg-surface-muted text-ink-secondary">
              {t}
            </Tag>
          ))}
          {turn.basis === "claim_supported" && (
            <Tag className="border-border-strong/60 bg-surface-raised text-ink" title="Cites at least one observed or calculated claim stored for the region.">
              <Check aria-hidden />
              Claim-supported
            </Tag>
          )}
        </p>
      )}
    </>
  );
}

/**
 * The saved transcript as a ruled ledger: the moderator's questions as section rows, participants answering the question and
 * each other, and anything you asked marked as yours. It is a live log, so a new turn is announced politely and the page is
 * never scrolled for the reader.
 */
export function Transcript({ result }: { result: FocusGroupResult }) {
  let question = 0;
  return (
    <ol role="log" aria-live="polite" aria-label="Focus group transcript" className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
      {result.turns.map((turn) => {
        const asked = turn.kind === "moderator" ? ++question : 0;
        return (
          <li
            key={turn.id}
            id={turnId(turn.turn_index)}
            tabIndex={-1}
            className={cn("scroll-mt-24 px-4 py-3 outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring", turn.kind !== "participant" && "bg-surface-muted/60")}
          >
            {turn.kind === "participant" ? (
              <ParticipantTurn turn={turn} result={result} />
            ) : (
              <>
                <p className="type-meta">{turn.kind === "moderator" ? `Moderator, question ${asked} of ${result.guide.length}` : "You asked"}</p>
                <p className="mt-0.5 max-w-[72ch] text-[14px] font-medium leading-snug text-ink">{turn.text}</p>
              </>
            )}
          </li>
        );
      })}
    </ol>
  );
}
