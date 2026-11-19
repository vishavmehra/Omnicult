"use client";

import { ExternalLink, LoaderCircle, RefreshCw } from "lucide-react";
import { useId, useState } from "react";

import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Labelled, NativeSelect } from "@/features/lens/parts";
import { SectionTitle } from "@/features/workspaces/parts";
import { ApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";

import { useCategoryShelf, useRefreshShelf, type CategoryShelf, type ShelfEntity, type ShelfRegion } from "./api";
import { DirectionTag, SourceChip, Sparkline, monthName, num, percent } from "./parts";

function Attention({ entity }: { entity: ShelfEntity }) {
  const a = entity.attention;
  if (!a) return <p className="text-[12.5px] text-ink-muted">{entity.attention_note}</p>;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <Sparkline series={a.series} label={`${entity.label}, ${a.language_name} Wikipedia`} width={108} height={28} />
      <div className="min-w-0 space-y-0.5">
        <DirectionTag direction={a.direction} />
        <p className="type-ledger text-[12.5px] text-ink-secondary">
          {a.change == null
            ? `${a.months} ${a.months === 1 ? "month" : "months"} of readings: too few to compare a year with the year before`
            : `${percent(a.change)} on the year before, ${a.recent_mean == null ? "n/a" : num.format(a.recent_mean)} views a month`}
        </p>
      </div>
      <ConfidenceIndicator level={a.confidence} />
      <span className="type-meta">
        {a.language_name} article, last month {monthName(a.series[a.series.length - 1].month)}
        {a.normalised ? ", as a share of the edition's readership" : ", raw views"}
      </span>
    </div>
  );
}

function EntityRow({ entity }: { entity: ShelfEntity }) {
  const facts = [
    entity.founded_year ? `Founded ${entity.founded_year}` : null,
    entity.places.length ? `${entity.kind === "brand" ? "Headquarters" : "Place"} ${entity.places.map((p) => p.label).join(", ")}` : null,
    `${entity.wikipedia_languages} Wikipedia ${entity.wikipedia_languages === 1 ? "edition" : "editions"}`,
  ].filter(Boolean);
  return (
    <li className="space-y-1.5 px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-[14.5px] font-medium text-ink">{entity.label}</p>
        <Tag className="border-border text-ink-secondary">{entity.kind === "brand" ? "Brand or business" : "Product"}</Tag>
        {entity.description && <p className="min-w-0 text-[13px] text-ink-secondary">{entity.description}</p>}
      </div>
      <p className="type-ledger text-[13px] text-ink-body">
        {facts.join(" · ")}
        {entity.basis && <span className="text-ink-secondary"> ({entity.basis})</span>}
      </p>
      <Attention entity={entity} />
      <div className="flex flex-wrap items-center gap-2">
        {entity.sources.map((s) => (
          <SourceChip key={s.label} label={s.label} url={s.url} />
        ))}
        {entity.website && (
          <a href={entity.website} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12.5px] text-ink-secondary underline decoration-border-strong underline-offset-2 hover:text-ink">
            Official site <ExternalLink aria-hidden className="size-3" />
          </a>
        )}
        {entity.unknown.length > 0 && <span className="text-[12.5px] text-ink-muted">Not recorded: {entity.unknown.join(", ")}</span>}
      </div>
    </li>
  );
}

function RegionSection({ region }: { region: ShelfRegion }) {
  return (
    <section aria-labelledby={`shelf-${region.region_code}`} className="space-y-3">
      <SectionTitle id={`shelf-${region.region_code}`} meta={`${region.entities.length} ${region.entities.length === 1 ? "entry" : "entries"}`}>
        {region.region_name}
      </SectionTitle>
      {region.entities.length > 0 && (
        <ul className="ledger-rules rounded-card border border-border bg-surface">
          {region.entities.map((e) => (
            <EntityRow key={e.entity_id} entity={e} />
          ))}
        </ul>
      )}
      {region.gaps.map((g) => (
        <p key={g} className="rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3 text-[13.5px] text-ink-secondary">
          {g}
        </p>
      ))}
    </section>
  );
}

function CategoryPicker({ shelf, pack, onPack }: { shelf: CategoryShelf; pack: string; onPack(key: string): void }) {
  const id = useId();
  return (
    <Labelled label="Category" htmlFor={id}>
      <NativeSelect id={id} value={pack} onChange={(e) => onPack(e.target.value)}>
        {!pack && <option value="">Choose a category</option>}
        {shelf.packs.map((p) => (
          <option key={p.key} value={p.key}>
            {p.label}
          </option>
        ))}
      </NativeSelect>
    </Labelled>
  );
}

