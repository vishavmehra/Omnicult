"use client";

import { Send, UserRound, UsersRound } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Tag } from "@/components/evidence/badges";
import { LimitationList } from "@/components/evidence/limitation-list";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useAskPanel, useParticipants, useQuestions, useRuns, useSamplingOptions } from "./api";
import { ChipSelect, DistributionLedger, Disclosure, FieldBlock, NativeSelect, Panel, RunPicker } from "./lab-parts";
import { CITY_TIER_LABEL, DIMENSION_LABEL, langFor, pluralise } from "./labels";
import { Identity, ReactionTag, Traits } from "./participants";
import { useRunBlock } from "./quick-read";
import type { AskBody, PanelAnswer, PanelParticipant, PanelQuestion, RunSummary } from "./types";
import { isUsable } from "./types";
import type { useLabLocation } from "./use-lab-location";

type Loc = ReturnType<typeof useLabLocation>;
type Filter = { states: string[]; languages: string[]; city_tiers: string[]; age_bands: string[] };
const EMPTY_FILTER: Filter = { states: [], languages: [], city_tiers: [], age_bands: [] };

const matches = (p: PanelParticipant, f: Filter) =>
  (!f.states.length || f.states.includes(p.state_code)) &&
  (!f.languages.length || f.languages.includes(p.language)) &&
  (!f.city_tiers.length || f.city_tiers.includes(p.city_tier)) &&
  (!f.age_bands.length || f.age_bands.includes(p.age_band));

function describeTarget(q: PanelQuestion, byId: Map<string, PanelParticipant>) {
  if (q.target_kind === "panel") return "The whole panel";
  if (q.target_kind === "participant") {
    const p = byId.get(String(q.target.participant_id));
    return p ? `Participant ${p.ordinal + 1}` : "One participant";
  }
  const f = (q.target.filter ?? {}) as Partial<Filter>;
  const parts = (Object.keys(DIMENSION_LABEL) as (keyof Filter)[])
    .filter((k) => f[k]?.length)
    .map((k) => `${DIMENSION_LABEL[k].toLowerCase()} ${f[k]!.map((v) => CITY_TIER_LABEL[v] ?? v).join(" or ")}`);
  return `A subgroup: ${parts.join(", ") || "selected"}`;
}

function memoryNote(a: PanelAnswer) {
  const own = a.memory_refs.filter((r) => r === a.participant_id).length;
  const earlier = a.memory_refs.length - own;
  const bits = [own ? "their own stored response" : null, earlier ? `${pluralise(earlier, "earlier answer")}` : null].filter(Boolean);
  return bits.length ? `Drew on ${bits.join(" and ")}` : "No stored record was cited";
}

function AnswerRow({ a, p, campaignId, runId }: { a: PanelAnswer; p?: PanelParticipant; campaignId: string; runId: string }) {
  const [history, setHistory] = useState(false);
  return (
    <li className="space-y-1 py-2.5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        {p ? <Identity p={p} /> : <p className="text-[13.5px] font-semibold text-ink">Participant {a.ordinal + 1}</p>}
        <ReactionTag value={a.stance} />
      </div>
      <p lang={langFor(a.answer, p?.language ?? "en")} className="max-w-[68ch] text-[14px] leading-snug text-ink">{a.answer}</p>
      <p className="type-meta">
        {memoryNote(a)}
        {a.model_id ? ` · model ${a.model_id}` : " · no model called"}
        {p && (
          <>
            {" · "}
            <button type="button" aria-expanded={history} onClick={() => setHistory((v) => !v)} className="font-medium text-ink-secondary underline underline-offset-2 hover:text-ink">
              {history ? "Hide history" : "Show their history"}
            </button>
          </>
        )}
      </p>
      {history && p && (
        <div className="rounded-md bg-surface-muted/60 px-3 py-2">
          <HistoryList campaignId={campaignId} run={runId} participant={p} />
        </div>
      )}
    </li>
  );
}

