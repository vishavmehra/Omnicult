"use client";

import { useState, type FormEvent } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { Textarea } from "@/components/ui/textarea";
import { useCapabilities } from "@/hooks/use-capabilities";
import { useCampaign } from "@/features/workspaces/campaign-context";

import { useQuickRead, useRuns, useSamplingOptions, useStartQuickRead } from "./api";
import { FieldBlock, NativeSelect, RunPicker, CONTROL } from "./lab-parts";
import { pluralise } from "./labels";
import { QuickReadView } from "./quick-read-result";
import { NO_DIMENSIONS, RunButton, SamplingDimensions, SetupPanel, toPlan, type Dimensions } from "./sampling-form";
import type { QuickReadCreate, SamplingOptions } from "./types";
import type { useLabLocation } from "./use-lab-location";

type Loc = ReturnType<typeof useLabLocation>;

/** Why a run cannot start right now, from what the screen already knows. */
export function useRunBlock(): string | null {
  const { project } = useCampaign();
  const ready = useCapabilities();
  if (project.status === "archived") return "This brand is archived and read-only. Restore it to start runs.";
  if (project.mode === "live" && ready.data && ready.data.dependencies.llm_provider === "not_configured") {
    return "No language model provider is configured on the server, so live runs cannot start. Use a demo project, or configure a provider.";
  }
  return null;
}

/** The state or union territory the campaign names, when it names one; otherwise Tamil Nadu, the demo's first adaptation. */
function defaultRegion(options: SamplingOptions, marketNames: string[]) {
  const named = options.states.find((s) => marketNames.some((m) => m.toLowerCase() === s.name.toLowerCase()));
  return (named ?? options.states.find((s) => s.code === "IN-TN") ?? options.states[0])?.code ?? "";
}

function QuickReadForm({ options, onStarted }: { options: SamplingOptions; onStarted(runId: string): void }) {
  const { campaign, project } = useCampaign();
  const start = useStartQuickRead(campaign.id);
  const block = useRunBlock();
  const limits = options.limits;
  const min = limits.quick_read_min_participants ?? 6;
  const max = limits.quick_read_max_participants ?? 24;

  const [region, setRegion] = useState(() => defaultRegion(options, campaign.target_markets.map((m) => m.display_name)));
  const [versionId, setVersionId] = useState(campaign.current_version.id);
  const [message, setMessage] = useState("");
  const [size, setSize] = useState(Math.min(12, max));
  const [seed, setSeed] = useState(42);
  const [dims, setDims] = useState<Dimensions>(NO_DIMENSIONS);

  const sizeError = !Number.isInteger(size) || size < min || size > max ? `Use a whole number from ${min} to ${max}.` : null;
  const seedError = !Number.isInteger(seed) || seed < 0 ? "Use a whole number, 0 or more." : null;
  const regionName = options.states.find((s) => s.code === region)?.name ?? "the region";

  function submit(e: FormEvent) {
    e.preventDefault();
    if (sizeError || seedError || !region) return;
    const body: QuickReadCreate = {
      region_code: region,
      content_version_id: versionId === campaign.current_version.id ? null : versionId,
      intended_message: message.trim() || null,
      size,
      sampling: toPlan(dims),
      seed,
    };
    start.mutate(body, { onSuccess: (run) => onStarted(run.run_id) });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <FieldBlock label="Region" htmlFor="qr-region" hint="One state or union territory. Its stored claims ground the panel.">
          <NativeSelect id="qr-region" value={region} onChange={(e) => setRegion(e.target.value)} aria-describedby="qr-region-hint">
            {options.states.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </NativeSelect>
        </FieldBlock>
        <FieldBlock label="Panel size" htmlFor="qr-size" error={sizeError} hint={`Synthetic participants to generate, ${min} to ${max}. A panel size, not a number of people surveyed.`}>
          <input
            id="qr-size"
            type="number"
            inputMode="numeric"
            min={min}
            max={max}
            value={Number.isNaN(size) ? "" : size}
            onChange={(e) => setSize(e.target.valueAsNumber)}
            aria-invalid={Boolean(sizeError)}
            aria-describedby="qr-size-hint"
            className={CONTROL}
          />
        </FieldBlock>
      </div>

      {campaign.versions.length > 1 && (
        <FieldBlock label="Creative version" htmlFor="qr-version" hint="The copy the panel reacts to.">
          <NativeSelect id="qr-version" value={versionId} onChange={(e) => setVersionId(e.target.value)} aria-describedby="qr-version-hint">
            {campaign.versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number}
                {v.id === campaign.current_version.id ? " (current)" : ""}: {v.content.headline ?? v.content.body ?? "No copy"}
              </option>
            ))}
          </NativeSelect>
        </FieldBlock>
      )}

      <FieldBlock label="Intended message" htmlFor="qr-message" optional hint="What the creative should get across. Without it, message survival has nothing to be judged against.">
        <Textarea id="qr-message" value={message} maxLength={300} rows={2} onChange={(e) => setMessage(e.target.value)} aria-describedby="qr-message-hint" />
      </FieldBlock>

      <SamplingDimensions
        options={options}
        value={dims}
        onChange={setDims}
        languageHint={`None selected means the languages of ${regionName}.`}
      />

      <FieldBlock label="Seed" htmlFor="qr-seed" error={seedError} hint="The same seed and settings draw the same panel composition. Model answers can still differ between runs.">
        <input id="qr-seed" type="number" min={0} value={Number.isNaN(seed) ? "" : seed} onChange={(e) => setSeed(e.target.valueAsNumber)} aria-describedby="qr-seed-hint" className={`${CONTROL} max-w-32`} />
      </FieldBlock>

      <RunButton kind="quick_read" pending={start.isPending} mode={project.mode} blocked={block} error={start.error} />
    </form>
  );
}

