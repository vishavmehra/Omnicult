"use client";

import { ArrowDown, ArrowUp, Play, Plus, X } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { cn } from "@/lib/utils";

import { useParticipants, useRuns } from "../api";
import { CONTROL, FieldBlock, NativeSelect } from "../lab-parts";
import { pluralise } from "../labels";
import { useRunBlock } from "../quick-read";
import { isUsable } from "../types";
import type { useLabLocation } from "../use-lab-location";
import { useStartFocusGroup, type FocusGroupCreate } from "./focus-api";

type Loc = ReturnType<typeof useLabLocation>;
type Defaults = { guide: string[]; limits: { focus_min_speakers: number; focus_max_speakers: number; focus_max_guide_questions: number } };
type Question = { key: number; text: string };

const KIND_LABEL = { quick_read: "Quick Read", audience_study: "Audience Study" } as const;

/** Icon-only button with a real label, so the guide editor works with a keyboard and a screen reader. */
function IconButton({ label, onClick, disabled, children }: { label: string; onClick(): void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className="grid size-8 shrink-0 place-items-center rounded-lg border border-border-strong/55 text-ink-secondary outline-none hover:bg-surface-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/** The moderator's guide: ordered questions, edited in place. Each must have words; the server bounds how many. */
function GuideEditor({ value, onChange, max }: { value: Question[]; onChange(next: Question[]): void; max: number }) {
  const move = (i: number, by: number) => {
    const next = [...value];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    onChange(next);
  };
  return (
    <fieldset className="min-w-0 space-y-2">
      <legend className="mb-1 text-[13px] font-medium text-ink">Moderator guide</legend>
      <p id="fg-guide-hint" className="max-w-prose text-xs text-ink-secondary">
        The moderator asks these in order, one round each. Participants answer the question and each other. 1 to {max} questions.
      </p>
      <ol className="space-y-2" aria-describedby="fg-guide-hint">
        {value.map((q, i) => (
          <li key={q.key} className="flex items-start gap-1.5">
            <span aria-hidden className="type-ledger mt-1.5 w-5 shrink-0 text-right text-[12.5px] text-ink-muted">
              {i + 1}
            </span>
            <input
              aria-label={`Question ${i + 1}`}
              value={q.text}
              maxLength={300}
              aria-invalid={!q.text.trim()}
              onChange={(e) => onChange(value.map((x) => (x.key === q.key ? { ...x, text: e.target.value } : x)))}
              className={cn(CONTROL, "h-8 min-w-0 flex-1")}
            />
            <IconButton label={`Move question ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>
              <ArrowUp aria-hidden className="size-3.5" />
            </IconButton>
            <IconButton label={`Move question ${i + 1} down`} disabled={i === value.length - 1} onClick={() => move(i, 1)}>
              <ArrowDown aria-hidden className="size-3.5" />
            </IconButton>
            <IconButton label={`Remove question ${i + 1}`} disabled={value.length <= 1} onClick={() => onChange(value.filter((x) => x.key !== q.key))}>
              <X aria-hidden className="size-3.5" />
            </IconButton>
          </li>
        ))}
      </ol>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={value.length >= max}
        onClick={() => onChange([...value, { key: Math.max(0, ...value.map((q) => q.key)) + 1, text: "" }])}
      >
        <Plus aria-hidden />
        Add a question
      </Button>
    </fieldset>
  );
}

export function FocusSetup({ defaults, loc, onStarted }: { defaults: Defaults; loc: Loc; onStarted(runId: string): void }) {
  const { campaign } = useCampaign();
  const quick = useRuns(campaign.id, "quick_read");
  const study = useRuns(campaign.id, "audience_study");
  const start = useStartFocusGroup(campaign.id);
  const block = useRunBlock();
  const { limits } = defaults;

  const panels = useMemo(
    () => [...(quick.data ?? []), ...(study.data ?? [])].filter((r) => isUsable(r.status)).sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [quick.data, study.data],
  );
  const [panelId, setPanelId] = useState<string | null>(null);
  const panel = panels.find((p) => p.id === panelId) ?? panels[0];
  const parts = useParticipants(campaign.id, panel?.id);
  const people = parts.data?.items ?? [];
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [count, setCount] = useState(6);
  const [guide, setGuide] = useState<Question[]>(() => defaults.guide.map((text, key) => ({ key, text })));
  const [seed, setSeed] = useState(42);

  if (quick.error || study.error) return <ErrorState error={quick.error ?? study.error} onRetry={() => { void quick.refetch(); void study.refetch(); }} />;
  if (quick.isPending || study.isPending) return <LoadingState label="Loading panels…" />;
  if (panels.length === 0) {
    return (
      <EmptyState
        title="No panel to talk with yet"
        description="A Focus Group draws its speakers from a finished Quick Read or Audience Study, and voices them from what they already said. Run one of those first."
        needs={[{ label: "A Quick Read or Audience Study that has finished", met: false }]}
        action={
          <Button variant="outline" onClick={() => loc.setTab("quick")}>
            Go to Quick Read
          </Button>
        }
      />
    );
  }

  const maxPick = Math.min(limits.focus_max_speakers, people.length || limits.focus_max_speakers);
  const picked = chosen.size;
  const pickError = picked > 0 && (picked < limits.focus_min_speakers || picked > limits.focus_max_speakers) ? `Choose ${limits.focus_min_speakers} to ${limits.focus_max_speakers} speakers, or none to let the server pick.` : null;
  const countError = picked === 0 && (!Number.isInteger(count) || count < limits.focus_min_speakers || count > maxPick) ? `Use a whole number from ${limits.focus_min_speakers} to ${maxPick}.` : null;
  const guideError = guide.some((q) => !q.text.trim()) ? "Every question needs words." : guide.length < 1 || guide.length > limits.focus_max_guide_questions ? `Use 1 to ${limits.focus_max_guide_questions} questions.` : null;
  const seedError = !Number.isInteger(seed) || seed < 0 ? "Use a whole number, 0 or more." : null;
  const invalid = Boolean(pickError || countError || guideError || seedError);

  function toggle(id: string) {
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (invalid || !panel) return;
    const body: FocusGroupCreate = {
      panel_run_id: panel.id,
      guide: guide.map((q) => q.text.trim()),
      seed,
      speakers: picked > 0 ? Math.max(limits.focus_min_speakers, picked) : count,
      participant_ids: picked > 0 ? people.filter((p) => chosen.has(p.id)).map((p) => p.id) : null,
    };
    start.mutate(body, { onSuccess: (run) => onStarted(run.run_id) });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <FieldBlock label="Panel" htmlFor="fg-panel" hint="The finished Quick Read or Audience Study whose participants will talk.">
        <NativeSelect
          id="fg-panel"
          value={panel?.id}
          aria-describedby="fg-panel-hint"
          onChange={(e) => {
            setPanelId(e.target.value);
            setChosen(new Set());
          }}
        >
          {panels.map((p) => (
            <option key={p.id} value={p.id}>
              {KIND_LABEL[p.kind as keyof typeof KIND_LABEL] ?? p.kind}, {p.region_codes.join(", ")}, {pluralise(p.participant_count, "participant")}
            </option>
          ))}
        </NativeSelect>
      </FieldBlock>

      <fieldset className="min-w-0 space-y-2" aria-describedby="fg-speakers-hint">
        <legend className="mb-1 text-[13px] font-medium text-ink">Speakers</legend>
        <p id="fg-speakers-hint" className="max-w-prose text-xs text-ink-secondary">
          Pick who speaks, or leave every box empty and the server picks a spread across the panel.
        </p>
        {parts.isPending ? (
          <LoadingState label="Loading the panel…" />
        ) : parts.error ? (
          <ErrorState error={parts.error} onRetry={() => void parts.refetch()} />
        ) : (
          <ul className="ledger-rules max-h-72 overflow-y-auto rounded-card border border-border bg-surface">
            {people.map((p) => {
              const on = chosen.has(p.id);
              return (
                <li key={p.id}>
                  <label className="flex cursor-pointer items-start gap-2.5 px-3 py-2 hover:bg-surface-muted has-[:focus-visible]:outline-2 has-[:focus-visible]:-outline-offset-2 has-[:focus-visible]:outline-ring">
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={!on && picked >= limits.focus_max_speakers}
                      onChange={() => toggle(p.id)}
                      className="mt-1 size-4 shrink-0 accent-[var(--primary)]"
                    />
                    <span className="min-w-0">
                      <span className="block text-[13.5px] font-medium text-ink">Participant {p.ordinal + 1}</span>
                      <span className="block text-[12.5px] text-ink-secondary">{p.persona}</span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
        {pickError && (
          <p role="alert" className="text-xs font-medium text-danger">
            {pickError}
          </p>
        )}
        <p className="type-meta" aria-live="polite">
          {picked > 0 ? `${picked} chosen.` : "None chosen: the server picks."}
        </p>
      </fieldset>

      {picked === 0 && (
        <FieldBlock label="Number of speakers" htmlFor="fg-count" error={countError} hint={`Seated when you choose none yourself, ${limits.focus_min_speakers} to ${maxPick}.`}>
          <input
            id="fg-count"
            type="number"
            inputMode="numeric"
            min={limits.focus_min_speakers}
            max={maxPick}
            value={Number.isNaN(count) ? "" : count}
            onChange={(e) => setCount(e.target.valueAsNumber)}
            aria-invalid={Boolean(countError)}
            aria-describedby="fg-count-hint"
            className={cn(CONTROL, "max-w-32")}
          />
        </FieldBlock>
      )}

      <div className="space-y-1.5">
        <GuideEditor value={guide} onChange={setGuide} max={limits.focus_max_guide_questions} />
        {guideError && (
          <p role="alert" className="text-xs font-medium text-danger">
            {guideError}
          </p>
        )}
      </div>

      <FieldBlock label="Seed" htmlFor="fg-seed" error={seedError} hint="The same panel and seed seat the same speakers. What they say can still differ between runs.">
        <input id="fg-seed" type="number" min={0} value={Number.isNaN(seed) ? "" : seed} onChange={(e) => setSeed(e.target.valueAsNumber)} aria-describedby="fg-seed-hint" className={cn(CONTROL, "max-w-32")} />
      </FieldBlock>

      <div className="space-y-3 border-t border-border pt-4">
        {start.error != null && <ErrorState error={start.error} />}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button type="submit" size="lg" disabled={start.isPending || invalid || Boolean(block)}>
            <Play aria-hidden />
            {start.isPending ? "Starting…" : "Start the Focus Group"}
          </Button>
          <p className="max-w-[60ch] text-[12.5px] text-ink-secondary">
            {block ?? "The transcript fills in as the group talks. You can put a question to the group while it runs."}
          </p>
        </div>
      </div>
    </form>
  );
}
