"use client";

import { ArrowUpRight, CircleAlert, CircleCheck, CircleDashed } from "lucide-react";
import { useState } from "react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { ErrorState, LoadingState } from "@/components/states";
import { Input } from "@/components/ui/input";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCountryPack, useRegionList, type CountryPack } from "./api";
import { SettingsFrame } from "./frame";

const SECTIONS = [
  ["regions", "Regions"], ["languages", "Languages and scripts"], ["calendar", "Festivals and calendars"], ["ad-codes", "Ad codes"],
  ["sources", "Data sources and licences"], ["gaps", "Known gaps"], ["sampling", "Audience sampling"],
] as const;

const TH = "px-3 py-2 text-left font-normal";

function Table({ children, min = "40rem" }: { children: React.ReactNode; min?: string }) {
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface">
      <table className="type-ledger w-full text-[13px]" style={{ minWidth: min }}>
        {children}
      </table>
    </div>
  );
}

function Regions({ pack }: { pack: CountryPack }) {
  const list = useRegionList(pack.country_code);
  const [filter, setFilter] = useState("");
  const items = (list.data?.items ?? []).filter((r) => `${r.name} ${r.code}`.toLowerCase().includes(filter.trim().toLowerCase()));
  const names = new Map(pack.languages.map((l) => [l.code, l.name]));
  return (
    <section aria-labelledby="regions" className="scroll-mt-24 space-y-3">
      <SectionTitle id="regions" meta={`${pack.regions.total} regions`}>
        Regions
      </SectionTitle>
      <p className="max-w-[68ch] text-[14px] text-ink-body">
        {pack.regions.states} states and {pack.regions.union_territories} union territories, coded by ISO 3166-2. Curated references, Census 2011 language shares and pageview series exist for{" "}
        <span className="font-mono text-[12.5px]">{pack.regions.demo_codes.join(", ")}</span>. The list below is read from the regions the app already serves, not copied into the pack.
      </p>
      <div className="space-y-1">
        <label htmlFor="pack-region-filter" className="type-meta block">
          Find a region
        </label>
        <Input id="pack-region-filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Kerala or IN-KL" className="h-10 w-64" />
      </div>
      {list.error ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : !list.data ? (
        <LoadingState label="Loading regions…" />
      ) : (
        <Table min="44rem">
          <thead>
            <tr className="border-b border-border text-ink-muted">
              <th scope="col" className={TH}>Code</th>
              <th scope="col" className={TH}>Region</th>
              <th scope="col" className={TH}>Kind</th>
              <th scope="col" className={TH}>Principal language</th>
              <th scope="col" className={TH}>Also</th>
            </tr>
          </thead>
          <tbody className="ledger-rules">
            {items.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-3 text-ink-muted">No region matches “{filter}”.</td></tr>
            )}
            {items.map((r) => {
              const extra = r.languages.filter((l) => l.role !== "primary");
              return (
                <tr key={r.code}>
                  <td className="px-3 py-2 font-mono text-[12px] text-ink-secondary">{r.code}</td>
                  <th scope="row" className="px-3 py-2 text-left font-normal text-ink">{r.name}</th>
                  <td className="px-3 py-2 text-ink-secondary">{r.kind === "union_territory" ? "Union territory" : "State"}</td>
                  <td className="px-3 py-2 text-ink-body">{r.primary_language ? names.get(r.primary_language) ?? r.primary_language : "n/a"}</td>
                  <td className="px-3 py-2 text-ink-secondary">{extra.length ? extra.map((l) => l.name).join(", ") : "none listed"}</td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </section>
  );
}

function Languages({ pack }: { pack: CountryPack }) {
  return (
    <section aria-labelledby="languages" className="scroll-mt-24 space-y-3">
      <SectionTitle id="languages" meta={`${pack.languages.length} languages, ${pack.scripts.length} scripts`}>
        Languages and scripts
      </SectionTitle>
      <p className="max-w-[68ch] text-[14px] text-ink-body">
        A language is listed for a region as principal or additional. That records official or widely used status; it is not a speaker share. Regional text is always set in type with its own script face, never drawn as an image.
      </p>
      <Table min="44rem">
        <thead>
          <tr className="border-b border-border text-ink-muted">
            <th scope="col" className={TH}>Code</th>
            <th scope="col" className={TH}>Language</th>
            <th scope="col" className={TH}>In its own script</th>
            <th scope="col" className={TH}>Script</th>
            <th scope="col" className={cn(TH, "text-right")}>Regions</th>
          </tr>
        </thead>
        <tbody className="ledger-rules">
          {pack.languages.map((l) => {
            const script = pack.scripts.find((s) => s.code === l.script);
            return (
              <tr key={l.code}>
                <td className="px-3 py-2 font-mono text-[12px] text-ink-secondary" title={l.code_standard === "iso639-3" ? "ISO 639-3 (no two-letter code)" : "ISO 639-1"}>{l.code}</td>
                <th scope="row" className="px-3 py-2 text-left font-normal text-ink">{l.name}</th>
                <td className="px-3 py-2 text-[14px] text-ink-body"><span lang={l.code} dir={l.direction}>{l.native_name}</span></td>
                <td className="px-3 py-2 text-ink-secondary">{script?.name ?? l.script} <span className="font-mono text-[11px] text-ink-muted">{l.script}</span>{l.direction === "rtl" ? ", right to left" : ""}</td>
                <td className="px-3 py-2 text-right text-ink-body">{l.region_count}</td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </section>
  );
}

function Calendars({ pack }: { pack: CountryPack }) {
  return (
    <section aria-labelledby="calendar" className="scroll-mt-24 space-y-3">
      <SectionTitle id="calendar">Festivals and calendars</SectionTitle>
      <ul className="ledger-rules rounded-card border border-border bg-surface">
        {pack.calendar_sources.map((c) => (
          <li key={c.id} className="space-y-1.5 px-4 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4">
              <p className="text-[14.5px] font-medium text-ink">{c.name}</p>
              <p className="type-meta">
                {[c.version ? `version ${c.version}` : null, c.as_of ? `as of ${c.as_of}` : null, c.entries != null ? `${c.entries} entries` : null].filter(Boolean).join(", ")}
              </p>
            </div>
            <p className="max-w-[68ch] text-[13.5px] text-ink-body">{c.description}</p>
            <p className="text-[13px] text-ink-secondary">Coverage: {c.coverage}</p>
            {c.limitations.length > 0 && (
              <details className="text-[13px] text-ink-secondary">
                <summary className="cursor-pointer text-ink-body">Limits ({c.limitations.length})</summary>
                <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
                  {c.limitations.map((x) => <li key={x}>{x}</li>)}
                </ul>
              </details>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function AdCodes({ pack }: { pack: CountryPack }) {
  const a = pack.ad_codes;
  return (
    <section aria-labelledby="ad-codes" className="scroll-mt-24 space-y-3">
      <SectionTitle id="ad-codes" meta={`${a.entries} clauses`}>
        Ad codes
      </SectionTitle>
      <dl className="ledger-rules rounded-card border border-border bg-surface">
        {[
          ["Publisher", a.publisher], ["Edition", a.edition], ["Index version", a.version], ["Retrieved", a.retrieved_on],
          ["Topics", a.topics.map((t) => t.replace(/_/g, " ")).join(", ")],
        ].map(([k, v]) => (
          <div key={k} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger text-[12.5px] text-ink-muted">{k}</dt>
            <dd className="text-[14px] text-ink-body">{v}</dd>
          </div>
        ))}
        <div className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
          <dt className="type-ledger text-[12.5px] text-ink-muted">Source file hash</dt>
          <dd className="min-w-0 break-all font-mono text-[11.5px] text-ink-secondary">{a.sha256}</dd>
        </div>
      </dl>
      <p className="text-[13px]">
        <a href={a.landing_page} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-ember-link hover:underline">
          ASCI code and guidelines <ArrowUpRight aria-hidden className="size-3.5" />
        </a>
      </p>
      <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-secondary">
        {a.limitations.map((x) => <li key={x}>{x}</li>)}
      </ul>
    </section>
  );
}

function Sources({ pack }: { pack: CountryPack }) {
  return (
    <section aria-labelledby="sources" className="scroll-mt-24 space-y-3">
      <SectionTitle id="sources" meta={`${pack.data_sources.length} sources`}>
        Data sources and licences
      </SectionTitle>
      <Table min="52rem">
        <thead>
          <tr className="border-b border-border text-ink-muted">
            <th scope="col" className={TH}>Source</th>
            <th scope="col" className={TH}>Used for</th>
            <th scope="col" className={TH}>Licence</th>
            <th scope="col" className={TH}>Retrieved</th>
          </tr>
        </thead>
        <tbody className="ledger-rules align-top">
          {pack.data_sources.map((s) => (
            <tr key={s.id}>
              <th scope="row" className="px-3 py-2.5 text-left font-normal text-ink">
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 hover:underline">
                    {s.name} <ArrowUpRight aria-hidden className="mt-0.5 size-3.5 shrink-0 text-ink-muted" />
                  </a>
                ) : (
                  s.name
                )}
              </th>
              <td className="max-w-64 px-3 py-2.5 text-ink-body">{s.used_for}</td>
              <td className="max-w-80 px-3 py-2.5">
                <p className="inline-flex items-center gap-1.5 text-ink-body">
                  {s.licence_status === "checked" ? <CircleCheck aria-hidden className="size-3.5 shrink-0 text-success" /> : <CircleDashed aria-hidden className="size-3.5 shrink-0 text-ink-muted" />}
                  {s.licence_status === "checked" ? (s.licence ?? "Checked") : "Not checked"}
                </p>
                <p className="mt-0.5 text-[12.5px] text-ink-secondary">
                  {s.licence_status === "checked" && s.licence_checked_on ? `Read ${s.licence_checked_on}. ` : ""}
                  {s.licence_note}
                </p>
              </td>
              <td className="px-3 py-2.5 text-ink-secondary">{s.retrieved_on ?? "Queried live"}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </section>
  );
}

function Gaps({ pack }: { pack: CountryPack }) {
  return (
    <section aria-labelledby="gaps" className="scroll-mt-24 space-y-3">
      <SectionTitle id="gaps" meta={`${pack.known_gaps.length}`}>
        Known gaps
      </SectionTitle>
      <ul className="ledger-rules rounded-card border border-border bg-surface">
        {pack.known_gaps.map((g) => (
          <li key={g} className="flex items-start gap-2.5 px-4 py-2.5 text-[13.5px] text-ink-body">
            <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
            <span>
              <span className="sr-only">Gap: </span>
              {g}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Sampling({ pack }: { pack: CountryPack }) {
  return (
    <section aria-labelledby="sampling" className="scroll-mt-24 space-y-3">
      <SectionTitle id="sampling">Audience sampling</SectionTitle>
      <p className="max-w-[68ch] text-[14px] text-ink-body">Synthetic panels vary only along these dimensions. They are simulations, not survey respondents.</p>
      <dl className="ledger-rules rounded-card border border-border bg-surface">
        {pack.sampling_dimensions.map((d) => (
          <div key={d.name} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger text-[12.5px] text-ink-muted">{d.name.replace(/_/g, " ")}</dt>
            <dd className="text-[14px] text-ink-body">{d.values.length ? d.values.join(", ") : d.description}</dd>
          </div>
        ))}
        <div className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
          <dt className="type-ledger text-[12.5px] text-ink-muted">Never sampled</dt>
          <dd className="text-[14px] text-ink-body">{pack.never_sampled.join(", ")}</dd>
        </div>
      </dl>
    </section>
  );
}

function PackView({ pack }: { pack: CountryPack }) {
  const seed = pack.seed;
  return (
    <div className="space-y-9">
      <ContextPanel title="On this page">
        <nav aria-label="Sections of the country pack">
          <ul className="space-y-0.5">
            {SECTIONS.map(([id, label]) => (
              <li key={id}>
                <a href={`#${id}`} className="flex h-9 items-center rounded-lg px-2.5 text-[13.5px] text-ink-secondary hover:bg-surface-muted hover:text-ink">
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <p className="text-[12.5px] text-ink-muted">Reports cite this pack as “{pack.citation}”.</p>
      </ContextPanel>

      <header className="space-y-2">
        <h2 className="type-title text-[26px] text-ink">
          {pack.name} <span className="font-mono text-[15px] font-normal text-ink-secondary">v{pack.version}</span>
        </h2>
        <p className="max-w-[68ch] text-[14px] text-ink-body">{pack.notes}</p>
        <dl className="type-ledger flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-ink-muted">
          <div className="flex gap-1.5">
            <dt>Fingerprint</dt>
            <dd className="font-mono text-ink-secondary" title={pack.content_sha256}>{pack.content_sha256.slice(0, 12)}</dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt>In this database</dt>
            <dd className="flex items-center gap-1 text-ink-secondary">
              {seed.loaded ? <CircleCheck aria-hidden className="size-3.5 text-success" /> : <CircleAlert aria-hidden className="size-3.5 text-warning" />}
              {seed.regions_in_database} of {seed.regions_expected} regions, {seed.languages_in_database} of {seed.languages_expected} languages, {seed.moments_in_database} of {seed.moments_expected} moments
              {seed.pack_loaded_at ? `, loaded ${formatDate(seed.pack_loaded_at)}` : ""}
            </dd>
          </div>
        </dl>
        {!seed.loaded && (
          <p role="alert" className="text-[13px] text-warning">
            The reference tables in this database are incomplete, so region pickers and profiles may be short. Run the reference-data seed (scripts.seed_reference_data) on the API host.
          </p>
        )}
      </header>

      <Regions pack={pack} />
      <Languages pack={pack} />
      <Calendars pack={pack} />
      <AdCodes pack={pack} />
      <Sources pack={pack} />
      <Gaps pack={pack} />
      <Sampling pack={pack} />
    </div>
  );
}

/** Country Packs (Tier 2 feature 57): the versioned India pack, described from the reference data that already exists. */
export function CountryPackScreen({ country = "IN" }: { country?: string }) {
  const pack = useCountryPack(country);
  return (
    <SettingsFrame needsWorkspace={false}>
      {() =>
        pack.error ? (
          <ErrorState error={pack.error} onRetry={() => void pack.refetch()} />
        ) : !pack.data ? (
          <LoadingState label="Loading the country pack…" />
        ) : (
          <PackView pack={pack.data} />
        )
      }
    </SettingsFrame>
  );
}