export function QuickReadTab({ loc }: { loc: Loc }) {
  const { campaign } = useCampaign();
  const options = useSamplingOptions();
  const runs = useRuns(campaign.id, "quick_read");
  const selectedId = loc.runId ?? runs.data?.[0]?.id ?? null;
  const result = useQuickRead(campaign.id, selectedId);
  const [open, setOpen] = useState<boolean | null>(null);
  const setupOpen = open ?? (runs.isSuccess && runs.data.length === 0);
  const regionName = (code: string) => options.data?.states.find((s) => s.code === code)?.name ?? code;

  if (options.error) return <ErrorState error={options.error} onRetry={() => void options.refetch()} />;
  if (runs.error) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;
  if (runs.isPending || !options.data) return <LoadingState label="Loading Quick Reads…" />;

  return (
    <div className="space-y-5">
      <p className="max-w-[68ch] text-[14px] text-ink-secondary">
        A fast read of how a small synthetic panel reacts to the creative in one region: first reactions, whether the message survives, what confuses, and regional concerns. Every answer is simulated.
      </p>
      <SetupPanel title="New Quick Read" meta={runs.data.length ? undefined : "Start here"} open={setupOpen} onOpenChange={setOpen}>
        <QuickReadForm
          options={options.data}
          onStarted={(id) => {
            setOpen(false);
            loc.selectRun(id);
          }}
        />
      </SetupPanel>

      <RunPicker
        runs={runs.data}
        selectedId={selectedId}
        onSelect={loc.selectRun}
        regionName={regionName}
        describe={(r) => pluralise(r.participant_count, "synthetic participant")}
      />

      {selectedId && result.error && <ErrorState error={result.error} onRetry={() => void result.refetch()} />}
      {selectedId && !result.data && !result.error && <LoadingState label="Opening the Quick Read…" />}
      {result.data && (
        <QuickReadView
          result={result.data}
          onNewRun={() => setOpen(true)}
          onAsk={({ participant, question }) => loc.go({ tab: "ask", run: result.data.id, participant: participant ?? null, q: question ?? null })}
        />
      )}
    </div>
  );
}
