"use client";

import { ExternalLink, OctagonAlert, ShieldAlert } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { Tag } from "@/components/evidence/badges";
import { LimitationList } from "@/components/evidence/limitation-list";
import { ErrorState, LoadingState } from "@/components/states";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { cn } from "@/lib/utils";

import { useAdCodeIndex, useRiskCheck, useRuns, useSamplingOptions, useStartRiskCheck, useStudioVersion, useStudioVersions, useXRayCreatives, useXRayScenes } from "./api";
import { FindingCard } from "./finding-card";
import { CONTROL, Disclosure, FieldBlock, NativeSelect, Panel, RunBanner, RunPicker } from "./lab-parts";
import { FINDING_STATUS, pluralise, sortFindings } from "./labels";
import { useRunBlock } from "./quick-read";
import { buildElements, buildScenes } from "./risk-input";
import { RunButton, SetupPanel } from "./sampling-form";
import { GroundingPanel, Provenance } from "./summary-parts";
import type { AdCodeEntry, FindingStatus, RiskCheckCreate, RiskCheckResult, SamplingOptions } from "./types";
import { isActive, isUsable } from "./types";
import type { useLabLocation } from "./use-lab-location";

type Loc = ReturnType<typeof useLabLocation>;

function RiskForm({ options, onStarted }: { options: SamplingOptions; onStarted(runId: string): void }) {
  const { campaign, project } = useCampaign();
  const start = useStartRiskCheck(campaign.id);
  const block = useRunBlock();
  const versions = useStudioVersions(campaign.id);
  const creatives = useXRayCreatives(campaign.id);

  const [region, setRegion] = useState(() => {
    const named = options.states.find((s) => campaign.target_markets.some((m) => m.display_name.toLowerCase() === s.name.toLowerCase()));
    return named?.code ?? "IN-TN";
  });
  const [source, setSource] = useState<"copy" | "studio">("copy");
  const [contentVersionId, setContentVersionId] = useState(campaign.current_version.id);
  const [studioId, setStudioId] = useState<string>("");
  const [creativeId, setCreativeId] = useState<string>("");
  const [category, setCategory] = useState("");

  const studioVersions = versions.data ?? [];
  const chosenStudio = source === "studio" ? (studioId || studioVersions.at(-1)?.id || "") : "";
  const studio = useStudioVersion(campaign.id, chosenStudio || null);
  const scenesQuery = useXRayScenes(source === "studio" && creativeId ? creativeId : null);
  const built = useMemo(() => (studio.data ? buildElements(studio.data.elements) : null), [studio.data]);
  const sceneInfo = useMemo(() => (built ? buildScenes(built.elements, scenesQuery.data) : null), [built, scenesQuery.data]);

  const blocked = block ?? (source === "studio" && !built ? "Choose a Creative Studio version with elements to check." : null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (blocked) return;
    const body: RiskCheckCreate = {
      region_code: region,
      product_category: category.trim() || null,
      ...(source === "studio" && built && sceneInfo
        ? { elements: built.elements, scenes: sceneInfo.scenes, version_ref: chosenStudio }
        : { scenes: [], content_version_id: contentVersionId === campaign.current_version.id ? null : contentVersionId }),
    };
    start.mutate(body, { onSuccess: (run) => onStarted(run.run_id) });
  }

  const copy = campaign.versions.find((v) => v.id === contentVersionId)?.content ?? campaign.current_version.content;

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <FieldBlock label="Region" htmlFor="rc-region" hint="The region whose claims and sensitivities the creative is read against.">
          <NativeSelect id="rc-region" value={region} onChange={(e) => setRegion(e.target.value)} aria-describedby="rc-region-hint">
            {options.states.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </NativeSelect>
        </FieldBlock>
        <FieldBlock label="Product category" htmlFor="rc-category" optional hint="For example packaged sweets. Helps pick the ASCI clauses that apply.">
          <input id="rc-category" value={category} maxLength={80} onChange={(e) => setCategory(e.target.value)} aria-describedby="rc-category-hint" className={CONTROL} />
        </FieldBlock>
      </div>

      <FieldBlock label="What to check" htmlFor="rc-source" hint="Campaign copy is always available. A Creative Studio version also brings its scenes, boxes and locked elements, so findings can point at them.">
        <NativeSelect id="rc-source" value={source} onChange={(e) => setSource(e.target.value as "copy" | "studio")} aria-describedby="rc-source-hint">
          <option value="copy">Campaign copy: headline, body and call to action</option>
          <option value="studio" disabled={studioVersions.length === 0}>
            Creative Studio version{studioVersions.length === 0 ? " (none yet)" : ""}
          </option>
        </NativeSelect>
      </FieldBlock>

      {source === "copy" ? (
        <>
          {campaign.versions.length > 1 && (
            <FieldBlock label="Copy version" htmlFor="rc-copy-version">
              <NativeSelect id="rc-copy-version" value={contentVersionId} onChange={(e) => setContentVersionId(e.target.value)}>
                {campaign.versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    v{v.version_number}
                    {v.id === campaign.current_version.id ? " (current)" : ""}: {v.content.headline ?? v.content.body ?? "No copy"}
                  </option>
                ))}
              </NativeSelect>
            </FieldBlock>
          )}
          <dl className="type-ledger space-y-1 rounded-md border border-border bg-surface-muted/50 px-3 py-2 text-[13px]">
            {([["Headline", copy.headline], ["Body", copy.body], ["Call to action", copy.call_to_action]] as const).map(([k, v]) => (
              <div key={k} className="grid gap-x-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
                <dt className="text-ink-muted">{k}</dt>
                <dd className="text-ink-body">{v ?? <span className="text-ink-muted">Empty</span>}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : (
        <div className="space-y-4">
          <FieldBlock label="Creative Studio version" htmlFor="rc-studio">
            <NativeSelect id="rc-studio" value={chosenStudio} onChange={(e) => setStudioId(e.target.value)}>
              {studioVersions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                  {v.region_code ? ` · ${v.region_code}` : ""} · {pluralise(v.element_count, "element")}
                </option>
              ))}
            </NativeSelect>
          </FieldBlock>
          {studio.isPending && chosenStudio && <LoadingState label="Loading the version's elements…" />}
          {studio.error && <ErrorState error={studio.error} onRetry={() => void studio.refetch()} />}
          {built && sceneInfo && (
            <div className="space-y-2">
              <p className="type-meta">
                {pluralise(built.elements.length, "element")} will be checked
                {built.omitted > 0 && `; ${built.omitted} more are left out because a check covers at most 60 (copy is kept first)`}. {pluralise(sceneInfo.scenes.length, "scene")} referenced.
              </p>
              <ul className="ledger-rules type-ledger max-h-56 overflow-y-auto rounded-md border border-border text-[13px]">
                {built.elements.map((el) => (
                  <li key={el.id} className="grid gap-x-3 px-3 py-1.5 sm:grid-cols-[7rem_minmax(0,1fr)]">
                    <span className="text-ink-secondary">
                      {el.kind}
                      {el.locked && <span className="text-ink-muted"> · locked</span>}
                    </span>
                    <span lang={el.language ?? undefined} className="min-w-0 truncate text-ink">
                      {typeof el.value === "string" ? el.value : JSON.stringify(el.value)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(creatives.data?.length ?? 0) > 0 && (
            <FieldBlock label="Scene timing from an X-Ray" htmlFor="rc-xray" optional hint="Adds start and end times to findings. A scene gets a time range only when its id matches; the rest stay untimed.">
              <NativeSelect id="rc-xray" value={creativeId} onChange={(e) => setCreativeId(e.target.value)} aria-describedby="rc-xray-hint">
                <option value="">No timing</option>
                {creatives.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label} · {pluralise(c.scene_count, "scene")}
                  </option>
                ))}
              </NativeSelect>
              {sceneInfo && creativeId && !scenesQuery.isPending && (
                <p className="type-meta mt-1">{sceneInfo.timed} of {sceneInfo.scenes.length} scenes matched an X-Ray scene and carry a time range.</p>
              )}
            </FieldBlock>
          )}
        </div>
      )}

      <RunButton kind="risk_check" pending={start.isPending} mode={project.mode} blocked={blocked} error={start.error} />
    </form>
  );
}

function RiskView({ result, adCodes, onNewRun }: { result: RiskCheckResult; adCodes: Map<string, AdCodeEntry>; onNewRun(): void }) {
  const { campaign } = useCampaign();
  const index = useAdCodeIndex();
  const [filter, setFilter] = useState<FindingStatus | "all">("all");
  const usable = isUsable(result.status);
  const { counts, dropped } = result;

  const sorted = useMemo(() => sortFindings(result.findings), [result.findings]);
  const shown = filter === "all" ? sorted : sorted.filter((f) => f.status === filter);
  const grounded = result.findings.filter((f) => f.claim_ids.length > 0).length;

  const limitations = [
    dropped.total > 0
      ? `The server dropped ${pluralise(dropped.total, "model finding")} before saving: ${dropped.unverified_quote} whose quoted text is not in the element, ${dropped.unknown_element} that named an element that does not exist, and ${dropped.duplicate} ${dropped.duplicate === 1 ? "duplicate" : "duplicates"} of another finding. Dropped findings are neither shown nor counted, so this list holds only what code could verify.`
      : "A model finding that code cannot verify (quoted text that is not in the element, an unknown element, a duplicate) is dropped before it is saved, and is neither shown nor counted. None was dropped in this run.",
    ...result.limitations,
  ];

  return (
    <div className="space-y-5">
      <RunBanner run={result} label="Risk Check" onNewRun={onNewRun} />

      <div className="flex items-start gap-3 rounded-md border border-warning/40 bg-warning-soft/60 px-3.5 py-3">
        <ShieldAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="space-y-1 text-[13px]">
          <p className="flex flex-wrap items-center gap-2 font-medium text-ink">
            A screening aid, not clearance
            <Tag className="border-warning/45 bg-surface text-warning">Human review required</Tag>
          </p>
          <p className="max-w-[68ch] text-ink-body">{result.disclaimer}</p>
        </div>
      </div>

      {usable && (
        <>
          <Panel id="rc-summary" title="Findings" meta={`${result.region.name} · rules ${result.rules_version} · ASCI index ${result.ad_code_index_version}`}>
            <div className="space-y-3">
              <p className="max-w-[68ch] text-[14.5px] leading-snug text-ink">
                {counts.total === 0
                  ? "No findings were saved. That is not clearance: a creative with no findings has not been cleared, and a person must still review it."
                  : `${pluralise(counts.total, "finding")}: ${(["high", "medium", "low"] as const).filter((s) => counts.by_severity[s]).map((s) => `${counts.by_severity[s]} ${s}`).join(", ")}. `}
                {counts.total > 0 && (
                  counts.blocking_go > 0 ? (
                    <span className="inline-flex items-center gap-1 font-semibold text-danger">
                      <OctagonAlert aria-hidden className="size-4" />
                      {pluralise(counts.blocking_go, "finding")} {counts.blocking_go === 1 ? "blocks" : "block"} Go while open or accepted.
                    </span>
                  ) : (
                    "None blocks Go right now."
                  )
                )}
              </p>
              {counts.total > 0 && (
                <div role="group" aria-label="Filter findings by status" className="flex flex-wrap gap-1.5">
                  {(["all", "open", "accepted", "dismissed", "fixed"] as const).map((k) => {
                    const n = k === "all" ? counts.total : counts.by_status[k] ?? 0;
                    const on = filter === k;
                    return (
                      <button
                        key={k}
                        type="button"
                        aria-pressed={on}
                        onClick={() => setFilter(k)}
                        className={cn(
                          "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[13px] outline-none transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                          on ? "border-ink-secondary bg-surface-raised font-medium text-ink shadow-clay" : "border-border-strong/55 text-ink-secondary hover:bg-surface-muted",
                        )}
                      >
                        {k === "all" ? "All" : FINDING_STATUS[k].label}
                        <span className="type-ledger text-ink-muted">{n}</span>
                      </button>
                    );
                  })}
                </div>
              )}
              <p className="type-meta">
                Sorted by computed severity, then findings that block Go first. {grounded} of {counts.total} {counts.total === 1 ? "finding rests" : "findings rest"} on a stored region claim.
              </p>
            </div>
          </Panel>

          {shown.length === 0 && counts.total > 0 && <p className="rounded-md border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-muted">No finding has this status.</p>}
          <div className="space-y-4">
            {shown.map((f) => (
              <FindingCard key={f.id} finding={f} elements={result.elements} claims={result.grounding.claims} adCodes={adCodes} campaignId={campaign.id} runId={result.id} />
            ))}
          </div>

          <Panel id="rc-checked" title="What was checked" meta={`${pluralise(result.elements.length, "element")}, ${pluralise(result.scenes.length, "scene")}`}>
            <ul className="ledger-rules type-ledger text-[13px]">
              {result.elements.map((e) => (
                <li key={e.id} className="grid gap-x-3 py-1.5 sm:grid-cols-[7rem_9rem_minmax(0,1fr)]">
                  <span className="text-ink-secondary">{e.kind}</span>
                  <span className="font-mono text-[11.5px] text-ink-muted">{e.id}{e.scene_id ? ` · ${e.scene_id}` : ""}</span>
                  <span lang={e.language ?? undefined} className="min-w-0 break-words text-ink">{typeof e.value === "string" ? e.value : JSON.stringify(e.value)}</span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel id="rc-grounding" title="Region claims supplied" meta="Grounding">
            <GroundingPanel grounding={result.grounding} />
          </Panel>

          {index.data && (
            <Panel id="rc-asci" title="ASCI reference" meta={`${index.data.version} · retrieved ${index.data.retrieved_at}`}>
              <div className="space-y-2 text-[13px] text-ink-body">
                <p>
                  Clauses are exact excerpts of {index.data.publisher}&apos;s published Code, with their PDF page: {index.data.source.title}, {index.data.source.edition}.{" "}
                  <a href={index.data.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-rose underline-offset-2 hover:underline">
                    Open the document
                    <ExternalLink aria-hidden className="size-3" />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                </p>
                <ul className="list-disc space-y-0.5 pl-5 text-ink-secondary marker:text-ink-muted">
                  {index.data.limitations.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              </div>
            </Panel>
          )}
        </>
      )}

      <LimitationList items={usable ? limitations : result.limitations} />
      {usable && <Provenance meta={result.run_metadata} extra={[{ label: "Severity rules", value: result.rules_version }, { label: "ASCI index", value: result.ad_code_index_version }]} />}
      <Disclosure summary="What severity and Blocks Go mean">
        <p className="max-w-[68ch] text-[13px] leading-relaxed text-ink-body">
          Severity and the Blocks Go flag are computed by versioned code, never by a model. A category sets the base level; a cited ASCI clause that fits, a backing observed or calculated region claim, and absolute or comparative wording in a verified quote each raise it one step; without a clause or claim a model finding stays at medium or below. Blocks Go means high severity in a category that can block a Go verdict. It counts while the finding is open or accepted, and stops counting when a person resolves it or dismisses it with a reason. A person&apos;s decision never changes the severity.
        </p>
      </Disclosure>
    </div>
  );
}

export function RiskCheckTab({ loc }: { loc: Loc }) {
  const { campaign } = useCampaign();
  const options = useSamplingOptions();
  const runs = useRuns(campaign.id, "risk_check");
  const adIndex = useAdCodeIndex();
  const selectedId = loc.runId ?? runs.data?.[0]?.id ?? null;
  const result = useRiskCheck(campaign.id, selectedId);
  const [open, setOpen] = useState<boolean | null>(null);
  const setupOpen = open ?? (runs.isSuccess && runs.data.length === 0);
  const adCodes = useMemo(() => new Map((adIndex.data?.entries ?? []).map((e) => [e.id, e])), [adIndex.data]);
  const regionName = (code: string) => options.data?.states.find((s) => s.code === code)?.name ?? code;

  if (options.error) return <ErrorState error={options.error} onRetry={() => void options.refetch()} />;
  if (runs.error) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;
  if (runs.isPending || !options.data) return <LoadingState label="Loading Risk Checks…" />;

  return (
    <div className="space-y-5">
      <p className="max-w-[68ch] text-[14px] text-ink-secondary">
        Screens the creative against the region&apos;s claims and the ASCI advertising code. Each finding points at an element, scene and time, quotes the exact text, and cites the clause. A person decides what to do with it.
      </p>
      <SetupPanel title="New Risk Check" meta={runs.data.length ? undefined : "Start here"} open={setupOpen} onOpenChange={setOpen}>
        <RiskForm
          options={options.data}
          onStarted={(id) => {
            setOpen(false);
            loc.selectRun(id);
          }}
        />
      </SetupPanel>
      <RunPicker runs={runs.data} selectedId={selectedId} onSelect={loc.selectRun} regionName={regionName} describe={(r) => (r.status === "failed" ? "no findings saved" : isActive(r.status) ? "in progress" : pluralise(r.finding_count, "finding"))} />
      {selectedId && result.error && <ErrorState error={result.error} onRetry={() => void result.refetch()} />}
      {selectedId && !result.data && !result.error && <LoadingState label="Opening the Risk Check…" />}
      {result.data && <RiskView result={result.data} adCodes={adCodes} onNewRun={() => setOpen(true)} />}
    </div>
  );
}