export function CategoryShelfView({ campaignId }: { campaignId: string }) {
  const [chosen, setChosen] = useState<string | null>(null);
  const shelf = useCategoryShelf(campaignId, [], chosen);
  const refresh = useRefreshShelf(campaignId);
  const data = shelf.data;
  const pack = chosen ?? data?.category.pack_key ?? "";
  const error = refresh.error instanceof ApiError ? refresh.error : null;

  if (shelf.isError) return <ErrorState error={shelf.error} onRetry={() => void shelf.refetch()} />;
  if (!data) return <LoadingState label="Reading the Category Shelf…" />;
  const live = data.mode === "live";
  const refreshButton = (
    <Button type="button" variant="outline" onClick={() => refresh.mutate({ pack: pack || null, regions: [] })} disabled={refresh.isPending || !pack || (data.category.pack_key !== null && !data.can_refresh)}>
      {refresh.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <RefreshCw aria-hidden />}
      {refresh.isPending ? "Reading…" : data.snapshot ? "Read the shelf again" : "Read the shelf"}
    </Button>
  );
  const placed = data.regions.reduce((n, r) => n + r.entities.length, 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <CategoryPicker shelf={data} pack={pack} onPack={setChosen} />
        {refreshButton}
        {refresh.isPending && (
          <p role="status" className="text-[12.5px] text-ink-secondary">
            {live ? "Asking Wikidata and Wikipedia, paced to stay polite. This can take up to a minute." : "Reading the recording."}
          </p>
        )}
      </div>
      {data.category.note && <p className="text-[13.5px] text-ink-body">{data.category.note}</p>}
      {data.category.text && data.category.status === "matched" && (
        <p className="text-[13px] text-ink-secondary">
          Category from the brand kit: &ldquo;{data.category.text}&rdquo;, read as {data.category.pack_label}.
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-lg border border-danger/35 bg-danger-soft/60 px-3 py-2 text-[13px] text-ink">
          {error.message}
          {error.details.map((d) => ` ${d.message}`).join("")}
        </p>
      )}

      {!data.snapshot ? (
        <EmptyState
          title="The shelf has not been read yet"
          description={
            pack
              ? "Reading asks Wikidata which brands and products it records in this category and which state it links them to. Fields it does not hold stay unknown."
              : "Choose a category first. Market Lens covers a short list and does not guess one."
          }
          action={pack && data.can_refresh ? refreshButton : undefined}
        />
      ) : (
        <>
          <p className="type-ledger text-[13.5px] text-ink-body" aria-live="polite">
            {data.snapshot.entities} brands and products read from Wikidata; {placed} placed in the campaign&apos;s states, {data.unplaced.length} not linked to any of them, {data.snapshot.excluded} left out.
            Version {data.snapshot.version}, read {formatDateTime(data.snapshot.taken_at)}.
          </p>
          {data.regions.map((r) => (
            <RegionSection key={r.region_code} region={r} />
          ))}
          {data.unplaced.length > 0 && (
            <details className="rounded-card border border-border bg-surface px-4 py-3 text-[13.5px]">
              <summary className="cursor-pointer font-medium text-ink">Not linked to these states ({data.unplaced.length})</summary>
              <p className="mt-2 text-[13px] text-ink-secondary">Wikidata records no state for these, or a state outside the campaign. They are listed because they belong to the category.</p>
              <ul className="ledger-rules mt-2 rounded-card border border-border">
                {data.unplaced.map((e) => (
                  <li key={e.entity_id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-3 py-2">
                    <span className="min-w-0 text-ink">
                      {e.label} <span className="text-[12.5px] text-ink-secondary">{e.description}</span>
                    </span>
                    <span className="type-ledger text-[12.5px] text-ink-secondary">
                      {e.places.length ? e.places.map((p) => p.label).join(", ") : "No place recorded"} · {e.wikipedia_languages} editions ·{" "}
                      <a href={e.wikidata_url} target="_blank" rel="noreferrer" className="underline decoration-border-strong underline-offset-2 hover:text-ink">
                        Wikidata
                      </a>
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {data.excluded.length > 0 && (
            <details className="rounded-card border border-border bg-surface px-4 py-3 text-[13.5px]">
              <summary className="cursor-pointer font-medium text-ink">Left out ({data.excluded.length})</summary>
              <p className="mt-2 max-w-[78ch] text-[13px] text-ink-secondary">{data.relevance_rule}</p>
              <ul className="ledger-rules mt-2 rounded-card border border-border">
                {data.excluded.map((x) => (
                  <li key={x.entity_id} className="flex flex-wrap items-baseline justify-between gap-x-4 px-3 py-1.5 text-[13px]">
                    <a href={x.url} target="_blank" rel="noreferrer" className="text-ink underline decoration-border-strong underline-offset-2">
                      {x.label}
                    </a>
                    <span className="text-ink-secondary">{x.reason}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {data.gaps.length > 0 && (
            <ul className="space-y-0.5 text-[13px] text-ink-secondary">
              {data.gaps.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          )}
          <details className="rounded-card border border-border bg-surface px-4 py-3 text-[13.5px]">
            <summary className="cursor-pointer font-medium text-ink">How the shelf is built</summary>
            <div className="mt-2 space-y-2 text-ink-body">
              <p className="max-w-[78ch]">{data.ranking}</p>
              <ul className="list-disc space-y-0.5 pl-5 text-ink-secondary">
                {data.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          </details>
        </>
      )}
    </div>
  );
}
