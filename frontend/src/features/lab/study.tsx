"use client";

import { useState, type FormEvent } from "react";

import { Tag } from "@/components/evidence/badges";
import { LimitationList } from "@/components/evidence/limitation-list";
import { ErrorState, LoadingState } from "@/components/states";
import { Textarea } from "@/components/ui/textarea";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { MessageSquareText } from "lucide-react";

import { useAudienceStudy, useRuns, useSamplingOptions, useStartStudy } from "./api";
import { CONTROL, DistributionLedger, FieldBlock, ListPicker, NativeSelect, Panel, RunBanner, RunPicker } from "./lab-parts";
import { CITY_TIER_LABEL, DIMENSION_LABEL, pluralise } from "./labels";
import { StudyParticipants } from "./participants";
import { NO_DIMENSIONS, RunButton, SamplingDimensions, SetupPanel, toPlan, type Dimensions } from "./sampling-form";
import { useRunBlock } from "./quick-read";
import { GroundingPanel, Provenance, SegmentTable } from "./summary-parts";
import type { AudienceStudyCreate, AudienceStudyResult, SamplingOptions, ThemeCount } from "./types";
import { isUsable } from "./types";
import type { useLabLocation } from "./use-lab-location";

type Loc = ReturnType<typeof useLabLocation>;

function StudyForm({ options, onStarted }: { options: SamplingOptions; onStarted(runId: string): void }) {
  const { campaign, project } = useCampaign();
  const start = useStartStudy(campaign.id);
  const block = useRunBlock();
  const min = options.limits.audience_study_min_participants ?? 20;
  const max = options.limits.audience_study_max_participants ?? 60;

  const [states, setStates] = useState<string[]>(() => {
    const named = options.states.find((s) => campaign.target_markets.some((m) => m.display_name.toLowerCase() === s.name.toLowerCase()));
    return [named?.code ?? "IN-TN"];
  });
  const [versionId, setVersionId] = useState(campaign.current_version.id);
  const [message, setMessage] = useState("");
  const [size, setSize] = useState(Math.min(30, max));
  const [depth, setDepth] = useState<"brief" | "standard">("standard");
  const [seed, setSeed] = useState(42);
  const [dims, setDims] = useState<Dimensions>(NO_DIMENSIONS);

  const sizeError = !Number.isInteger(size) || size < min || size > max ? `Use a whole number from ${min} to ${max}.` : null;
  const stateError = states.length === 0 ? "Choose at least one state or union territory." : null;
  const seedError = !Number.isInteger(seed) || seed < 0 ? "Use a whole number, 0 or more." : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (sizeError || stateError || seedError) return;
    const body: AudienceStudyCreate = {
      sampling: toPlan(dims, states),
      content_version_id: versionId === campaign.current_version.id ? null : versionId,
      intended_message: message.trim() || null,
      size,
      interview_depth: depth,
      seed,
    };
    start.mutate(body, { onSuccess: (run) => onStarted(run.run_id) });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <ListPicker
        id="st-states"
        label="States and union territories"
        required
        max={5}
        placeholder="Add a state or union territory"
        options={options.states.map((s) => ({ value: s.code, label: s.name }))}
        value={states}
        onChange={setStates}
        hint={stateError ?? "Up to five. Participants are spread across them."}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <FieldBlock label="Panel size" htmlFor="st-size" error={sizeError} hint={`Synthetic participants, ${min} to ${max} on this server. Each is interviewed once. A panel size, not a number of people surveyed.`}>
          <input id="st-size" type="number" inputMode="numeric" min={min} max={max} value={Number.isNaN(size) ? "" : size} onChange={(e) => setSize(e.target.valueAsNumber)} aria-invalid={Boolean(sizeError)} aria-describedby="st-size-hint" className={CONTROL} />
        </FieldBlock>
        <FieldBlock label="Interview depth" htmlFor="st-depth" hint="Standard adds one follow-up question to each interview.">
          <NativeSelect id="st-depth" value={depth} onChange={(e) => setDepth(e.target.value as "brief" | "standard")} aria-describedby="st-depth-hint">
            <option value="brief">Brief: the eight core questions</option>
            <option value="standard">Standard: core questions and one follow-up</option>
          </NativeSelect>
        </FieldBlock>
      </div>

      {campaign.versions.length > 1 && (
        <FieldBlock label="Creative version" htmlFor="st-version" hint="The copy the panel is interviewed about.">
          <NativeSelect id="st-version" value={versionId} onChange={(e) => setVersionId(e.target.value)} aria-describedby="st-version-hint">
            {campaign.versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number}
                {v.id === campaign.current_version.id ? " (current)" : ""}: {v.content.headline ?? v.content.body ?? "No copy"}
              </option>
            ))}
          </NativeSelect>
        </FieldBlock>
      )}

      <FieldBlock label="Intended message" htmlFor="st-message" optional hint="What the creative should get across, so comprehension can be judged against it.">
        <Textarea id="st-message" value={message} maxLength={300} rows={2} onChange={(e) => setMessage(e.target.value)} aria-describedby="st-message-hint" />
      </FieldBlock>

      <SamplingDimensions options={options} value={dims} onChange={setDims} languageHint="None selected means the languages of the chosen states." />

      <FieldBlock label="Seed" htmlFor="st-seed" error={seedError} hint="The same seed and settings draw the same panel composition. Model answers can still differ.">
        <input id="st-seed" type="number" min={0} value={Number.isNaN(seed) ? "" : seed} onChange={(e) => setSeed(e.target.valueAsNumber)} aria-describedby="st-seed-hint" className={`${CONTROL} max-w-32`} />
      </FieldBlock>

      <RunButton kind="audience_study" pending={start.isPending} mode={project.mode} blocked={block} error={start.error} />
    </form>
  );
}

