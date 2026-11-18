"use client";

import { AudioLines, Boxes, Captions, Clapperboard, Heading, Image as ImageIcon, Lock, LockOpen, MousePointerClick, Music, Package, Pencil, Sparkles, Stamp, TextQuote, Type, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useEditElement, useSetLock } from "./api";
import { ChipsPanel } from "./chips";
import { elementText, isTextKind, KIND_LABEL, lineFor, scriptName, type ElementPair } from "./model";
import { Failed, languageLabel, LockState, MutationError, Passed, useStudio } from "./parts";
import type { CreativeElement, ElementKind, Lock as LockRow, LineResult, Operation, VersionNode, VersionSummary } from "./types";

const KIND_ICON: Record<ElementKind, LucideIcon> = {
  headline: Heading,
  body: Type,
  cta: MousePointerClick,
  tagline: TextQuote,
  logo: Stamp,
  product: Package,
  packshot: Boxes,
  image_region: ImageIcon,
  scene: Clapperboard,
  voiceover: AudioLines,
  music: Music,
  caption: Captions,
};

/** A short, human reading of one line's checks: the same ledger the Transcreate results show, condensed under the line. */
function CheckSummary({ line }: { line: LineResult }) {
  const t = line.term_checks;
  const protectedBad = [...t.missing_in_copy, ...t.missing_in_back_translation];
  const prohibitedBad = [...t.prohibited_in_copy, ...t.prohibited_in_back_translation];
  return (
    <ul aria-label="Checks on this line" className="flex flex-wrap gap-x-4 gap-y-1">
      <li className="inline-flex items-center gap-1.5">
        {line.script_check.ok ? <Passed>{`${scriptName(line.script_check.expected_script)} script`}</Passed> : <Failed>{`${scriptName(line.script_check.expected_script)} script`}</Failed>}
      </li>
      <li className="inline-flex items-center gap-1.5">
        {protectedBad.length ? <Failed>{`Protected term missing: ${[...new Set(protectedBad)].join(", ")}`}</Failed> : <Passed>{t.preserved_terms.length ? `Protected terms kept: ${t.preserved_terms.join(", ")}` : "No protected terms in this line"}</Passed>}
      </li>
      <li className="inline-flex items-center gap-1.5">
        {prohibitedBad.length ? <Failed>{`Prohibited term: ${[...new Set(prohibitedBad)].join(", ")}`}</Failed> : <Passed>No prohibited terms</Passed>}
      </li>
    </ul>
  );
}

/** The wording of one element in a column: copy in its own `lang` so the Indic face and line height apply, anything else as a descriptor. */
function Wording({ element, className }: { element: CreativeElement; className?: string }) {
  const text = elementText(element.value);
  const textual = isTextKind(element.kind);
  if (!text) return <p className="text-[13px] text-ink-muted">Empty.</p>;
  return textual ? (
    <p lang={element.language ?? undefined} className={cn("text-[15px] leading-relaxed whitespace-pre-line text-ink", className)}>
      {text}
    </p>
  ) : (
    <p className="font-mono text-[12px] leading-relaxed break-all text-ink-secondary">{text}</p>
  );
}

function ColumnLabel({ children, language }: { children: string; language?: string }) {
  return (
    <p className="type-meta mb-1 flex flex-wrap items-center gap-x-1.5">
      <span className="font-medium text-ink-secondary">{children}</span>
      {language && <span>{language}</span>}
    </p>
  );
}

function LockExplainer() {
  return (
    <p className="max-w-[68ch] text-[12.5px] leading-relaxed text-ink-muted">
      A lock stops every change to that element: your edits, Tweak Chips, transcreation runs and restores, whoever or whatever asks. Unlock it to change it. Locks apply to every version of this campaign, and each lock and release is recorded.
    </p>
  );
}

