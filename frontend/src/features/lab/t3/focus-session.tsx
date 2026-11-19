"use client";

import { MessageSquarePlus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/errors";

import { Disclosure, RunBanner } from "../lab-parts";
import { pluralise } from "../labels";
import { Provenance } from "../summary-parts";
import { isActive, isUsable } from "../types";
import { useInterject, type FocusGroupResult } from "./focus-api";
import { FocusSummary } from "./focus-summary";
import { Transcript } from "./focus-transcript";

/**
 * Put a question to the group while it talks. The moderator relays it at the next turn boundary, so the form says so and shows
 * what is still waiting; once the session has finished the form is gone and the server would refuse it anyway.
 */
function AskGroup({ campaignId, result, max }: { campaignId: string; result: FocusGroupResult; max: number }) {
  const [text, setText] = useState("");
  const send = useInterject(campaignId, result.id);
  const waiting = result.interjections.filter((i) => i.status === "pending");
  const full = result.interjections.length >= max;
  const reason = send.error instanceof ApiError ? send.error.message : send.error ? "The question could not be sent. Try again." : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || send.isPending || full) return;
    send.mutate(value, { onSuccess: () => setText("") });
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded-card border border-border bg-surface px-4 py-3" aria-labelledby="fg-ask-title">
      <h3 id="fg-ask-title" className="text-[14px] font-semibold text-ink">
        Ask the group
      </h3>
      <label htmlFor="fg-ask" className="sr-only">
        Your question for the group
      </label>
      <Textarea id="fg-ask" value={text} maxLength={1000} rows={2} disabled={full} onChange={(e) => setText(e.target.value)} aria-describedby="fg-ask-hint" placeholder="What would you ask them next?" />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button type="submit" size="sm" variant="outline" disabled={!text.trim() || send.isPending || full}>
          <MessageSquarePlus aria-hidden />
          {send.isPending ? "Sending…" : "Ask the group"}
        </Button>
        <p id="fg-ask-hint" className="type-meta">
          {full ? `This session relays at most ${max} questions.` : `The moderator asks it at the next turn. ${max - result.interjections.length} of ${max} questions left.`}
        </p>
      </div>
      {reason && (
        <p role="alert" className="text-[12.5px] text-warning">
          {reason}
        </p>
      )}
      {waiting.length > 0 && (
        <ul className="space-y-0.5 text-[12.5px] text-ink-secondary" aria-label="Questions waiting for the moderator" aria-live="polite">
          {waiting.map((w) => (
            <li key={w.id}>
              Waiting for the next turn: {w.text}
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}

export function FocusSession({ campaignId, result, maxInterjections, onNewRun }: { campaignId: string; result: FocusGroupResult; maxInterjections: number; onNewRun(): void }) {
  const active = isActive(result.status);
  return (
    <div className="space-y-5">
      <RunBanner run={result} label="Focus Group" onNewRun={onNewRun} />

      <Disclosure summary={`${pluralise(result.speakers.length, "speaker")} and the guide`}>
        <div className="space-y-3 text-[13px] text-ink-body">
          <ul className="ledger-rules">
            {result.speakers.map((s) => (
              <li key={s.id} className="py-1.5">
                <span className="font-medium text-ink">Participant {s.ordinal + 1}</span> <span className="text-ink-secondary">{s.persona}</span>
              </li>
            ))}
          </ul>
          <ol className="list-decimal space-y-1 pl-5 marker:text-ink-muted">
            {result.guide.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ol>
        </div>
      </Disclosure>

      {result.turns.length > 0 ? <Transcript result={result} /> : active ? <LoadingState label="The moderator is opening the session…" /> : null}

      {result.interjections_open && <AskGroup campaignId={campaignId} result={result} max={maxInterjections} />}

      {result.summary.participant_turns > 0 && <FocusSummary summary={result.summary} />}

      <LimitationList items={result.limitations} />
      {isUsable(result.status) && <Provenance meta={result.run_metadata} />}
    </div>
  );
}