function ThemeList({ items, denominator, empty }: { items: ThemeCount[]; denominator: number; empty: string }) {
  if (!items.length) return <p className="text-[13px] text-ink-muted">{empty}</p>;
  return (
    <ul className="ledger-rules">
      {items.map((t) => (
        <li key={t.label} className="flex items-baseline justify-between gap-4 py-1.5 text-[13.5px]">
          <span className="min-w-0 text-ink">{t.label}</span>
          <span className="type-ledger shrink-0 text-ink-body">
            {t.count} <span className="text-ink-muted">of {denominator}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function InterpretationList({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-[13px] text-ink-muted">{empty}</p>;
  return (
    <ul className="space-y-1.5 text-[13.5px] text-ink-body">
      {items.map((t, i) => (
        <li key={i} className="flex flex-wrap items-start gap-x-2 gap-y-1">
          <span className="min-w-0 flex-1">{t}</span>
        </li>
      ))}
    </ul>
  );
}

function StudyView({ result, onAsk, onNewRun }: { result: AudienceStudyResult; onAsk(participant: string): void; onNewRun(): void }) {
  const { summary, panel } = result;
  const usable = isUsable(result.status);
  const n = summary?.overall.denominator ?? 0;
  const groups = summary
    ? (["states", "languages", "city_tiers", "age_bands"] as const)
        .map((d) => ({
          title: DIMENSION_LABEL[d],
          rows: summary.by_dimension
            .filter((s) => s.dimension === d)
            .map((s) => ({ value: s.value, label: d === "city_tiers" ? (CITY_TIER_LABEL[s.value] ?? s.label) : s.label, counts: s.distribution.counts as Record<string, number>, total: s.participants })),
        }))
        .filter((g) => g.rows.length > 0)
    : [];

  return (
    <div className="space-y-5">
      <RunBanner run={result} label="Audience Study" onNewRun={onNewRun} />
      {usable && (
        <>
          <Panel id="st-panel" title="The panel" meta={`${pluralise(panel.generated_size, "synthetic participant")} interviewed${panel.requested_size !== panel.generated_size ? `, ${panel.requested_size} requested` : ""}`}>
            <dl className="type-ledger grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-[8rem_minmax(0,1fr)]">
              <dt className="text-ink-muted">States</dt>
              <dd className="text-ink-body">{panel.states.map((s) => `${s.name} ${panel.marginal_counts.states?.[s.code] ?? 0}`).join(" · ")}</dd>
              <dt className="text-ink-muted">Interview</dt>
              <dd className="text-ink-body">{result.interview_depth === "standard" ? "Core questions and one follow-up" : "Core questions"}</dd>
              <dt className="text-ink-muted">Creative</dt>
              <dd className="min-w-0 text-ink-body">{[result.creative.headline, result.creative.body, result.creative.call_to_action].filter(Boolean).join(" / ") || "No copy"}</dd>
              <dt className="text-ink-muted">Intended message</dt>
              <dd className="text-ink-body">{result.intended_message ?? "None given"}</dd>
            </dl>
            <p className="mt-2 max-w-[68ch] text-xs text-ink-secondary">{panel.method}</p>
          </Panel>

          {summary ? (
            <>
              <Panel id="st-overall" title="Reactions" meta="Counts of synthetic participants">
                <DistributionLedger dist={summary.overall} noun="synthetic participants interviewed" />
              </Panel>

              {groups.length > 0 && (
                <Panel id="st-segments" title="Segment differences" meta="Counted from the stored interviews">
                  <SegmentTable groups={groups} />
                  <p className="mt-2 max-w-[68ch] text-xs text-ink-secondary">
                    Tallies per dimension value. Small slices are noisy, so read them as questions to ask rather than market segments. They say nothing about real people.
                  </p>
                </Panel>
              )}

              <Panel id="st-themes" title="Themes, concerns and misreadings" meta="Tallied from the interviews">
                <p className="type-meta mb-1">Themes</p>
                <ThemeList items={summary.themes} denominator={n} empty="No theme was repeated." />
                <p className="type-meta mt-4 mb-1">Concerns</p>
                <ThemeList items={summary.concerns} denominator={n} empty="No concern was raised." />
                <p className="type-meta mt-4 mb-1">Misreadings</p>
                <ThemeList items={summary.misunderstandings} denominator={n} empty="No misreading was reported." />
              </Panel>

              <Panel id="st-differences" title="Where groups differ and what is missing">
                <div className="space-y-4">
                  <div>
                    <p className="type-meta mb-1.5 flex items-center gap-2">
                      Differences between groups
                      <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title="A model's reading of the tallies. Not a finding about real people.">
                        <MessageSquareText aria-hidden />
                        Model interpretation
                      </Tag>
                    </p>
                    <InterpretationList items={summary.group_differences} empty="The tallies showed no difference worth naming." />
                  </div>
                  <div>
                    <p className="type-meta mb-1.5">Evidence gaps</p>
                    <InterpretationList items={summary.evidence_gaps} empty="No gap was named." />
                  </div>
                  <div>
                    <p className="type-meta mb-1.5">Suggested next steps (check with real people)</p>
                    <InterpretationList items={summary.next_actions} empty="None suggested." />
                  </div>
                  <p className="text-xs text-ink-secondary">All participants share one model&apos;s biases. Agreement between them is not confirmation, and a difference between them is a prompt to ask real people.</p>
                </div>
              </Panel>
            </>
          ) : (
            <p className="rounded-md border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-secondary">
              No summary was produced for this run. The interviews that were saved are listed below, and the limitations say why.
            </p>
          )}

          <Panel id="st-grounding" title="Grounding" meta="Claim-supported versus interpretation">
            <GroundingPanel grounding={result.grounding} />
          </Panel>

          <Panel id="st-participants" title="Participants and interviews" meta={`${result.participants.length} synthetic`}>
            <StudyParticipants participants={result.participants} onAsk={onAsk} />
          </Panel>
        </>
      )}
      <LimitationList items={result.limitations} />
      {usable && <Provenance meta={result.run_metadata} extra={[{ label: "Sampling version", value: panel.sampling_version }, { label: "Interview depth", value: result.interview_depth }]} />}
    </div>
  );
}

export function StudyTab({ loc }: { loc: Loc }) {
  const { campaign } = useCampaign();
  const options = useSamplingOptions();
  const runs = useRuns(campaign.id, "audience_study");
  const selectedId = loc.runId ?? runs.data?.[0]?.id ?? null;
  const result = useAudienceStudy(campaign.id, selectedId);
  const [open, setOpen] = useState<boolean | null>(null);
  const setupOpen = open ?? (runs.isSuccess && runs.data.length === 0);
  const regionName = (code: string) => options.data?.states.find((s) => s.code === code)?.name ?? code;

  if (options.error) return <ErrorState error={options.error} onRetry={() => void options.refetch()} />;
  if (runs.error) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;
  if (runs.isPending || !options.data) return <LoadingState label="Loading Audience Studies…" />;

  return (
    <div className="space-y-5">
      <p className="max-w-[68ch] text-[14px] text-ink-secondary">
        The deeper run: a bounded synthetic panel sampled by state, language, city tier and age band, with an interview for each participant. It rehearses questions to put to real people; it does not measure them.
      </p>
      <SetupPanel title="New Audience Study" meta={runs.data.length ? undefined : "Start here"} open={setupOpen} onOpenChange={setOpen}>
        <StudyForm
          options={options.data}
          onStarted={(id) => {
            setOpen(false);
            loc.selectRun(id);
          }}
        />
      </SetupPanel>
      <RunPicker runs={runs.data} selectedId={selectedId} onSelect={loc.selectRun} regionName={regionName} describe={(r) => pluralise(r.participant_count, "synthetic participant")} />
      {selectedId && result.error && <ErrorState error={result.error} onRetry={() => void result.refetch()} />}
      {selectedId && !result.data && !result.error && <LoadingState label="Opening the Audience Study…" />}
      {result.data && <StudyView result={result.data} onNewRun={() => setOpen(true)} onAsk={(id) => loc.go({ tab: "ask", run: result.data.id, participant: id, q: null })} />}
    </div>
  );
}