function EditBox({ element, versionId, versionLabel, onSaved, onCancel }: { element: CreativeElement; versionId: string; versionLabel: string; onSaved(id: string): void; onCancel(): void }) {
  const { campaignId } = useStudio();
  const edit = useEditElement(campaignId);
  const original = elementText(element.value);
  const [value, setValue] = useState(original);
  const [reason, setReason] = useState("");
  const unchanged = value.trim() === original.trim();
  return (
    <form
      className="space-y-2.5 rounded-lg border border-border bg-surface-muted/50 px-3.5 py-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (unchanged || !value.trim()) return;
        edit.mutate(
          { versionId, elementId: element.id, value: value.trim(), reason: reason.trim() || "Edited by hand in Creative Studio." },
          { onSuccess: (r) => { toast.success("Saved as a new version"); onSaved(r.version.id); } },
        );
      }}
    >
      <div className="space-y-1">
        <label htmlFor={`edit-${element.id}`} className="block text-[12.5px] font-medium text-ink">
          New wording for {KIND_LABEL[element.kind].toLowerCase()} <span className="font-mono text-[11.5px] text-ink-muted">{element.id}</span>
        </label>
        <Textarea id={`edit-${element.id}`} lang={element.language ?? undefined} value={value} onChange={(e) => setValue(e.target.value)} rows={3} className="text-[15px] leading-relaxed" />
      </div>
      <div className="space-y-1">
        <label htmlFor={`reason-${element.id}`} className="block text-[12.5px] font-medium text-ink">
          Why <span className="font-normal text-ink-secondary">(optional, kept in the history)</span>
        </label>
        <input
          id={`reason-${element.id}`}
          value={reason}
          maxLength={500}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Edited by hand in Creative Studio."
          className="h-8 w-full rounded-lg border border-input bg-surface-raised px-2.5 text-sm shadow-well outline-none focus-visible:border-ring dark:bg-surface-muted"
        />
      </div>
      <p className="text-[12.5px] text-ink-muted">Saving makes a new version from “{versionLabel}”. Nothing earlier is overwritten.</p>
      {edit.isError && <MutationError error={edit.error} />}
      <div className="flex gap-2">
        <Button type="submit" disabled={unchanged || !value.trim() || edit.isPending}>
          {edit.isPending ? "Saving…" : "Save as new version"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function ElementRow({
  pair,
  version,
  isOriginal,
  lock,
  match,
  onOpenVersion,
}: {
  pair: ElementPair;
  version: VersionNode;
  isOriginal: boolean;
  lock: LockRow | undefined;
  match: ReturnType<typeof lineFor>;
  onOpenVersion(id: string): void;
}) {
  const { campaignId, languageNames } = useStudio();
  const setLock = useSetLock(campaignId);
  const [mode, setMode] = useState<"view" | "edit" | "chips">("view");
  const { current, original } = pair;
  const Icon = KIND_ICON[pair.kind];
  const textual = isTextKind(pair.kind);
  const locked = Boolean(lock);
  const hasValue = current !== null && elementText(current.value).trim() !== "";

  return (
    <article aria-label={`${KIND_LABEL[pair.kind]} ${pair.id}`} className="space-y-3 px-4 py-3.5">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h3 className="inline-flex min-w-0 items-center gap-2 text-[14px] font-semibold text-ink">
          <Icon aria-hidden className="size-4 shrink-0 text-ink-secondary" />
          {KIND_LABEL[pair.kind]}
          <span className="font-mono text-[11.5px] font-normal text-ink-muted">{pair.id}</span>
        </h3>
        <LockState locked={locked} />
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {current && textual && hasValue && (
            <>
              <Button size="sm" variant="outline" disabled={locked} aria-expanded={mode === "edit"} onClick={() => setMode(mode === "edit" ? "view" : "edit")} title={locked ? "Locked: unlock this element to edit it." : undefined}>
                <Pencil aria-hidden />
                Edit
              </Button>
              <Button size="sm" variant="outline" disabled={locked} aria-expanded={mode === "chips"} onClick={() => setMode(mode === "chips" ? "view" : "chips")} title={locked ? "Locked: unlock this element to get tweak chips." : undefined}>
                <Sparkles aria-hidden />
                Tweak chips
              </Button>
            </>
          )}
          {current && (
            <Button
              size="sm"
              variant={locked ? "default" : "outline"}
              aria-pressed={locked}
              disabled={setLock.isPending}
              onClick={() => setLock.mutate({ elementId: pair.id, locked: !locked })}
              title={locked ? "Release the lock so this element can change again." : "Lock this element: nothing, including AI, can change it until you unlock it."}
            >
              {locked ? <Lock aria-hidden /> : <LockOpen aria-hidden />}
              {setLock.isPending ? "Saving…" : locked ? "Unlock" : "Lock"}
            </Button>
          )}
        </div>
      </header>

      {locked && lock && (
        <p className="text-[12.5px] text-ink-secondary">
          Locked {formatRelative(lock.locked_at)}
          {lock.reason ? `: ${lock.reason}` : ""}. Edits, chips, transcreation and restore all refuse this element until it is unlocked.
        </p>
      )}
      {setLock.isError && <MutationError error={setLock.error} />}

      <div className={cn("grid gap-x-6 gap-y-4", !isOriginal && "md:grid-cols-2")}>
        {!isOriginal && (
          <div className="min-w-0">
            <ColumnLabel language={original ? languageLabel(languageNames, original.language) : undefined}>Original</ColumnLabel>
            {original ? <Wording element={original} className="text-ink-body" /> : <p className="text-[13px] text-ink-muted">Not in the original: added in this line of versions.</p>}
          </div>
        )}
        <div className="min-w-0 space-y-2.5">
          <ColumnLabel language={current ? current.script && scriptName(current.script) !== languageLabel(languageNames, current.language) ? `${languageLabel(languageNames, current.language)}, ${scriptName(current.script)}` : languageLabel(languageNames, current.language) : undefined}>
            {isOriginal ? "This version, the original" : "This version"}
          </ColumnLabel>
          {current ? <Wording element={current} /> : <p className="text-[13px] text-ink-muted">Removed in this version.</p>}

          {current && textual && !isOriginal && hasValue && (match || (current.language && original?.language && current.language !== original.language)) && (
            <div className="space-y-1.5 border-t border-border pt-2.5">
              <p className="type-meta font-medium text-ink-secondary">English back-translation</p>
              {match ? (
                <>
                  <p className="text-[14px] leading-relaxed text-ink-body">{match.line.back_translation}</p>
                  {match.state === "edited" && (
                    <p className="text-[12.5px] text-warning">
                      This wording was edited after the transcreation, so the back-translation above belongs to the earlier wording, not to this text.
                    </p>
                  )}
                  <CheckSummary line={match.line} />
                </>
              ) : (
                <p className="text-[13px] text-ink-muted">No back-translation for this wording: it was not produced by a transcreation in this line of versions.</p>
              )}
            </div>
          )}
        </div>
      </div>

      {mode === "edit" && current && <EditBox element={current} versionId={version.id} versionLabel={version.label} onCancel={() => setMode("view")} onSaved={(id) => { setMode("view"); onOpenVersion(id); }} />}
      {mode === "chips" && current && <ChipsPanel element={current} versionId={version.id} versionRegion={version.region_code} onOpenVersion={(id) => { setMode("view"); onOpenVersion(id); }} />}
    </article>
  );
}

/**
 * Every element of the selected version with the original beside it. Text elements carry their English back-translation and
 * check results under the regional wording when a transcreation produced them. Each element can be locked, edited by hand,
 * or given Tweak Chips; the lock explains itself and a locked element refuses every one of those.
 */
export function ElementEditor({
  pairs,
  version,
  isOriginal,
  locks,
  operations,
  chain,
  onOpenVersion,
}: {
  pairs: ElementPair[];
  version: VersionNode;
  isOriginal: boolean;
  locks: LockRow[];
  operations: Operation[];
  chain: VersionSummary[];
  onOpenVersion(id: string): void;
}) {
  const lockById = new Map(locks.map((l) => [l.element_id, l]));
  return (
    <section aria-labelledby="elements-title" className="space-y-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="elements-title" className="text-[15px] font-semibold text-ink">
          Elements
        </h2>
        <span className="type-meta">
          {pairs.length} {pairs.length === 1 ? "element" : "elements"} · {locks.length} locked
        </span>
      </div>
      <LockExplainer />
      {pairs.length === 0 ? (
        <p className="rounded-card border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-muted">This version has no elements.</p>
      ) : (
        <div className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
          {pairs.map((pair) => {
            const text = pair.current ? elementText(pair.current.value) : "";
            return (
              <ElementRow
                key={pair.id}
                pair={pair}
                version={version}
                isOriginal={isOriginal}
                lock={lockById.get(pair.id)}
                match={pair.current && isTextKind(pair.kind) ? lineFor(operations, chain, pair.id, text) : null}
                onOpenVersion={onOpenVersion}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}

