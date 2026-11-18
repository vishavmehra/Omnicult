"use client";

import { ArrowLeftRight, ArrowRight, Equal, Minus, PencilLine, Plus, SlidersHorizontal } from "lucide-react";
import { useState } from "react";

import { LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";

import { useDiff, useVersion } from "./api";
import { elementText, KIND_LABEL, lineage, scriptName, TONE_DIALS } from "./model";
import { languageLabel, MutationError, NativeSelect, useStudio } from "./parts";
import type { CreativeElement, VersionDiff, VersionNode, VersionSummary } from "./types";

const FIELD_LABEL: Record<string, string> = { value: "Wording", language: "Language", script: "Script", bbox: "Position", scene_id: "Scene", kind: "Kind", region_code: "Region", locked: "Lock" };

function settingLabel(field: string) {
  if (field.startsWith("tone.")) {
    const dial = TONE_DIALS.find((d) => d.key === field.slice(5));
    return `Tone: ${dial?.label.toLowerCase() ?? field.slice(5)}`;
  }
  return FIELD_LABEL[field] ?? field;
}

function show(field: string, value: unknown, names: Map<string, string>) {
  if (value === null || value === undefined || value === "") return "None";
  if (field === "language" && typeof value === "string") return languageLabel(names, value);
  if (field === "script" && typeof value === "string") return scriptName(value);
  return elementText(value);
}

function Before({ children }: { children: React.ReactNode }) {
  return <div className="min-w-0 rounded-md bg-surface-muted/70 px-2.5 py-1.5 text-[13.5px] leading-snug text-ink-secondary">{children}</div>;
}
function After({ children }: { children: React.ReactNode }) {
  return <div className="min-w-0 rounded-md bg-surface-muted/70 px-2.5 py-1.5 text-[13.5px] leading-snug text-ink">{children}</div>;
}

/** What changed from one version to another, in four groups (changed, added, removed, preserved) plus setting and tone changes. */
function DiffBody({ diff, numbers, fromNode, toNode }: { diff: VersionDiff; numbers: Map<string, number>; fromNode?: VersionNode; toNode?: VersionNode }) {
  const { languageNames } = useStudio();
  const textLang = (e: CreativeElement) => e.language ?? undefined;
  const langIn = (node: VersionNode | undefined, id: string) => node?.elements.find((e) => e.id === id)?.language ?? undefined;
  return (
    <div className="space-y-6">
      <p className="type-ledger text-[13px] text-ink-body" role="status">
        v{numbers.get(diff.from_id)} to v{numbers.get(diff.to_id)}: {diff.changed.length} changed, {diff.added.length} added, {diff.removed.length} removed, {diff.preserved.length} preserved
        {diff.settings_changes.length ? `, ${diff.settings_changes.length} setting ${diff.settings_changes.length === 1 ? "change" : "changes"}` : ""}.
      </p>

      <section aria-labelledby="diff-settings" className="space-y-2">
        <h3 id="diff-settings" className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-ink">
          <SlidersHorizontal aria-hidden className="size-4 text-ink-secondary" />
          Region, language and tone
        </h3>
        {diff.settings_changes.length === 0 ? (
          <p className="text-[13px] text-ink-muted">The region, language and tone dials are the same in both versions.</p>
        ) : (
          <dl className="ledger-rules type-ledger overflow-hidden rounded-lg border border-border bg-surface">
            {diff.settings_changes.map((c) => (
              <div key={c.field} className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-3 px-3 py-2 sm:grid-cols-[11rem_minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-center">
                <dt className="text-[12.5px] text-ink-secondary">{settingLabel(c.field)}</dt>
                <dd className="contents">
                  <span className="text-[13.5px] text-ink-secondary">{show(c.field, c.before, languageNames)}</span>
                  <ArrowRight aria-hidden className="hidden size-3.5 text-ink-muted sm:block" />
                  <span className="text-[13.5px] font-medium text-ink">{show(c.field, c.after, languageNames)}</span>
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section aria-labelledby="diff-changed" className="space-y-2">
        <h3 id="diff-changed" className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-ink">
          <PencilLine aria-hidden className="size-4 text-ink-secondary" />
          Changed ({diff.changed.length})
        </h3>
        {diff.changed.length === 0 ? (
          <p className="text-[13px] text-ink-muted">No element changed.</p>
        ) : (
          <div className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
            {diff.changed.map((c) => {
              return (
                <article key={c.element_id} className="space-y-2 px-4 py-3">
                  <h4 className="text-[14px] font-semibold text-ink">
                    {KIND_LABEL[c.kind]} <span className="font-mono text-[11.5px] font-normal text-ink-muted">{c.element_id}</span>
                  </h4>
                  {c.fields.map((f) => (
                    <div key={f.field} className="space-y-1">
                      <p className="type-meta font-medium text-ink-secondary">{FIELD_LABEL[f.field] ?? f.field}</p>
                      <div className="grid gap-1.5 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-start md:gap-3">
                        <Before>
                          <span lang={f.field === "value" ? langIn(fromNode, c.element_id) : undefined}>{show(f.field, f.before, languageNames)}</span>
                        </Before>
                        <ArrowRight aria-hidden className="mt-2 hidden size-4 text-ink-muted md:block" />
                        <After>
                          <span lang={f.field === "value" ? langIn(toNode, c.element_id) : undefined}>{show(f.field, f.after, languageNames)}</span>
                        </After>
                      </div>
                    </div>
                  ))}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {(["added", "removed"] as const).map((group) => {
        const items = diff[group];
        const Icon = group === "added" ? Plus : Minus;
        return (
          <section key={group} aria-labelledby={`diff-${group}`} className="space-y-2">
            <h3 id={`diff-${group}`} className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-ink">
              <Icon aria-hidden className="size-4 text-ink-secondary" />
              {group === "added" ? "Added" : "Removed"} ({items.length})
            </h3>
            {items.length === 0 ? (
              <p className="text-[13px] text-ink-muted">No element was {group}.</p>
            ) : (
              <ul className="ledger-rules overflow-hidden rounded-lg border border-border bg-surface">
                {items.map((e) => (
                  <li key={e.id} className="px-3 py-2.5">
                    <p className="text-[13px] font-medium text-ink">
                      {KIND_LABEL[e.kind]} <span className="font-mono text-[11.5px] font-normal text-ink-muted">{e.id}</span>
                    </p>
                    <p lang={textLang(e)} className="mt-0.5 text-[14px] text-ink-body">
                      {elementText(e.value) || "Empty"}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}

      <section aria-labelledby="diff-preserved" className="space-y-2">
        <h3 id="diff-preserved" className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-ink">
          <Equal aria-hidden className="size-4 text-ink-secondary" />
          Preserved ({diff.preserved.length})
        </h3>
        {diff.preserved.length === 0 ? (
          <p className="text-[13px] text-ink-muted">No element is identical in both versions.</p>
        ) : (
          <>
            <ul className="flex flex-wrap gap-1.5" aria-label="Unchanged elements">
              {diff.preserved.map((id) => (
                <li key={id} className="rounded-stamp border border-border px-1.5 py-0.5 font-mono text-[12px] text-ink-secondary">
                  {id}
                </li>
              ))}
            </ul>
            <p className="text-[12.5px] text-ink-muted">Identical in wording, language, script, position and scene. A lock flag is not content and is ignored here.</p>
          </>
        )}
      </section>
    </div>
  );
}

/** Pick any two versions of the campaign; the server computes the difference, the screen only lays it out. */
export function DiffView({ versions, numbers, selectedId }: { versions: VersionSummary[]; numbers: Map<string, number>; selectedId: string }) {
  const { campaignId } = useStudio();
  // Starts as "the version before the selected one" to "the selected one"; the workspace remounts this view (key) when the
  // selection changes. A root has no parent, so it is compared with the newest other version instead.
  const [from, setFrom] = useState<string>(() => {
    const chain = lineage(versions, selectedId);
    return chain[1]?.id ?? selectedId;
  });
  const [to, setTo] = useState<string>(() => {
    const chain = lineage(versions, selectedId);
    if (chain.length > 1) return selectedId;
    return [...versions].reverse().find((v) => v.id !== selectedId)?.id ?? selectedId;
  });

  const diff = useDiff(campaignId, from !== to ? from : null, from !== to ? to : null);
  const fromNode = useVersion(campaignId, from).data;
  const toNode = useVersion(campaignId, to).data;
  const options = [...versions].sort((a, b) => (numbers.get(a.id) ?? 0) - (numbers.get(b.id) ?? 0));
  const label = (v: VersionSummary) => `v${numbers.get(v.id)}: ${v.label}`;

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-[15px] font-semibold text-ink">Compare two versions</h2>
        <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">Shows what the later version changed, kept, added or removed, and whether its region, language or tone dials moved. Nothing here edits a version.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-end">
        <div className="space-y-1">
          <label htmlFor="diff-from" className="block text-[12.5px] font-medium text-ink">
            From
          </label>
          <NativeSelect id="diff-from" value={from} onChange={(e) => setFrom(e.target.value)}>
            {options.map((v) => (
              <option key={v.id} value={v.id}>
                {label(v)}
              </option>
            ))}
          </NativeSelect>
        </div>
        <Button variant="outline" size="icon" aria-label="Swap the two versions" onClick={() => { setFrom(to); setTo(from); }}>
          <ArrowLeftRight aria-hidden />
        </Button>
        <div className="space-y-1">
          <label htmlFor="diff-to" className="block text-[12.5px] font-medium text-ink">
            To
          </label>
          <NativeSelect id="diff-to" value={to} onChange={(e) => setTo(e.target.value)}>
            {options.map((v) => (
              <option key={v.id} value={v.id}>
                {label(v)}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>

      {versions.length < 2 ? (
        <p className="rounded-card border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-secondary">
          There is only one version, so there is nothing to compare. Edit an element, apply a chip or transcreate to make a second version.
        </p>
      ) : from === to ? (
        <p className="text-[13px] text-ink-secondary">Choose two different versions.</p>
      ) : diff.isPending ? (
        <LoadingState label="Comparing the versions…" />
      ) : diff.isError ? (
        <MutationError error={diff.error} onRetry={() => void diff.refetch()} />
      ) : (
        <DiffBody diff={diff.data} numbers={numbers} fromNode={fromNode} toNode={toNode} />
      )}
    </div>
  );
}
