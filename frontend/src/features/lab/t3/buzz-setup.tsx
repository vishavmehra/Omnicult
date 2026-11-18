"use client";

import { Play } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useCampaign } from "@/features/workspaces/campaign-context";

import { CONTROL, FieldBlock, ListPicker, NativeSelect } from "../lab-parts";
import { useRunBlock } from "../quick-read";
import { NO_DIMENSIONS, SamplingDimensions, toPlan, type Dimensions } from "../sampling-form";
import type { SamplingOptions } from "../types";
import { useStartBuzz, type BuzzCreate, type SessionDefaults } from "./buzz-api";

const MIN_PER_STATE = 3;
const MAX_STATES = 5;

/** The campaign's own target states when they are on the list, else Tamil Nadu (the demo's first adaptation). */
function defaultStates(options: SamplingOptions, marketNames: string[]): string[] {
  const named = options.states.filter((s) => marketNames.some((m) => m.toLowerCase() === s.name.toLowerCase())).map((s) => s.code);
  if (named.length) return named.slice(0, MAX_STATES);
  return [options.states.find((s) => s.code === "IN-TN")?.code ?? options.states[0]?.code].filter(Boolean) as string[];
}

const int = (n: number) => Number.isInteger(n);

export function BuzzForm({ options, defaults, onStarted }: { options: SamplingOptions; defaults: SessionDefaults; onStarted(runId: string): void }) {
  const { campaign, project } = useCampaign();
  const start = useStartBuzz(campaign.id);
  const block = useRunBlock();
  const { buzz_min_participants: minSize, buzz_max_participants: maxSize, buzz_max_rounds: maxRounds } = defaults.limits;

  const [states, setStates] = useState(() => defaultStates(options, campaign.target_markets.map((m) => m.display_name)));
  const [dims, setDims] = useState<Dimensions>(NO_DIMENSIONS);
  const [size, setSize] = useState(Math.min(24, maxSize));
  const [platform, setPlatform] = useState(defaults.platforms[0]?.value ?? "instagram");
  const [rounds, setRounds] = useState(Math.min(3, maxRounds));
  const [exposure, setExposure] = useState(25);
  const [degree, setDegree] = useState(4);
  const [versionId, setVersionId] = useState(campaign.current_version.id);
  const [message, setMessage] = useState("");
  const [seed, setSeed] = useState(42);

  const floor = Math.max(minSize, states.length * MIN_PER_STATE);
  const statesError = states.length === 0 ? "Pick at least one state or union territory." : null;
  const sizeError = !int(size) || size < floor || size > maxSize ? `Use a whole number from ${floor} to ${maxSize}.${states.length > 1 ? ` Each state needs at least ${MIN_PER_STATE} accounts.` : ""}` : null;
  const roundsError = !int(rounds) || rounds < 1 || rounds > maxRounds ? `Use 1 to ${maxRounds}.` : null;
  const exposureError = !int(exposure) || exposure < 10 || exposure > 60 ? "Use a whole number from 10 to 60." : null;
  const degreeError = !int(degree) || degree < 2 || degree > 6 ? "Use 2 to 6." : null;
  const seedError = !int(seed) || seed < 0 ? "Use a whole number, 0 or more." : null;
  const invalid = Boolean(statesError || sizeError || roundsError || exposureError || degreeError || seedError);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (invalid) return;
    const body: BuzzCreate = {
      sampling: toPlan(dims, states),
      size,
      platform,
      rounds,
      initial_exposure: exposure / 100,
      degree,
      content_version_id: versionId === campaign.current_version.id ? null : versionId,
      intended_message: message.trim() || null,
      seed,
    };
    start.mutate(body, { onSuccess: (run) => onStarted(run.run_id) });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <ListPicker
        id="buzz-states"
        label="States"
        required
        placeholder="Add a state or union territory"
        options={options.states.map((s) => ({ value: s.code, label: s.name }))}
        value={states}
        onChange={setStates}
        max={MAX_STATES}
        hint={`One to ${MAX_STATES}. The simulated accounts are drawn state by state, each reading a language of its own state unless you pick languages below.`}
      />
      {statesError && (
        <p role="alert" className="-mt-3 text-xs font-medium text-danger">
          {statesError}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <FieldBlock label="Simulated accounts" htmlFor="buzz-size" error={sizeError} hint={`${floor} to ${maxSize}. A population size for the simulation, not a number of people.`}>
          <input id="buzz-size" type="number" inputMode="numeric" min={floor} max={maxSize} value={Number.isNaN(size) ? "" : size} onChange={(e) => setSize(e.target.valueAsNumber)} aria-invalid={Boolean(sizeError)} aria-describedby="buzz-size-hint" className={CONTROL} />
        </FieldBlock>
        <FieldBlock label="Platform" htmlFor="buzz-platform" hint="Sets the voice and length of the posts. No platform data is used.">
          <NativeSelect id="buzz-platform" value={platform} onChange={(e) => setPlatform(e.target.value as BuzzCreate["platform"])} aria-describedby="buzz-platform-hint">
            {defaults.platforms.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </NativeSelect>
        </FieldBlock>
        <FieldBlock label="Rounds" htmlFor="buzz-rounds" error={roundsError} hint={`1 to ${maxRounds}. Each account acts once, in the round after it first sees the creative.`}>
          <input id="buzz-rounds" type="number" inputMode="numeric" min={1} max={maxRounds} value={Number.isNaN(rounds) ? "" : rounds} onChange={(e) => setRounds(e.target.valueAsNumber)} aria-invalid={Boolean(roundsError)} aria-describedby="buzz-rounds-hint" className={CONTROL} />
        </FieldBlock>
        <FieldBlock label="Share who see it first (%)" htmlFor="buzz-exposure" error={exposureError} hint="10 to 60. A setting for the simulation, not a forecast of who would see it.">
          <input id="buzz-exposure" type="number" inputMode="numeric" min={10} max={60} value={Number.isNaN(exposure) ? "" : exposure} onChange={(e) => setExposure(e.target.valueAsNumber)} aria-invalid={Boolean(exposureError)} aria-describedby="buzz-exposure-hint" className={CONTROL} />
        </FieldBlock>
        <FieldBlock label="Accounts each account sees posts from" htmlFor="buzz-degree" error={degreeError} hint="2 to 6. Who sees whose posts is seeded and mostly within a state; it is not a measured follower graph.">
          <input id="buzz-degree" type="number" inputMode="numeric" min={2} max={6} value={Number.isNaN(degree) ? "" : degree} onChange={(e) => setDegree(e.target.valueAsNumber)} aria-invalid={Boolean(degreeError)} aria-describedby="buzz-degree-hint" className={CONTROL} />
        </FieldBlock>
        <FieldBlock label="Seed" htmlFor="buzz-seed" error={seedError} hint="The same seed and settings draw the same population and network. Model text can still differ between runs.">
          <input id="buzz-seed" type="number" min={0} value={Number.isNaN(seed) ? "" : seed} onChange={(e) => setSeed(e.target.valueAsNumber)} aria-invalid={Boolean(seedError)} aria-describedby="buzz-seed-hint" className={`${CONTROL} max-w-32`} />
        </FieldBlock>
      </div>

      {campaign.versions.length > 1 && (
        <FieldBlock label="Creative version" htmlFor="buzz-version" hint="The copy the accounts see.">
          <NativeSelect id="buzz-version" value={versionId} onChange={(e) => setVersionId(e.target.value)} aria-describedby="buzz-version-hint">
            {campaign.versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number}
                {v.id === campaign.current_version.id ? " (current)" : ""}: {v.content.headline ?? v.content.body ?? "No copy"}
              </option>
            ))}
          </NativeSelect>
        </FieldBlock>
      )}

      <FieldBlock label="Intended message" htmlFor="buzz-message" optional hint="What the creative should get across. Without it, what accounts pass on is compared with the creative's own copy.">
        <Textarea id="buzz-message" value={message} maxLength={300} rows={2} onChange={(e) => setMessage(e.target.value)} aria-describedby="buzz-message-hint" />
      </FieldBlock>

      <SamplingDimensions options={options} value={dims} onChange={setDims} languageHint="None selected means the languages of each chosen state." />

      <div className="space-y-3 border-t border-border pt-4">
        {start.error != null && <ErrorState error={start.error} />}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button type="submit" size="lg" disabled={start.isPending || Boolean(block) || invalid}>
            <Play aria-hidden />
            {start.isPending ? "Starting…" : "Run Buzz Simulator"}
          </Button>
          <p className="max-w-[60ch] text-[12.5px] text-ink-secondary">
            {block ??
              (project.mode === "demo"
                ? "Demo project: runs on labelled fixtures. It is free and calls no model."
                : "Live run: calls the configured language model once per batch of accounts per round, so it takes a minute or more.")}
          </p>
        </div>
      </div>
    </form>
  );
}
