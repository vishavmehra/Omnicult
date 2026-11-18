"use client";

import { CircleCheck, CircleDashed } from "lucide-react";
import type { ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  REQUIRED_LABEL,
  STATUS_LABEL,
  dayLabel,
  daysBetween,
  formatMoney,
  languageName,
  scriptName,
  type Brief,
  type BriefContent,
  type Region,
} from "./types";

const NOT_SET = "Not set";

function Muted({ children }: { children: ReactNode }) {
  return <span className="text-ink-muted">{children}</span>;
}

/** Ruled rows for short facts. Empty values read as "Not set", never as a blank. */
function Facts({ rows }: { rows: { label: string; value: ReactNode | null | undefined; lang?: string }[] }) {
  return (
    <dl className="ledger-rules rounded-card border border-border bg-surface">
      {rows.map((r) => (
        <div key={r.label} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
          <dt className="type-ledger text-[12.5px] text-ink-muted">{r.label}</dt>
          <dd lang={r.lang} className="min-w-0 text-[14px] text-ink-body">
            {r.value ?? <Muted>{NOT_SET}</Muted>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Block({ id, title, meta, children }: { id: string; title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id}>
      <SectionTitle id={id} meta={meta}>
        {title}
      </SectionTitle>
      {children}
    </section>
  );
}

function Table({ head, children, label }: { head: string[]; children: ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface">
      <table aria-label={label} className="type-ledger w-full min-w-[30rem] text-left text-[13.5px]">
        <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="px-3.5 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}

const Cell = ({ children, className }: { children: ReactNode; className?: string }) => <td className={cn("px-3.5 py-2.5 align-top text-ink-body", className)}>{children}</td>;

function Chips({ items, empty = NOT_SET }: { items: string[]; empty?: string }) {
  if (!items.length) return <Muted>{empty}</Muted>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((t) => (
        <li key={t} className="rounded-stamp border border-border-strong/45 bg-surface-raised px-1.5 py-0.5 text-[12.5px] text-ink">
          {t}
        </li>
      ))}
    </ul>
  );
}

/** Completeness: what the saved brief still lacks, as words and icons. The rule lives in the API. */
export function Completeness({ brief }: { brief: Pick<Brief, "completeness"> }) {
  const c = brief.completeness;
  const missing = new Set<string>(c.missing);
  return (
    <div className="space-y-2">
      <p className="text-[13px] text-ink-secondary">
        <span className="type-ledger tabular-nums text-ink">
          {c.filled} of {c.required}
        </span>{" "}
        required parts filled{c.complete ? ": the brief is complete." : "."}
      </p>
      <ul className="flex flex-wrap gap-1.5">
        {(Object.keys(REQUIRED_LABEL) as (keyof typeof REQUIRED_LABEL)[]).map((k) => (
          <li key={k}>
            <Tag className={missing.has(k) ? "border-dashed border-warning/40 bg-warning-soft text-warning" : "border-success/25 bg-success-soft text-success"}>
              {missing.has(k) ? <CircleDashed aria-hidden /> : <CircleCheck aria-hidden />}
              <span className="sr-only">{missing.has(k) ? "Missing: " : "Filled: "}</span>
              {REQUIRED_LABEL[k]}
            </Tag>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Which version is on screen, when it was saved, and where the content came from. */
export function VersionBar({ brief, viewing }: { brief: Brief; viewing?: { version: number; createdAt: string; note: string | null } }) {
  const fixture = brief.provenance.source === "demo_fixture";
  return (
    <div className="space-y-2.5 rounded-card border border-border bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="type-ledger inline-flex items-center gap-1.5 rounded-stamp border border-border-strong/45 bg-surface-raised px-2 py-0.5 text-[12.5px] font-medium text-ink">
          {brief.saved ? `Brief version ${viewing?.version ?? brief.version}` : "No brief saved yet"}
        </span>
        {viewing ? (
          <span className="text-[12.5px] text-ink-secondary">
            An earlier version, saved {formatDateTime(viewing.createdAt)}. Version {brief.version} is current.
          </span>
        ) : brief.saved && brief.created_at ? (
          <span className="text-[12.5px] text-ink-secondary" title={formatDateTime(brief.created_at)}>
            Saved {formatRelative(brief.created_at)} · {brief.version_count} {brief.version_count === 1 ? "version" : "versions"}
          </span>
        ) : (
          <span className="text-[12.5px] text-ink-secondary">
            This shows what the campaign record already says. Saving the brief starts version 1.
          </span>
        )}
        <Tag className="ml-auto border-border bg-surface-muted text-ink-secondary">{STATUS_LABEL[brief.content.status]}</Tag>
      </div>
      {(viewing?.note ?? brief.change_note) && <p className="text-[13px] text-ink-body">“{viewing?.note ?? brief.change_note}”</p>}
      <Completeness brief={brief} />
      {fixture && <p className="text-[11.5px] text-ink-muted">Source: demonstration fixture</p>}
    </div>
  );
}

const nameOf = (regions: Region[] | undefined, code: string) => regions?.find((r) => r.code === code)?.name ?? code;

/** The brief as a document. Read-only; editing is a separate mode. */
export function BriefDocument({ content, regions, sample }: { content: BriefContent; regions: Region[] | undefined; sample: boolean }) {
  const c = content;
  const rows = [...(c.regions.origin ? [{ code: c.regions.origin, role: "Origin" }] : []), ...c.regions.targets.map((code) => ({ code, role: "Target" }))];
  const budget = c.budget;
  const allocated = budget ? Object.values(budget.by_region).reduce((a, b) => a + b, 0) : 0;

  return (
    <article aria-label="Campaign brief" className="space-y-8">
      <Block id="b-objective" title="Objective">
        {c.objective ? <p className="max-w-[68ch] text-[16px] leading-relaxed text-ink">{c.objective}</p> : <Muted>No objective stated.</Muted>}
        {c.primary_message && (
          <p className="mt-3 max-w-[68ch] text-[14px] text-ink-body">
            <span className="type-meta mr-2">Primary message</span>
            {c.primary_message}
          </p>
        )}
      </Block>

      <Block id="b-product" title="Product and audience">
        <Facts
          rows={[
            { label: "Product", value: c.product ? <span className="font-medium text-ink">{c.product.name}</span> : null },
            { label: "Description", value: c.product?.description },
            {
              label: "Net weight and price",
              value: c.product && (c.product.net_weight_g || c.product.price) ? (
                <span className="type-ledger tabular-nums">
                  {c.product.net_weight_g ? `${c.product.net_weight_g} g` : null}
                  {c.product.net_weight_g && c.product.price ? " · " : null}
                  {c.product.price ? formatMoney(c.product.price.currency, c.product.price.amount) : null}
                  {c.product.price_note ? <span className="text-ink-muted"> ({c.product.price_note})</span> : null}
                </span>
              ) : null,
            },
            { label: "Audience", value: c.target_audience?.summary },
            { label: "Age bands", value: c.target_audience?.age_bands.length ? <Chips items={c.target_audience.age_bands} /> : null },
            { label: "City tiers", value: c.target_audience?.city_tiers.length ? <Chips items={c.target_audience.city_tiers.map((t) => t.replace("tier", "Tier "))} /> : null },
            { label: "Never targeted by", value: c.target_audience?.targeting_exclusions },
          ]}
        />
      </Block>

      <Block id="b-regions" title="Regions, languages and scripts" meta="Region codes follow ISO 3166-2:IN">
        {rows.length === 0 ? (
          <Muted>No origin or target regions set.</Muted>
        ) : (
          <Table label="Regions, languages and scripts" head={["Region", "Role", "Languages", "Scripts"]}>
            {rows.map((r) => (
              <tr key={r.code}>
                <Cell>
                  <span className="font-medium text-ink">{nameOf(regions, r.code)}</span> <span className="font-mono text-[11.5px] text-ink-muted">{r.code}</span>
                </Cell>
                <Cell>{r.role}</Cell>
                <Cell>
                  {c.languages[r.code]?.length ? (
                    c.languages[r.code]!.map((l) => `${languageName(l)} (${l})`).join(", ")
                  ) : (
                    <Muted>None set</Muted>
                  )}
                </Cell>
                <Cell>{c.scripts[r.code]?.length ? c.scripts[r.code]!.map(scriptName).join(", ") : <Muted>None set</Muted>}</Cell>
              </tr>
            ))}
          </Table>
        )}
      </Block>

      <Block id="b-channels" title="Channels">
        {c.channels.length === 0 ? (
          <Muted>No channels yet.</Muted>
        ) : (
          <Table label="Channels" head={["Channel", "Format", "Creative"]}>
            {c.channels.map((ch) => (
              <tr key={ch.id}>
                <Cell className="font-medium text-ink">{ch.name}</Cell>
                <Cell>{ch.format ?? <Muted>{NOT_SET}</Muted>}</Cell>
                <Cell className="font-mono text-[11.5px] break-all text-ink-secondary">{ch.creative_ref ?? <Muted>None</Muted>}</Cell>
              </tr>
            ))}
          </Table>
        )}
      </Block>

      <Block id="b-budget" title="Budget">
        {!budget ? (
          <Muted>No budget set.</Muted>
        ) : (
          <div className="space-y-2.5">
            <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="type-title text-[26px] tabular-nums text-ink">{formatMoney(budget.currency, budget.total)}</span>
            </p>
            {budget.note && <p className="text-[13px] text-ink-secondary">{budget.note}</p>}
            {Object.keys(budget.by_region).length > 0 && (
              <Table label="Budget by region" head={["Region", "Amount", "Share of total"]}>
                {Object.entries(budget.by_region).map(([code, amount]) => (
                  <tr key={code}>
                    <Cell className="font-medium text-ink">{nameOf(regions, code)}</Cell>
                    <Cell className="tabular-nums">{formatMoney(budget.currency, amount)}</Cell>
                    <Cell className="tabular-nums">{budget.total ? `${Math.round((amount / budget.total) * 100)}%` : "n/a"}</Cell>
                  </tr>
                ))}
              </Table>
            )}
            {budget.total > allocated + 0.005 && Object.keys(budget.by_region).length > 0 && (
              <p className="text-[12.5px] text-ink-muted">{formatMoney(budget.currency, budget.total - allocated)} of the total is not assigned to a region.</p>
            )}
            {(sample || budget.sample) && <p className="text-[11.5px] text-ink-muted">Source: sample figures</p>}
          </div>
        )}
      </Block>

      <Block id="b-dates" title="Campaign dates" meta={c.dates?.timezone}>
        {!c.dates ? (
          <Muted>No dates set.</Muted>
        ) : (
          <div className="space-y-2.5">
            <p className="text-[14px] text-ink-body">
              <span className="type-ledger tabular-nums font-medium text-ink">
                {dayLabel(c.dates.start)} to {dayLabel(c.dates.end)}
              </span>{" "}
              <span className="text-ink-secondary">({daysBetween(c.dates.start, c.dates.end)} days)</span>
            </p>
            {c.dates.key_moments.length > 0 && (
              <Table label="Key moments" head={["Date", "Moment", "Regions", "Sources"]}>
                {[...c.dates.key_moments]
                  .sort((a, b) => a.date.localeCompare(b.date))
                  .map((m) => (
                    <tr key={m.id}>
                      <Cell className="type-ledger whitespace-nowrap tabular-nums">{dayLabel(m.date)}</Cell>
                      <Cell>
                        <span className="font-medium text-ink">{m.name}</span>
                        {m.note && <span className="mt-0.5 block text-[12.5px] text-ink-secondary">{m.note}</span>}
                      </Cell>
                      <Cell>{m.region_codes.length ? m.region_codes.map((r) => nameOf(regions, r)).join(", ") : <Muted>All</Muted>}</Cell>
                      <Cell className="text-[12.5px]">{m.source_ids.length ? m.source_ids.join(", ") : <Muted>None</Muted>}</Cell>
                    </tr>
                  ))}
              </Table>
            )}
            {c.dates.sources.length > 0 && (
              <ul className="space-y-1 text-[12.5px] text-ink-secondary">
                {c.dates.sources.map((s) => (
                  <li key={s.id}>
                    <span className="font-mono text-[11.5px] text-ink-muted">{s.id}</span> {s.publisher ? `${s.publisher}: ` : ""}
                    {s.url ? (
                      <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-rose underline-offset-2 hover:underline">
                        {s.title}
                      </a>
                    ) : (
                      s.title
                    )}
                    {s.retrieved_at ? ` (retrieved ${dayLabel(s.retrieved_at)})` : ""}
                  </li>
                ))}
              </ul>
            )}
            {c.dates.note && <p className="text-[12.5px] text-ink-muted">{c.dates.note}</p>}
          </div>
        )}
      </Block>

      <Block id="b-metric" title="Success metric">
        {!c.success_metric ? (
          <Muted>No success metric set.</Muted>
        ) : (
          <div className="space-y-2">
            <Table label="Success metrics" head={["Metric", "Definition", "Target"]}>
              {[{ ...c.success_metric.primary, primary: true }, ...c.success_metric.secondary.map((m) => ({ ...m, primary: false }))].map((m) => (
                <tr key={m.id}>
                  <Cell className="whitespace-nowrap">
                    <span className="font-medium text-ink">{m.id.replace(/[_-]/g, " ")}</span>
                    {m.primary && <span className="type-meta ml-1.5">primary</span>}
                  </Cell>
                  <Cell>{m.definition}</Cell>
                  <Cell className="type-ledger whitespace-nowrap">{m.target ?? <Muted>No target</Muted>}</Cell>
                </tr>
              ))}
            </Table>
            {c.success_metric.note && <p className="text-[12.5px] text-ink-muted">{c.success_metric.note}</p>}
          </div>
        )}
      </Block>

      <Block id="b-cta" title="Call to action">
        <Facts
          rows={[
            { label: "In English", value: c.cta?.text_en },
            { label: "Festival hook", value: c.cta?.festival_hook },
            {
              label: "Original line",
              lang: c.cta?.original ? c.languages[c.cta.original.region_code]?.[0] : undefined,
              value: c.cta?.original ? (
                <span>
                  {c.cta.original.text}
                  {c.cta.original.translation_en && <span lang="en" className="block text-[12.5px] text-ink-secondary">English: {c.cta.original.translation_en}</span>}
                  <span className="type-meta block">{nameOf(regions, c.cta.original.region_code)}</span>
                </span>
              ) : null,
            },
          ]}
        />
      </Block>

      <Block id="b-constraints" title="Constraints">
        {c.constraints.length === 0 ? (
          <Muted>No constraints stated.</Muted>
        ) : (
          <ul className="ledger-rules rounded-card border border-border bg-surface">
            {c.constraints.map((t) => (
              <li key={t} className="px-4 py-2.5 text-[14px] text-ink-body">
                {t}
              </li>
            ))}
          </ul>
        )}
      </Block>
    </article>
  );
}