/** One question with everything it produced: the stance tally, the answers by participant, who did not answer, and the limits. */
function QuestionCard({ q, participants, defaultOpen }: { q: PanelQuestion; participants: PanelParticipant[]; defaultOpen?: boolean }) {
  const byId = useMemo(() => new Map(participants.map((p) => [p.id, p])), [participants]);
  const unanswered = q.unanswered_participant_ids.map((id) => byId.get(id)).filter((p): p is PanelParticipant => Boolean(p));
  const asked = q.answers.length + q.unanswered_participant_ids.length;
  return (
    <article className="rounded-card border border-border bg-surface">
      <header className="space-y-1 border-b border-border px-4 py-3">
        <p className="text-[14.5px] font-semibold leading-snug text-ink">{q.question}</p>
        <p className="type-meta flex flex-wrap items-center gap-x-2">
          <span>{describeTarget(q, byId)}</span>
          <span aria-hidden>·</span>
          <span title={formatDateTime(q.created_at)}>{formatRelative(q.created_at)}</span>
        </p>
      </header>
      <div className="space-y-4 px-4 py-3">
        <p className="text-[13px] text-ink-body">
          {q.answers.length} of {asked} selected {asked === 1 ? "participant" : "participants"} answered.
          {unanswered.length === 0 && q.unanswered_participant_ids.length === 0 ? " Every selected participant answered." : ""}
        </p>
        {q.answers.length > 1 && (
          <Disclosure summary="Stance of the answers returned" defaultOpen={defaultOpen}>
            <DistributionLedger dist={q.stance} noun="answers returned" />
          </Disclosure>
        )}
        {q.summaries.length > 0 && (
          <div className="space-y-1">
            <p className="type-meta flex items-center gap-2">
              How the answers differ
              <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary">Model interpretation</Tag>
            </p>
            {q.summaries.map((s, i) => (
              <p key={i} className="max-w-[68ch] text-[13.5px] text-ink-body">{s}</p>
            ))}
          </div>
        )}
        <ul className="ledger-rules">
          {q.answers.map((a) => (
            <AnswerRow key={a.id} a={a} p={byId.get(a.participant_id)} campaignId={q.campaign_id} runId={q.run_id} />
          ))}
        </ul>
        {q.unanswered_participant_ids.length > 0 && (
          <div className="rounded-md border border-warning/40 bg-warning-soft/60 px-3.5 py-2.5">
            <p className="text-[13.5px] font-medium text-ink">
              {pluralise(q.unanswered_participant_ids.length, "participant")} did not get an answer
            </p>
            <p className="text-[13px] text-ink-body">
              The model returned nothing for them, or the batch they were in failed. They are not guessed at and not asked again automatically.
            </p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[13px] text-ink-body">
              {(unanswered.length ? unanswered : []).map((p) => (
                <li key={p.id}>
                  Participant {p.ordinal + 1}: {p.persona}
                </li>
              ))}
              {unanswered.length < q.unanswered_participant_ids.length && <li>{q.unanswered_participant_ids.length - unanswered.length} more, not on the first page of the panel list.</li>}
            </ul>
          </div>
        )}
        <LimitationList items={q.limitations} />
      </div>
    </article>
  );
}

