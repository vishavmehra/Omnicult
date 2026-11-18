"use client";

import { ChevronRight, Languages, Lock, TriangleAlert } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { Field } from "@/components/forms/fields";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import { formatRelative } from "@/lib/format";

import { studioKeys, useRegions, useStartTranscreate, type TranscreateVars } from "./api";
import { LineResults, TranscreateLimits } from "./line-results";
import { asLines, DEFAULT_TONE, dialWord, elementText, isTextKind, KIND_LABEL, lineCounts, TONE_DIALS } from "./model";
import { languageLabel, MutationError, NativeSelect, Status, useStudio } from "./parts";
import type { Lock as LockRow, Operation, Region, Tone, VersionNode } from "./types";

const ROLE_ORDER = { primary: 0, secondary: 1, code_mixed: 2 } as const;
const ROLE_WORD = { primary: "primary", secondary: "secondary", code_mixed: "code-mixed" } as const;

function ToneDials({ tone, onChange, disabled }: { tone: Tone; onChange(next: Tone): void; disabled: boolean }) {
  return (
    <fieldset className="space-y-3" disabled={disabled}>
      <legend className="mb-1 text-[13px] font-medium text-ink">Tone dials</legend>
      <p className="max-w-[68ch] text-[12.5px] text-ink-muted">
        Each dial becomes an explicit instruction in the model call and is stored on the new version, so the tone of every version can be read back later. At either end of a dial the instruction is firm; near the middle it follows the brand voice.
      </p>
      <div className="grid gap-x-8 gap-y-3.5 md:grid-cols-2">
        {TONE_DIALS.map((dial) => (
          <div key={dial.key} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[13px] text-ink-body">{dial.label}</span>
              <span className="type-ledger text-[12.5px] text-ink">{dialWord(dial, tone[dial.key])}</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={tone[dial.key]}
              disabled={disabled}
              aria-label={dial.label}
              aria-valuetext={dialWord(dial, tone[dial.key])}
              onChange={(e) => onChange({ ...tone, [dial.key]: Number(e.target.value) })}
              className="h-5 w-full cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-50"
            />
            <div className="type-meta flex justify-between">
              <span>{dial.low}</span>
              <span>{dial.high}</span>
            </div>
          </div>
        ))}
      </div>
    </fieldset>
  );
}

function languageOptions(region: Region | undefined) {
  return [...(region?.languages ?? [])].sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role]);
}

