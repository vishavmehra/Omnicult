"use client";

import { Play, Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useCampaign } from "@/features/workspaces/campaign-context";

import { FieldBlock, ListPicker, NativeSelect, CONTROL } from "../lab-parts";
import { useRunBlock } from "../quick-read";
import { NO_DIMENSIONS, SamplingDimensions, toPlan, type Dimensions } from "../sampling-form";
import type { SamplingOptions } from "../types";
import type { LabSessionDefaults, MessageCheckCreate } from "./check-api";

const RUN_NOTE = {
  live: "Live run: calls the configured language model twice per batch (restating, then comparing). Usually finishes within a minute or two.",
  demo: "Demo project: runs on labelled fixtures. It is free, calls no model, and its results are not research.",
} as const;

/** The states the campaign names, when they are known states; otherwise Tamil Nadu, the demo's first adaptation. */
function defaultRegions(options: SamplingOptions, marketNames: string[], max: number) {
  const named = options.states.filter((s) => marketNames.some((m) => m.toLowerCase() === s.name.toLowerCase())).map((s) => s.code);
  const fallback = options.states.find((s) => s.code === "IN-TN") ?? options.states[0];
  return (named.length ? named : fallback ? [fallback.code] : []).slice(0, max);
}

export function MessageCheckForm({
  options,
  defaults,
  onStarted,
  start,
}: {
  options: SamplingOptions;
  defaults: LabSessionDefaults;
  onStarted(runId: string): void;
  start: { mutate(body: MessageCheckCreate, opts: { onSuccess(run: { run_id: string }): void }): void; isPending: boolean; error: unknown };
}) {
  const { campaign, project } = useCampaign();
  const block = useRunBlock();
  const limits = defaults.limits;
  const briefMessage = defaults.primary_message ?? "";

  const [regions, setRegions] = useState(() => defaultRegions(options, campaign.target_markets.map((m) => m.display_name), limits.message_check_max_regions));
  const [versions, setVersions] = useState<Record<string, string>>({});
  const [message, setMessage] = useState(briefMessage);
  const [points, setPoints] = useState<string[] | null>(null); // null: the person has not edited them, so the server's split is used
  const [size, setSize] = useState(Math.min(8, limits.message_check_max_per_region));
  const [seed, setSeed] = useState(42);
  const [dims, setDims] = useState<Dimensions>(NO_DIMENSIONS);
  const [submitted, setSubmitted] = useState(false);

  const messageText = message.trim();
  const fromBrief = Boolean(briefMessage) && messageText === briefMessage.trim();
  const shownPoints = points ?? (fromBrief ? defaults.key_points : []);
  const maxPoints = limits.message_check_max_key_points;

  const errors = {
    regions: regions.length < 1 ? "Choose at least one region." : null,
    message: !messageText ? (briefMessage ? "The message is empty. Write the message to check, or restore the brief's." : "State the message to check, or add a primary message to the campaign brief.") : null,
    points: points && (points.length < 1 || points.some((p) => p.trim().length < 2)) ? `Give 1 to ${maxPoints} key points, each at least two characters.` : null,
    size: !Number.isInteger(size) || size < limits.message_check_min_per_region || size > limits.message_check_max_per_region
      ? `Use a whole number from ${limits.message_check_min_per_region} to ${limits.message_check_max_per_region}.`
      : null,
    seed: !Number.isInteger(seed) || seed < 0 ? "Use a whole number, 0 or more." : null,
  };
  const invalid = Object.values(errors).some(Boolean);
  const show = (e: string | null) => (submitted ? e : null);
  const regionName = (code: string) => options.states.find((s) => s.code === code)?.name ?? code;

  function submit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (invalid) return;
    const body: MessageCheckCreate = {
      targets: regions.map((code) => ({ region_code: code, content_version_id: versions[code] && versions[code] !== campaign.current_version.id ? versions[code] : null })),
      intended_message: messageText,
      key_points: points ? points.map((p) => p.trim()) : null,
      size_per_region: size,
      sampling: toPlan(dims),
      seed,
    };
    start.mutate(body, { onSuccess: (run) => onStarted(run.run_id) });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <ListPicker
        id="mc-regions"
        label="Regions"
        required
        placeholder="Add a region"
        options={options.states.map((s) => ({ value: s.code, label: s.name }))}
        value={regions}
        onChange={setRegions}
        max={limits.message_check_max_regions}
        hint={`Up to ${limits.message_check_max_regions}. Each region gets its own panel and reads only that region's copy.`}
      />
      {show(errors.regions) && <p role="alert" className="text-xs font-medium text-danger">{errors.regions}</p>}

      {campaign.versions.length > 1 && regions.length > 0 && (
        <fieldset className="min-w-0 space-y-2">
          <legend className="mb-1 text-[13px] font-medium text-ink">Copy each region reads</legend>
          <ul className="space-y-2">
            {regions.map((code) => (
              <li key={code} className="grid items-center gap-x-3 gap-y-1 sm:grid-cols-[10rem_minmax(0,1fr)]">
                <label htmlFor={`mc-version-${code}`} className="text-[13px] text-ink-body">{regionName(code)}</label>
                <NativeSelect id={`mc-version-${code}`} value={versions[code] ?? campaign.current_version.id} onChange={(e) => setVersions((v) => ({ ...v, [code]: e.target.value }))}>
                  {campaign.versions.map((v) => (
                    <option key={v.id} value={v.id}>
                      v{v.version_number}
                      {v.id === campaign.current_version.id ? " (current)" : ""}: {v.content.headline ?? v.content.body ?? "No copy"}
                    </option>
                  ))}
                </NativeSelect>
              </li>
            ))}
          </ul>
          <p className="max-w-prose text-xs text-ink-secondary">Pick the version adapted for each region. The participants never see the intended message, only this copy.</p>
        </fieldset>
      )}

      <FieldBlock
        label="Intended message"
        htmlFor="mc-message"
        error={show(errors.message)}
        hint={
          fromBrief
            ? "From the campaign brief. Edit it for this check if you like; the brief is not changed."
            : briefMessage
              ? "Edited for this check. The brief's primary message is not changed."
              : "What the creative should get across. Add a primary message to the campaign brief to start from it."
        }
      >
        <Textarea id="mc-message" value={message} maxLength={300} rows={2} onChange={(e) => setMessage(e.target.value)} aria-describedby="mc-message-hint" aria-invalid={Boolean(show(errors.message))} />
      </FieldBlock>

      <fieldset className="min-w-0 space-y-2" aria-describedby="mc-points-hint">
        <legend className="mb-1 text-[13px] font-medium text-ink">Key points</legend>
        {points === null ? (
          <>
            {shownPoints.length > 0 ? (
              <ol className="type-ledger list-decimal space-y-0.5 pl-5 text-[13.5px] text-ink-body marker:text-ink-muted">
                {shownPoints.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ol>
            ) : (
              <p className="text-[13px] text-ink-secondary">The server splits your message at commas and &ldquo;and&rdquo; into key points when the run starts.</p>
            )}
            <Button type="button" size="sm" variant="outline" onClick={() => setPoints(shownPoints.length ? [...shownPoints] : [""])}>
              Edit key points
            </Button>
          </>
        ) : (
          <>
            <ul className="space-y-1.5">
              {points.map((p, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span className="type-ledger w-6 shrink-0 text-right text-[12px] text-ink-muted">K{i + 1}</span>
                  <input
                    type="text"
                    value={p}
                    maxLength={160}
                    aria-label={`Key point ${i + 1}`}
                    onChange={(e) => setPoints(points.map((x, j) => (j === i ? e.target.value : x)))}
                    className={CONTROL}
                  />
                  <Button type="button" size="icon-sm" variant="ghost" aria-label={`Remove key point ${i + 1}`} disabled={points.length === 1} onClick={() => setPoints(points.filter((_, j) => j !== i))}>
                    <X aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" size="sm" variant="outline" disabled={points.length >= maxPoints} onClick={() => setPoints([...points, ""])}>
                <Plus aria-hidden />
                Add a key point
              </Button>
              <button type="button" onClick={() => setPoints(null)} className="text-[12.5px] font-medium text-ink-secondary underline underline-offset-2 hover:text-ink">
                Use the default split
              </button>
            </div>
          </>
        )}
        <p id="mc-points-hint" className="max-w-prose text-xs text-ink-secondary">
          The parts of the message a reader must carry away, up to {maxPoints}. Each restatement is marked against every one.
        </p>
        {show(errors.points) && <p role="alert" className="text-xs font-medium text-danger">{errors.points}</p>}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <FieldBlock
          label="Participants per region"
          htmlFor="mc-size"
          error={show(errors.size)}
          hint={`${limits.message_check_min_per_region} to ${limits.message_check_max_per_region}. A panel size, not a number of people surveyed${regions.length > 1 ? `; ${size * regions.length} in total` : ""}.`}
        >
          <input
            id="mc-size"
            type="number"
            inputMode="numeric"
            min={limits.message_check_min_per_region}
            max={limits.message_check_max_per_region}
            value={Number.isNaN(size) ? "" : size}
            onChange={(e) => setSize(e.target.valueAsNumber)}
            aria-invalid={Boolean(show(errors.size))}
            aria-describedby="mc-size-hint"
            className={CONTROL}
          />
        </FieldBlock>
        <FieldBlock label="Seed" htmlFor="mc-seed" error={show(errors.seed)} hint="The same seed and settings draw the same panel. Model wording can still differ between runs.">
          <input id="mc-seed" type="number" min={0} value={Number.isNaN(seed) ? "" : seed} onChange={(e) => setSeed(e.target.valueAsNumber)} aria-describedby="mc-seed-hint" className={`${CONTROL} max-w-32`} />
        </FieldBlock>
      </div>

      <SamplingDimensions options={options} value={dims} onChange={setDims} languageHint="None selected means each region's own languages." />

      <div className="space-y-3 border-t border-border pt-4">
        {start.error != null && <ErrorState error={start.error} />}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button type="submit" size="lg" disabled={start.isPending || Boolean(block)}>
            <Play aria-hidden />
            {start.isPending ? "Starting…" : "Run Message Check"}
          </Button>
          <p className="max-w-[60ch] text-[12.5px] text-ink-secondary">{block ?? RUN_NOTE[project.mode]}</p>
        </div>
      </div>
    </form>
  );
}
