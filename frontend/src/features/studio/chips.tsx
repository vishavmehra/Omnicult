"use client";

import { ArrowRight, MessageSquareText, Sparkles } from "lucide-react";
import { useState } from "react";

import { Tag } from "@/components/evidence/badges";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/states";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

import { useApplyChip, useChips, useGenerateChips, useRegions } from "./api";
import { ClaimsDisclosure } from "./claims";
import { formatCost } from "./model";
import { MutationError, NativeSelect, useStudio } from "./parts";
import type { Chip, ChipsGenerated, CreativeElement } from "./types";

/** What a chip would change, as text: the whole new line, or a phrase swapped for another. */
function ChangePreview({ chip, current, lang }: { chip: Chip; current: string; lang?: string }) {
  const swap = chip.operation_type === "swap_reference";
  const from = swap ? chip.change.from_text : current;
  const to = swap ? chip.change.to_text : chip.change.value;
  return (
    <div className="grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-start sm:gap-3">
      <p lang={lang} className="rounded-md bg-surface-muted/70 px-2.5 py-1.5 text-[13.5px] leading-snug text-ink-secondary">
        <span className="type-meta block">{swap ? "Replaces" : "Now"}</span>
        {from}
      </p>
      <ArrowRight aria-hidden className="mt-4 hidden size-4 text-ink-muted sm:block" />
      <p lang={lang} className="rounded-md bg-surface-muted/70 px-2.5 py-1.5 text-[13.5px] leading-snug text-ink">
        <span className="type-meta block">{swap ? "With" : "Proposed"}</span>
        {to}
      </p>
    </div>
  );
}

function ChipCard({ chip, element, selectedVersionId, onApplied }: { chip: Chip; element: CreativeElement; selectedVersionId: string; onApplied(versionId: string): void }) {
  const { campaignId, workspaceId } = useStudio();
  const apply = useApplyChip(campaignId);
  const applied = chip.status === "applied";
  const cost = formatCost(chip.estimated_cost_usd);
  const current = typeof element.value === "string" ? element.value : "";
  return (
    <article className="space-y-2.5 rounded-lg border border-border bg-surface px-3.5 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <h4 className="text-[14px] font-semibold text-ink">{chip.title}</h4>
          <p className="text-[13px] text-ink-body">{chip.expected_effect}</p>
        </div>
        {applied ? (
          <span className="inline-flex items-center gap-2 text-[12.5px] text-ink-secondary">
            Applied
            {chip.applied_version_id && (
              <Button size="sm" variant="outline" onClick={() => onApplied(chip.applied_version_id!)}>
                Open that version
              </Button>
            )}
          </span>
        ) : (
          <Button
            size="sm"
            disabled={apply.isPending}
            onClick={() => apply.mutate({ chipId: chip.id, versionId: selectedVersionId }, { onSuccess: (r) => { toast.success("Chip applied as a new version"); onApplied(r.version.id); } })}
          >
            {apply.isPending ? "Applying…" : "Apply chip"}
          </Button>
        )}
      </div>
      <ChangePreview chip={chip} current={current} lang={element.language ?? undefined} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title="Written by a model. Not an observed fact.">
          <MessageSquareText aria-hidden />
          Model interpretation
        </Tag>
        <p className="min-w-0 flex-1 text-[13px] text-ink-body">{chip.reason}</p>
      </div>
      <ClaimsDisclosure workspaceId={workspaceId} claimIds={chip.claim_ids} />
      <p className="type-meta">
        {chip.reversible ? "Applying makes a new version; restore the previous one to undo it." : "Cannot be undone by restoring."}
        {cost && <> · {cost} (estimate)</>}
        {chip.model_id && <> · {chip.model_id}</>}
        {chip.prompt_version && <> · prompt {chip.prompt_version}</>}
      </p>
      {apply.isError && <MutationError error={apply.error} />}
    </article>
  );
}

/**
 * Tweak Chips for one element of the selected version. The model proposes; code has already dropped proposals that cite
 * unknown claims, break a lock, remove a protected term, use a prohibited one or leave the element's script. Each chip that
 * is left shows its reason and opens the claims it cites; applying makes a new version and a locked element refuses it.
 */
export function ChipsPanel({ element, versionId, versionRegion, onOpenVersion }: { element: CreativeElement; versionId: string; versionRegion: string | null; onOpenVersion(id: string): void }) {
  const { campaignId } = useStudio();
  const regions = useRegions();
  const [region, setRegion] = useState(versionRegion ?? "");
  const [last, setLast] = useState<ChipsGenerated | null>(null);
  const chips = useChips(campaignId, versionId, element.id, true);
  const generate = useGenerateChips(campaignId);
  const items = chips.data?.items ?? [];

  return (
    <section aria-label={`Tweak chips for ${element.id}`} className="space-y-3 border-t border-border pt-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[12rem] flex-1 space-y-1">
          <label htmlFor={`chip-region-${element.id}`} className="block text-[12.5px] font-medium text-ink">
            Region whose claims ground the chips
          </label>
          <NativeSelect id={`chip-region-${element.id}`} value={region} onChange={(e) => setRegion(e.target.value)} disabled={regions.isPending}>
            <option value="">{regions.isPending ? "Loading regions…" : "Choose a region"}</option>
            {regions.data?.items.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name} ({r.code})
              </option>
            ))}
          </NativeSelect>
        </div>
        <Button
          variant="outline"
          disabled={!region || generate.isPending}
          onClick={() => generate.mutate({ versionId, elementId: element.id, regionCode: region }, { onSuccess: setLast })}
        >
          <Sparkles aria-hidden />
          {generate.isPending ? "Asking the model…" : items.length ? "Suggest more chips" : "Suggest chips"}
        </Button>
      </div>
      <p className="type-meta">Grounded in the region&apos;s claims. Nothing changes until you apply a chip.</p>

      {generate.isPending && <LoadingState label="Proposing chips and checking them against the claims, locks and glossary…" className="py-2" />}
      {generate.isError && <MutationError error={generate.error} onRetry={() => generate.reset()} />}
      {last && !generate.isPending && (
        <div role="status" className="rounded-md border border-border bg-surface-muted/60 px-3 py-2 text-[12.5px] text-ink-secondary">
          <p>
            {last.chips.length} {last.chips.length === 1 ? "chip" : "chips"} kept
            {last.dropped > 0 ? `; ${last.dropped} dropped by code checks (unknown claims, locks, protected or prohibited terms, wrong script).` : "."}
          </p>
          {last.notes.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      )}

      {chips.isError && <MutationError error={chips.error} onRetry={() => void chips.refetch()} />}
      {chips.isPending ? (
        <LoadingState label="Loading saved chips…" className="py-2" />
      ) : items.length === 0 ? (
        <p className={cn("rounded-md border border-dashed border-border-strong/50 px-3 py-2.5 text-[13px] text-ink-secondary")}>
          No chips for this element in this version yet. Choose a region and ask for suggestions.
        </p>
      ) : (
        <div className="space-y-2.5">
          {items.map((chip) => (
            <ChipCard key={chip.id} chip={chip} element={element} selectedVersionId={versionId} onApplied={onOpenVersion} />
          ))}
        </div>
      )}
    </section>
  );
}