/** Earlier transcreations of this campaign, newest first, each with its lines on demand. */
function EarlierRuns({ operations, skipId }: { operations: Operation[]; skipId: string | null }) {
  const past = operations.filter((o) => o.kind === "transcreate" && o.id !== skipId);
  if (past.length === 0) return null;
  return (
    <section aria-labelledby="earlier-transcreations" className="space-y-2">
      <h3 id="earlier-transcreations" className="text-[15px] font-semibold text-ink">
        Earlier transcreations
      </h3>
      <ul className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
        {past.map((op) => (
          <li key={op.id}>
            <EarlierRun op={op} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function EarlierRun({ op }: { op: Operation }) {
  const [open, setOpen] = useState(false);
  const { languageNames } = useStudio();
  const lines = asLines(op.params);
  const { passed, review } = lineCounts(lines);
  const language = typeof op.params.language === "string" ? op.params.language : "";
  const region = typeof op.params.region_code === "string" ? op.params.region_code : "";
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)} className="group px-4 py-2.5">
      <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 text-[13.5px] select-none">
        <ChevronRight aria-hidden className="size-3.5 shrink-0 transition-transform group-open:rotate-90" />
        <span className="font-medium text-ink">{languageLabel(languageNames, language)}</span>
        <span className="font-mono text-[11.5px] text-ink-muted">{region}</span>
        {op.status === "applied" ? (
          <span className="text-ink-secondary">
            {passed} applied{review > 0 ? `, ${review} for review` : ""}
          </span>
        ) : (
          <Status tone="warning" Icon={TriangleAlert}>
            Refused, nothing applied
          </Status>
        )}
        <span className="type-meta ml-auto" title={op.created_at}>
          {formatRelative(op.created_at)}
        </span>
      </summary>
      {open && (
        <div className="space-y-3 pt-3">
          {op.rejection && <p className="text-[13px] text-ink-body">{op.rejection.message}</p>}
          {lines.length > 0 ? <LineResults lines={lines} language={language} /> : <p className="text-[13px] text-ink-muted">No lines were stored on this operation.</p>}
        </div>
      )}
    </details>
  );
}

/**
 * Transcreate: choose the target region and language from the reference lists, pick the lines, set the five tone dials and run.
 * The run is asynchronous, so progress is the shared run status (real stages and elapsed time, never a made-up percentage).
 * Results come back per line with the back-translation and the code checks; lines that fail stay here for review.
 */
export function TranscreatePanel({
  version,
  locks,
  operations,
  runId: shownRunId,
  onRun,
  onOpenVersion,
}: {
  version: VersionNode;
  locks: LockRow[];
  operations: Operation[];
  runId: string | null;
  onRun(id: string): void;
  onOpenVersion(id: string): void;
}) {
  const { campaignId, projectId, demo } = useStudio();
  const client = useQueryClient();
  const regions = useRegions();
  const start = useStartTranscreate(campaignId);
  const lockedIds = useMemo(() => new Set(locks.map((l) => l.element_id)), [locks]);
  const textElements = version.elements.filter((e) => isTextKind(e.kind) && elementText(e.value).trim() !== "");
  const [picked, setPicked] = useState<Set<string>>(() => new Set(textElements.filter((e) => !lockedIds.has(e.id)).map((e) => e.id)));
  const [regionCode, setRegionCode] = useState("");
  const [language, setLanguage] = useState("");
  const [tone, setTone] = useState<Tone>(DEFAULT_TONE);
  const [lastVars, setLastVars] = useState<TranscreateVars | null>(null);
  // After a page refresh, a run that was still going comes back as the one shown.
  const latest = useLatestRun(projectId, { runType: "transcreate", campaignId });
  const resumable = latest.data && !isTerminal(latest.data.status) ? latest.data.id : null;
  const runId = shownRunId ?? resumable;
  const run = useRun(runId);
  const refreshed = useRef<string | null>(null);

  // When the run ends, the new version, its operation and the history are on the server: refresh the whole Studio.
  useEffect(() => {
    const r = run.data;
    if (r && isTerminal(r.status) && refreshed.current !== r.id) {
      refreshed.current = r.id;
      void client.invalidateQueries({ queryKey: studioKeys.all(campaignId) });
    }
  }, [run.data, client, campaignId]);

  const region = regions.data?.items.find((r) => r.code === regionCode);
  const langs = languageOptions(region);
  const chosen = textElements.filter((e) => picked.has(e.id) && !lockedIds.has(e.id));
  const busy = start.isPending || Boolean(run.data && !isTerminal(run.data.status));

  function launch(vars: TranscreateVars) {
    setLastVars(vars);
    start.mutate(vars, { onSuccess: (accepted) => onRun(accepted.run_id) });
  }

  const ref = run.data?.result;
  const resultOp =
    ref && run.data && isTerminal(run.data.status)
      ? operations.find((o) => (ref.resource === "operation" ? o.id === ref.ids[0] : ref.resource === "version" ? o.result_version_id === ref.ids[0] : false))
      : undefined;
  const resultLines = asLines(resultOp?.params);
  const resultVersionId = resultOp?.result_version_id ?? (ref?.resource === "version" ? (ref.ids[0] ?? null) : null);

  return (
    <div className="space-y-7">
      <section aria-labelledby="transcreate-title" className="space-y-4">
        <div className="space-y-1">
          <h2 id="transcreate-title" className="text-[15px] font-semibold text-ink">
            Transcreate “{version.label}”
          </h2>
          <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">
            Adapts each chosen line for a region and language, not word for word. The result is a new version beside this one; this version is never changed. To start again from the original copy, select the original in the version tree first.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Region" htmlFor="tc-region" required>
            <NativeSelect
              id="tc-region"
              value={regionCode}
              disabled={busy || regions.isPending}
              onChange={(e) => {
                const next = e.target.value;
                setRegionCode(next);
                const r = regions.data?.items.find((x) => x.code === next);
                setLanguage(r?.primary_language ?? "");
              }}
            >
              <option value="">{regions.isPending ? "Loading regions…" : "Choose a region"}</option>
              {regions.data?.items.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name} ({r.code})
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Language" htmlFor="tc-language" required hint={language && region ? "The script follows the language and is checked in code on every line." : undefined}>
            <NativeSelect id="tc-language" value={language} disabled={busy || !region} onChange={(e) => setLanguage(e.target.value)}>
              <option value="">{region ? "Choose a language" : "Choose a region first"}</option>
              {langs.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                  {l.native_name && l.native_name !== l.name ? `, ${l.native_name}` : ""} ({ROLE_WORD[l.role]})
                </option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        {regions.isError && <MutationError error={regions.error} onRetry={() => void regions.refetch()} />}

        <fieldset className="space-y-2" disabled={busy}>
          <legend className="mb-1 text-[13px] font-medium text-ink">Lines to transcreate</legend>
          {textElements.length === 0 ? (
            <p className="rounded-card border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-muted">This version has no text element to transcreate.</p>
          ) : (
            <ul className="ledger-rules overflow-hidden rounded-lg border border-border bg-surface">
              {textElements.map((e) => {
                const locked = lockedIds.has(e.id);
                const on = picked.has(e.id) && !locked;
                return (
                  <li key={e.id}>
                    <label className="flex cursor-pointer items-start gap-3 px-3 py-2.5 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-70">
                      <Checkbox
                        checked={on}
                        disabled={locked}
                        onCheckedChange={(c) =>
                          setPicked((prev) => {
                            const next = new Set(prev);
                            if (c) next.add(e.id);
                            else next.delete(e.id);
                            return next;
                          })
                        }
                        aria-label={`${KIND_LABEL[e.kind]} ${e.id}`}
                        className="mt-0.5"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2 text-[13.5px] font-medium text-ink">
                          {KIND_LABEL[e.kind]}
                          <span className="font-mono text-[11.5px] font-normal text-ink-muted">{e.id}</span>
                          {locked && (
                            <Status tone="warning" Icon={Lock}>
                              Locked, refuses transcreation
                            </Status>
                          )}
                        </span>
                        <span lang={e.language ?? undefined} className="mt-0.5 line-clamp-2 block text-[13.5px] text-ink-secondary">
                          {elementText(e.value)}
                        </span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </fieldset>

        <ToneDials tone={tone} onChange={setTone} disabled={busy} />

        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              size="lg"
              disabled={busy || !regionCode || !language || chosen.length === 0}
              onClick={() => launch({ versionId: version.id, regionCode, language, elementIds: chosen.length === textElements.filter((e) => !lockedIds.has(e.id)).length ? null : chosen.map((e) => e.id), tone })}
            >
              <Languages aria-hidden />
              {busy ? "Transcreating…" : `Transcreate ${chosen.length} ${chosen.length === 1 ? "line" : "lines"}`}
            </Button>
            <p className="text-[12.5px] text-ink-muted">
              {demo ? "Source: demo fixtures, available for a few lines only." : "One model call; its cost estimate is recorded on the new version."}
            </p>
          </div>
          {start.isError && <MutationError error={start.error} onRetry={lastVars ? () => launch(lastVars) : undefined} />}
        </div>
      </section>

      {runId && (
        <section aria-labelledby="tc-run-title" className="space-y-3">
          <h2 id="tc-run-title" className="text-[15px] font-semibold text-ink">
            This run
          </h2>
          <RunStatusPanel run={run.data} operation="Transcreate" onRetry={lastVars ? () => launch(lastVars) : undefined} />
          {run.isError && <MutationError error={run.error} onRetry={() => void run.refetch()} />}
          {run.data && isTerminal(run.data.status) && (
            <>
              {resultLines.length > 0 ? (
                <>
                  <LineResults lines={resultLines} language={typeof resultOp?.params.language === "string" ? resultOp.params.language : language} />
                  <TranscreateLimits />
                  {resultVersionId && (
                    <Button variant="outline" onClick={() => onOpenVersion(resultVersionId)}>
                      Open the new version
                    </Button>
                  )}
                </>
              ) : run.data.status === "completed" || run.data.status === "partial" ? (
                <p className="text-[13px] text-ink-muted">The run finished but its lines are not loaded yet.</p>
              ) : null}
            </>
          )}
        </section>
      )}

      <EarlierRuns operations={operations} skipId={resultOp?.id ?? null} />
    </div>
  );
}
