"use client";

import { BookMarked, Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Tag } from "@/components/evidence/badges";
import { Field, TermListInput } from "@/components/forms/fields";
import { EmptyState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/errors";

import { useCreateTerm, useDeleteTerm, useGlossary, useUpdateTerm } from "./api";
import { SCRIPT_CODES, scriptName } from "./model";
import { languageLabel, MutationError, NativeSelect, useStudio } from "./parts";
import type { GlossaryTerm } from "./types";

type Draft = {
  term: string;
  language: string;
  script: string;
  approved_spelling: string;
  preferred_translation: string;
  pronunciation: string;
  protected: boolean;
  never_translate: boolean;
  prohibited_alternatives: string[];
  notes: string;
};

const BLANK: Draft = { term: "", language: "*", script: "", approved_spelling: "", preferred_translation: "", pronunciation: "", protected: false, never_translate: false, prohibited_alternatives: [], notes: "" };
const toDraft = (t: GlossaryTerm): Draft => ({
  term: t.term,
  language: t.language,
  script: t.script ?? "",
  approved_spelling: t.approved_spelling ?? "",
  preferred_translation: t.preferred_translation ?? "",
  pronunciation: t.pronunciation ?? "",
  protected: t.protected,
  never_translate: t.never_translate,
  prohibited_alternatives: t.prohibited_alternatives,
  notes: t.notes ?? "",
});
const orNull = (s: string) => (s.trim() ? s.trim() : null);

/** Add or edit one entry. A term and its language identify the entry, so they are fixed once it exists. */
function TermForm({ existing, onDone }: { existing?: GlossaryTerm; onDone(): void }) {
  const { campaignId, languages } = useStudio();
  const create = useCreateTerm(campaignId);
  const update = useUpdateTerm(campaignId);
  const [d, setD] = useState<Draft>(existing ? toDraft(existing) : BLANK);
  const mutation = existing ? update : create;
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setD((prev) => ({ ...prev, [key]: value }));
  const apiError = mutation.error instanceof ApiError && mutation.error.code === "VALIDATION_ERROR" ? mutation.error : null;
  const fieldError = (name: string) => apiError?.details.find((x) => x.field === name)?.message ?? null;
  const scriptNeeded = d.approved_spelling.trim() !== "" && d.script === "";

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!d.term.trim() || scriptNeeded) return;
    const body = {
      script: orNull(d.script),
      approved_spelling: orNull(d.approved_spelling),
      preferred_translation: orNull(d.preferred_translation),
      pronunciation: orNull(d.pronunciation),
      protected: d.protected,
      never_translate: d.never_translate,
      prohibited_alternatives: d.prohibited_alternatives,
      notes: orNull(d.notes),
    };
    const done = () => {
      toast.success(existing ? "Glossary entry updated" : "Glossary entry added");
      onDone();
    };
    if (existing) update.mutate({ id: existing.id, body }, { onSuccess: done });
    else create.mutate({ term: d.term.trim(), language: d.language, ...body }, { onSuccess: done });
  }

  return (
    <form onSubmit={submit} aria-label={existing ? `Edit ${existing.term}` : "Add a glossary term"} className="space-y-4 rounded-card border border-border bg-surface px-4 py-4">
      <h3 className="text-[15px] font-semibold text-ink">{existing ? `Edit “${existing.term}”` : "Add a term"}</h3>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Term as written in the source copy" htmlFor="gl-term" required error={fieldError("term")}>
          <Input id="gl-term" value={d.term} maxLength={200} disabled={Boolean(existing)} onChange={(e) => set("term", e.target.value)} className="bg-surface" />
        </Field>
        <Field label="Applies to" htmlFor="gl-lang" required hint={existing ? "An entry is identified by its term and language, so these two cannot change." : "One language, or every language."} error={fieldError("language")}>
          <NativeSelect
            id="gl-lang"
            value={d.language}
            disabled={Boolean(existing)}
            onChange={(e) => {
              const code = e.target.value;
              setD((prev) => ({ ...prev, language: code, script: prev.script || (languages.find((l) => l.code === code)?.script ?? "") }));
            }}
          >
            <option value="*">All languages</option>
            {languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name} ({l.code})
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Approved spelling" htmlFor="gl-spelling" hint="How the brand writes this term in the language and script above. It is checked against the script." error={fieldError("approved_spelling")}>
          <Input id="gl-spelling" value={d.approved_spelling} maxLength={200} onChange={(e) => set("approved_spelling", e.target.value)} className="bg-surface" lang={d.language === "*" ? undefined : d.language} />
        </Field>
        <Field label="Script of the approved spelling" htmlFor="gl-script" required={d.approved_spelling.trim() !== ""} error={fieldError("script") ?? (scriptNeeded ? "Choose the script of the approved spelling." : null)}>
          <NativeSelect id="gl-script" value={d.script} onChange={(e) => set("script", e.target.value)}>
            <option value="">No script</option>
            {SCRIPT_CODES.map((c) => (
              <option key={c} value={c}>
                {scriptName(c)} ({c})
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Preferred translation" htmlFor="gl-pref" hint="Followed when it can be, and flagged (not blocking) when a line leaves it out.">
          <Input id="gl-pref" value={d.preferred_translation} maxLength={200} onChange={(e) => set("preferred_translation", e.target.value)} className="bg-surface" lang={d.language === "*" ? undefined : d.language} />
        </Field>
        <Field label="Pronunciation" htmlFor="gl-pron" hint="For voice-over direction.">
          <Input id="gl-pron" value={d.pronunciation} maxLength={200} onChange={(e) => set("pronunciation", e.target.value)} className="bg-surface" />
        </Field>
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        <label className="flex cursor-pointer items-start gap-2.5 text-[13.5px] text-ink">
          <Checkbox checked={d.protected} onCheckedChange={(c) => set("protected", Boolean(c))} className="mt-0.5" />
          <span>
            Protected
            <span className="block text-[12.5px] text-ink-muted">Must survive transcreation, as the approved spelling if there is one.</span>
          </span>
        </label>
        <label className="flex cursor-pointer items-start gap-2.5 text-[13.5px] text-ink">
          <Checkbox checked={d.never_translate} onCheckedChange={(c) => set("never_translate", Boolean(c))} className="mt-0.5" />
          <span>
            Never translate
            <span className="block text-[12.5px] text-ink-muted">Treated like protected: kept as written.</span>
          </span>
        </label>
      </div>
      <Field label="Prohibited alternatives" htmlFor="gl-prohibited" hint="Wordings that must not appear in the regional copy or its back-translation. Press Enter to add each one.">
        <TermListInput id="gl-prohibited" value={d.prohibited_alternatives} onChange={(v) => set("prohibited_alternatives", v)} max={20} placeholder="A wording to refuse" />
      </Field>
      <Field label="Notes" htmlFor="gl-notes">
        <Textarea id="gl-notes" value={d.notes} maxLength={500} rows={2} onChange={(e) => set("notes", e.target.value)} />
      </Field>
      {mutation.isError && <MutationError error={mutation.error} />}
      <div className="flex gap-2">
        <Button type="submit" disabled={!d.term.trim() || scriptNeeded || mutation.isPending}>
          {mutation.isPending ? "Saving…" : existing ? "Save changes" : "Add term"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function TermRow({ term, onEdit }: { term: GlossaryTerm; onEdit(): void }) {
  const { campaignId, languageNames } = useStudio();
  const remove = useDeleteTerm(campaignId);
  const [confirming, setConfirming] = useState(false);
  const lang = term.language === "*" ? undefined : term.language;
  return (
    <div className="space-y-1.5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h4 className="text-[14.5px] font-semibold text-ink">{term.term}</h4>
        <span className="type-meta">{term.language === "*" ? "All languages" : languageLabel(languageNames, term.language)}</span>
        {term.protected && <Tag className="border-border bg-surface-muted text-ink">Protected</Tag>}
        {term.never_translate && <Tag className="border-border bg-surface-muted text-ink">Never translate</Tag>}
        <div className="ml-auto flex items-center gap-1.5">
          {confirming ? (
            <>
              <span className="text-[12.5px] text-ink-secondary">Delete this entry? Runs that used it keep their own copy.</span>
              <Button size="sm" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate({ id: term.id }, { onSuccess: () => toast.success("Glossary entry deleted") })}>
                {remove.isPending ? "Deleting…" : "Delete"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                Keep
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={onEdit} aria-label={`Edit ${term.term}`}>
                <Pencil aria-hidden />
                Edit
              </Button>
              <Button size="icon-sm" variant="ghost" onClick={() => setConfirming(true)} aria-label={`Delete ${term.term}`}>
                <Trash2 aria-hidden />
              </Button>
            </>
          )}
        </div>
      </div>
      <dl className="type-ledger grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-2">
        {term.approved_spelling && (
          <div className="flex gap-2">
            <dt className="text-ink-muted">Approved spelling</dt>
            <dd lang={lang} className="text-ink">
              {term.approved_spelling}
              {term.script && <span className="text-ink-muted"> ({scriptName(term.script)})</span>}
            </dd>
          </div>
        )}
        {term.preferred_translation && (
          <div className="flex gap-2">
            <dt className="text-ink-muted">Preferred translation</dt>
            <dd lang={lang} className="text-ink">
              {term.preferred_translation}
            </dd>
          </div>
        )}
        {term.pronunciation && (
          <div className="flex gap-2">
            <dt className="text-ink-muted">Pronunciation</dt>
            <dd className="text-ink">{term.pronunciation}</dd>
          </div>
        )}
        {term.prohibited_alternatives.length > 0 && (
          <div className="flex gap-2 sm:col-span-2">
            <dt className="shrink-0 text-ink-muted">Prohibited</dt>
            <dd className="text-ink">{term.prohibited_alternatives.join(", ")}</dd>
          </div>
        )}
      </dl>
      {term.notes && <p className="text-[12.5px] text-ink-secondary">{term.notes}</p>}
      {remove.isError && <MutationError error={remove.error} />}
    </div>
  );
}

/**
 * The Brand Glossary: how this brand's terms are spelled, translated and protected, per language and script. It belongs to the
 * brand, so every campaign of the brand reads the same entries. Transcreate and Tweak Chips use it, and its protected and
 * prohibited terms are checked in code on the regional copy and on the English back-translation.
 */
export function GlossaryPanel() {
  const { campaignId, languageNames } = useStudio();
  const glossary = useGlossary(campaignId);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [filter, setFilter] = useState("");
  const items = glossary.data?.items ?? [];
  const usedLanguages = [...new Set(items.map((t) => t.language))].filter((l) => l !== "*");
  const shown = filter ? items.filter((t) => t.language === filter || t.language === "*") : items;

  return (
    <section aria-labelledby="glossary-title" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h2 id="glossary-title" className="text-[15px] font-semibold text-ink">
            Brand Glossary
          </h2>
          <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">
            The brand&apos;s own spellings, preferred translations and protected terms per language and script. Every campaign of this brand reads the same entries; Transcreate and Tweak Chips follow them, and protected and prohibited terms are checked in code on both the regional copy and the English back-translation.
          </p>
        </div>
        {editing === null && (
          <Button onClick={() => setEditing("new")}>
            <Plus aria-hidden />
            Add a term
          </Button>
        )}
      </div>

      {editing === "new" && <TermForm onDone={() => setEditing(null)} />}

      {glossary.isPending ? (
        <LoadingState label="Loading the glossary…" />
      ) : glossary.isError ? (
        <MutationError error={glossary.error} onRetry={() => void glossary.refetch()} />
      ) : items.length === 0 ? (
        editing === "new" ? null : (
          <EmptyState
            title="No glossary entries yet"
            description="Add the brand names, product names and phrases that must survive adaptation, with the spelling the brand uses in each script. Until then only the Brand Kit's protected and prohibited terms are checked."
            action={
              <Button onClick={() => setEditing("new")}>
                <Plus aria-hidden />
                Add the first term
              </Button>
            }
          />
        )
      ) : (
        <>
          {usedLanguages.length > 0 && (
            <div className="flex max-w-xs items-center gap-2">
              <label htmlFor="gl-filter" className="shrink-0 text-[12.5px] text-ink-secondary">
                Show
              </label>
              <NativeSelect id="gl-filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="">All entries</option>
                {usedLanguages.map((l) => (
                  <option key={l} value={l}>
                    {languageLabel(languageNames, l)} and all-language entries
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}
          <ul aria-label="Glossary entries" className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
            {shown.map((t) => (
              <li key={t.id}>
                {editing === t.id ? (
                  <div className="p-3">
                    <TermForm existing={t} onDone={() => setEditing(null)} />
                  </div>
                ) : (
                  <TermRow term={t} onEdit={() => setEditing(t.id)} />
                )}
              </li>
            ))}
          </ul>
          <p className="type-meta flex items-center gap-1.5">
            <BookMarked aria-hidden className="size-3.5" />
            {shown.length} of {glossary.data?.total ?? items.length} entries
          </p>
        </>
      )}
    </section>
  );
}