function AskForm({ run, participants, initialParticipant, initialQuestion, onAsked, onFocus }: { run: RunSummary; participants: PanelParticipant[]; initialParticipant: string | null; initialQuestion: string; onAsked(q: PanelQuestion): void; onFocus(id: string | null): void }) {
  const { campaign, project } = useCampaign();
  const options = useSamplingOptions();
  const ask = useAskPanel(campaign.id, run.id);
  const block = useRunBlock();
  const maxAsk = options.data?.limits.ask_max_participants ?? 60;

  // A hand-off may name a participant of another panel; only one that is in this panel counts.
  const known = participants.some((p) => p.id === initialParticipant) ? initialParticipant : null;
  const [kind, setKind] = useState<"participant" | "subgroup" | "panel">(known ? "participant" : "panel");
  const [participantId, setParticipantId] = useState(known ?? participants[0]?.id ?? "");
  const [filter, setFilter] = useState<Filter>(EMPTY_FILTER);
  const [question, setQuestion] = useState(initialQuestion);

  // A hand-off from a result ("Ask this participant", a suggested question) arrives after this form mounted:
  // adjust state while rendering when the hand-off changes (React's pattern for resetting state on a prop change).
  const [seenKnown, setSeenKnown] = useState(known);
  if (known !== seenKnown) {
    setSeenKnown(known);
    if (known) {
      setKind("participant");
      setParticipantId(known);
    }
  }
  const [seenQuestion, setSeenQuestion] = useState(initialQuestion);
  if (initialQuestion !== seenQuestion) {
    setSeenQuestion(initialQuestion);
    if (initialQuestion) setQuestion(initialQuestion);
  }
  // The participant being asked is the one whose identity and history the page shows.
  useEffect(() => onFocus(kind === "participant" ? participantId || null : null), [kind, participantId, onFocus]);

  const dims = useMemo(() => {
    const uniq = (pick: (p: PanelParticipant) => [string, string]) => [...new Map(participants.map(pick)).entries()].map(([value, label]) => ({ value, label }));
    return {
      states: uniq((p) => [p.state_code, p.state_name]),
      languages: uniq((p) => [p.language, p.language_name]),
      city_tiers: uniq((p) => [p.city_tier, CITY_TIER_LABEL[p.city_tier] ?? p.city_tier]),
      age_bands: uniq((p) => [p.age_band, p.age_band]),
    };
  }, [participants]);

  const hasFilter = Object.values(filter).some((v) => v.length);
  const selected = kind === "participant" ? participants.filter((p) => p.id === participantId) : kind === "subgroup" ? participants.filter((p) => matches(p, filter)) : participants;
  const questionError = question.trim().length === 0 ? "Write the question first." : null;
  const targetError =
    kind === "participant" && !participantId ? "Choose a participant." : kind === "subgroup" && !hasFilter ? "Choose at least one value to select a subgroup." : selected.length === 0 ? "No participant matches." : selected.length > maxAsk ? `A question can go to at most ${maxAsk} participants; narrow the subgroup.` : null;
  const [touched, setTouched] = useState(false);

  function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (questionError || targetError) return;
    const body: AskBody = {
      question: question.trim(),
      target:
        kind === "participant"
          ? { kind, participant_id: participantId }
          : kind === "panel"
            ? { kind }
            : { kind, filter: Object.fromEntries(Object.entries(filter).filter(([, v]) => v.length)) as never },
    };
    ask.mutate(body, {
      onSuccess: (q) => {
        setQuestion("");
        setTouched(false);
        onAsked(q);
      },
    });
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <fieldset className="space-y-2">
        <legend className="mb-1 text-[13px] font-medium text-ink">Ask</legend>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Who to ask">
          {(
            [
              ["participant", "One participant", UserRound],
              ["subgroup", "A subgroup", UsersRound],
              ["panel", `Everyone (${participants.length})`, UsersRound],
            ] as const
          ).map(([k, label, Icon]) => (
            <label key={k} className="relative">
              <input type="radio" name="ask-target" className="peer sr-only" checked={kind === k} onChange={() => setKind(k)} />
              <span
                className={cn(
                  "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 text-[13px] transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring",
                  kind === k ? "border-ink-secondary bg-surface-raised font-medium text-ink shadow-clay" : "border-border-strong/55 text-ink-secondary hover:bg-surface-muted",
                )}
              >
                <Icon aria-hidden className="size-3.5" />
                {label}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {kind === "participant" && (
        <FieldBlock label="Participant" htmlFor="ask-participant" hint="Answers come from this participant's stored response and earlier answers, so the same person answers every time.">
          <NativeSelect id="ask-participant" value={participantId} onChange={(e) => setParticipantId(e.target.value)} aria-describedby="ask-participant-hint">
            {participants.map((p) => (
              <option key={p.id} value={p.id}>
                Participant {p.ordinal + 1}: {p.persona}
              </option>
            ))}
          </NativeSelect>
        </FieldBlock>
      )}

      {kind === "subgroup" && (
        <div className="space-y-3">
          {dims.states.length > 1 && <ChipSelect legend="States" options={dims.states} value={filter.states} onChange={(v) => setFilter({ ...filter, states: v })} />}
          <ChipSelect legend="Languages" options={dims.languages} value={filter.languages} onChange={(v) => setFilter({ ...filter, languages: v })} />
          <ChipSelect legend="City tiers" options={dims.city_tiers} value={filter.city_tiers} onChange={(v) => setFilter({ ...filter, city_tiers: v })} />
          <ChipSelect legend="Age bands" options={dims.age_bands} value={filter.age_bands} onChange={(v) => setFilter({ ...filter, age_bands: v })} hint="Within a dimension any chosen value matches; across dimensions all must match." />
        </div>
      )}

      <p className="type-meta" aria-live="polite">
        {selected.length === 0 ? "No participant selected." : `${pluralise(selected.length, "synthetic participant")} will be asked.`}
      </p>

      <FieldBlock label="Question" htmlFor="ask-question" error={touched ? (questionError ?? targetError) : null} hint="Answers come from each participant's stored response and earlier answers. Nothing new is invented about them, and a participant with no stored response is not asked.">
        <Textarea id="ask-question" value={question} maxLength={1000} rows={3} onChange={(e) => setQuestion(e.target.value)} aria-describedby="ask-question-hint" />
      </FieldBlock>

      {ask.error != null && <ErrorState error={ask.error} onRetry={() => ask.reset()} />}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button type="submit" size="lg" disabled={ask.isPending || Boolean(block)}>
          <Send aria-hidden />
          {ask.isPending ? "Asking…" : "Ask the panel"}
        </Button>
        <p className="max-w-[60ch] text-[12.5px] text-ink-secondary">
          {block ?? (project.mode === "demo" ? "Demo project: answers quote each participant's stored fixture response; no model is called." : "Live: each batch of up to eight participants is one model call.")}
        </p>
      </div>
    </form>
  );
}

/** What one participant has been asked and has answered here, oldest memory last. Their answers feed their next ones. */
function HistoryList({ campaignId, run, participant }: { campaignId: string; run: string; participant: PanelParticipant }) {
  const history = useQuestions(campaignId, run, participant.id);
  if (history.error) return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  if (history.isPending) return <LoadingState label="Loading this participant's history…" />;
  if (history.data.items.length === 0) {
    return <p className="text-[13px] text-ink-muted">No question has been put to this participant yet. Their answers draw on their stored response and, from now on, on each answer they give here.</p>;
  }
  return (
    <ul className="ledger-rules">
      {history.data.items.map((q) => {
        const a = q.answers.find((x) => x.participant_id === participant.id);
        return (
          <li key={q.id} className="space-y-0.5 py-2">
            <p className="type-meta">{q.question} · {formatRelative(q.created_at)}</p>
            {a ? <p lang={langFor(a.answer, participant.language)} className="text-[13.5px] text-ink">{a.answer}</p> : <p className="text-[13px] text-ink-muted">Selected, but not answered.</p>}
          </li>
        );
      })}
    </ul>
  );
}

function ParticipantHistory({ campaignId, run, participant }: { campaignId: string; run: string; participant: PanelParticipant }) {
  return (
    <Panel id="ask-history-participant" title={`Participant ${participant.ordinal + 1}`} meta="Stable identity and history">
      <div className="space-y-3">
        <Identity p={participant} />
        <Traits p={participant} />
        <HistoryList campaignId={campaignId} run={run} participant={participant} />
      </div>
    </Panel>
  );
}

export function AskTab({ loc }: { loc: Loc }) {
  const { campaign } = useCampaign();
  const options = useSamplingOptions();
  const quick = useRuns(campaign.id, "quick_read");
  const study = useRuns(campaign.id, "audience_study");
  const [justAsked, setJustAsked] = useState<PanelQuestion | null>(null);

  const panels = useMemo(
    () => [...(quick.data ?? []), ...(study.data ?? [])].filter((r) => isUsable(r.status)).sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [quick.data, study.data],
  );
  const run = panels.find((r) => r.id === loc.runId) ?? panels[0];
  const parts = useParticipants(campaign.id, run?.id);
  const questions = useQuestions(campaign.id, run?.id);
  const regionName = (code: string) => options.data?.states.find((s) => s.code === code)?.name ?? code;
  const participants = parts.data?.items ?? [];
  const [focusId, setFocusId] = useState<string | null>(null);
  const focus = focusId ? participants.find((p) => p.id === focusId) : undefined;

  if (quick.error || study.error) return <ErrorState error={quick.error ?? study.error} onRetry={() => { void quick.refetch(); void study.refetch(); }} />;
  if (quick.isPending || study.isPending) return <LoadingState label="Loading panels…" />;

  if (panels.length === 0) {
    return (
      <EmptyState
        title="No panel to ask yet"
        description="Ask the Panel puts a follow-up question to the synthetic participants of a finished Quick Read or Audience Study, answered from their stored responses. Run one of those first."
        needs={[
          { label: "A Quick Read or Audience Study that has finished", met: false },
          { label: "At least one participant with a stored response", met: false },
        ]}
        action={
          <Button variant="outline" onClick={() => loc.setTab("quick")}>
            Go to Quick Read
          </Button>
        }
      />
    );
  }

  const history = (questions.data?.items ?? []).filter((q) => q.id !== justAsked?.id);

  return (
    <div className="space-y-5">
      <p className="max-w-[68ch] text-[14px] text-ink-secondary">
        Put a follow-up question to one participant, a subgroup or the whole panel. Each answer comes from that participant&apos;s stored response and earlier answers, so the same synthetic person keeps their identity across questions.
      </p>
      <div className="space-y-1.5">
        <p className="text-[13px] font-medium text-ink">Panel</p>
        <RunPicker
          runs={panels}
          selectedId={run?.id}
          onSelect={(id) => {
            setJustAsked(null);
            loc.selectRun(id);
          }}
          regionName={regionName}
          describe={(r) => `${r.kind === "quick_read" ? "Quick Read" : "Audience Study"}, ${pluralise(r.participant_count, "synthetic participant")}`}
        />
      </div>

      {run && (parts.isPending ? <LoadingState label="Loading the panel…" /> : parts.error ? <ErrorState error={parts.error} onRetry={() => void parts.refetch()} /> : (
        <>
          <Panel id="ask-form" title="New question" meta={`${participants.length} synthetic participants in this panel`}>
            <AskForm
              key={run.id}
              run={run}
              participants={participants}
              initialParticipant={loc.participantId}
              initialQuestion={loc.question ?? ""}
              onAsked={(q) => setJustAsked(q)}
              onFocus={setFocusId}
            />
          </Panel>

          {focus && <ParticipantHistory campaignId={campaign.id} run={run.id} participant={focus} />}

          {justAsked && <QuestionCard q={justAsked} participants={participants} defaultOpen />}

          <section aria-labelledby="ask-earlier" className="space-y-3">
            <h3 id="ask-earlier" className="text-[14px] font-semibold text-ink">
              Earlier questions to this panel
            </h3>
            {questions.error ? (
              <ErrorState error={questions.error} onRetry={() => void questions.refetch()} />
            ) : questions.isPending ? (
              <LoadingState label="Loading earlier questions…" />
            ) : history.length === 0 ? (
              <p className="rounded-md border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-muted">No earlier questions for this panel.</p>
            ) : (
              <div className="space-y-3">
                {history.map((q) => (
                  <QuestionCard key={q.id} q={q} participants={participants} />
                ))}
              </div>
            )}
          </section>
        </>
      ))}
    </div>
  );
}
