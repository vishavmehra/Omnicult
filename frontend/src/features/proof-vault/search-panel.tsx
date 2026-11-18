"use client";

import { ArrowUpRight, Search } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { EvidenceLabel, RetrievalBadge, Tag } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { workspaceHref, type WorkspaceKey } from "@/components/shell/workspaces";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

import { useProofSearch, useRegions } from "./api";
import { SELECT_CLASS } from "./parts";
import type { SearchHit } from "./types";

const KIND: Record<SearchHit["kind"], { label: string; workspace: WorkspaceKey | null }> = {
  claim: { label: "Claim", workspace: null },
  claim_source: { label: "Claim source", workspace: null },
  evidence: { label: "Evidence record", workspace: null },
  brand_example: { label: "Brand example", workspace: "desk" },
  risk_finding: { label: "Risk finding", workspace: "lab" },
  finding: { label: "Risk Check finding", workspace: "lab" },
  profile_item: { label: "Cultural profile item", workspace: "lens" },
  adaptation: { label: "Adaptation", workspace: "studio" },
  version: { label: "Creative version", workspace: "studio" },
  scene: { label: "Creative scene", workspace: "studio" },
};

/** What to search, as groups a person recognises; none ticked searches everything. */
const GROUPS: { key: string; label: string; kinds: SearchHit["kind"][] }[] = [
  { key: "claims", label: "Claims", kinds: ["claim"] },
  { key: "sources", label: "Claim sources", kinds: ["claim_source"] },
  { key: "evidence", label: "Evidence records", kinds: ["evidence"] },
  { key: "findings", label: "Risk findings", kinds: ["risk_finding", "finding"] },
  { key: "creative", label: "Creative", kinds: ["adaptation", "version", "scene"] },
  { key: "profiles", label: "Profiles and brand", kinds: ["profile_item", "brand_example"] },
];

function Hit({ hit, campaignId, onOpenClaim }: { hit: SearchHit; campaignId: string; onOpenClaim: (claimId: string) => void }) {
  const { inspect } = useEvidenceInspector();
  const meta = KIND[hit.kind];
  const claimId = hit.kind === "claim" ? hit.ref.id : hit.kind === "claim_source" ? (hit.ref.url?.split("/").pop() ?? null) : null;

  async function openEvidence() {
    const record = await unwrap(api.GET("/api/v1/evidence/{evidence_id}", { params: { path: { evidence_id: hit.ref.id } } })).catch(() => null);
    inspect({ title: hit.title, summary: record ? undefined : "The evidence record could not be loaded.", records: record ? [record] : [] });
  }

  const body = (
    <>
      <span className="flex flex-wrap items-center gap-1.5">
        <Tag className="border-border bg-surface-muted text-ink-secondary">{meta.label}</Tag>
        {hit.region_code && <span className="font-mono text-[11.5px] text-ink-muted">{hit.region_code}</span>}
        {hit.evidence_type && hit.claim_type && <EvidenceLabel record={{ evidence_type: hit.evidence_type, claim_type: hit.claim_type }} />}
        {hit.retrieval_mode && <RetrievalBadge mode={hit.retrieval_mode} />}
      </span>
      <span className="mt-1 block text-[14px] font-medium text-ink">{hit.title}</span>
      <span className="mt-0.5 line-clamp-3 block max-w-[72ch] text-[13px] text-ink-body">{hit.snippet}</span>
      <span className="type-ledger mt-1 block text-[12px] text-ink-muted">
        {hit.explanation} · Similarity {hit.similarity.toFixed(2)}
      </span>
    </>
  );
  const row = "group flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-surface-muted/60 focus-visible:-outline-offset-2";
  const arrow = <ArrowUpRight aria-hidden className="mt-1 size-4 shrink-0 text-ink-muted group-hover:text-rose" />;
  return (
    <li>
      {claimId ? (
        <button type="button" onClick={() => onOpenClaim(claimId)} className={row}>
          <span className="min-w-0 flex-1">{body}</span>
          {arrow}
          <span className="sr-only">Open claim detail</span>
        </button>
      ) : hit.kind === "evidence" ? (
        <button type="button" onClick={() => void openEvidence()} className={row}>
          <span className="min-w-0 flex-1">{body}</span>
          {arrow}
          <span className="sr-only">Open evidence record</span>
        </button>
      ) : meta.workspace ? (
        <Link href={workspaceHref(campaignId, meta.workspace)} className={row}>
          <span className="min-w-0 flex-1">{body}</span>
          {arrow}
          <span className="sr-only">Open in its workspace</span>
        </Link>
      ) : (
        <div className={row}>
          <span className="min-w-0 flex-1">{body}</span>
        </div>
      )}
    </li>
  );
}

/**
 * Semantic search over what this project stores, claims and their sources included, optionally limited to one region.
 * It runs on submit. When embeddings are not configured the API says so and this shows that, never a keyword guess.
 */
export function SearchPanel({ projectId, campaignId, onOpenClaim }: { projectId: string; campaignId: string; onOpenClaim: (claimId: string) => void }) {
  const regions = useRegions();
  const [draft, setDraft] = useState("");
  const [region, setRegion] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const [applied, setApplied] = useState({ q: "", region: "", kinds: [] as string[] });
  const results = useProofSearch(projectId, applied.q, applied.region, applied.kinds);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = draft.trim();
    if (!q) return;
    setApplied({ q, region, kinds: GROUPS.filter((g) => groups.includes(g.key)).flatMap((g) => g.kinds) });
  }

  const data = results.data;
  return (
    <div className="space-y-4">
      <form role="search" onSubmit={submit} className="space-y-3 rounded-card border border-border bg-surface px-4 py-4">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[14rem] flex-1 space-y-1">
            <label htmlFor="proof-search" className="text-[13px] font-medium text-ink">
              Search the record
            </label>
            <div className="relative">
              <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-muted" />
              <Input id="proof-search" type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="For example: festival gifting customs in Kerala" className="h-10 pl-8 text-[14px]" />
            </div>
          </div>
          <div className="space-y-1">
            <label htmlFor="proof-search-region" className="text-[13px] font-medium text-ink">
              Region
            </label>
            <select id="proof-search-region" value={region} onChange={(e) => setRegion(e.target.value)} className={`${SELECT_CLASS} h-10 block`}>
              <option value="">All regions</option>
              {regions.data?.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name} ({r.code})
                </option>
              ))}
            </select>
          </div>
          <Button type="submit" size="lg" disabled={!draft.trim() || results.isFetching}>
            <Search aria-hidden />
            Search
          </Button>
        </div>
        <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <legend className="sr-only">What to search</legend>
          <span aria-hidden className="type-meta">
            Look in
          </span>
          {GROUPS.map((g) => (
            <label key={g.key} className="flex items-center gap-1.5 text-[13px] text-ink-body">
              <input
                type="checkbox"
                checked={groups.includes(g.key)}
                onChange={(e) => setGroups((list) => (e.target.checked ? [...list, g.key] : list.filter((x) => x !== g.key)))}
                className="size-4 accent-[var(--primary)]"
              />
              {g.label}
            </label>
          ))}
          <span className="type-meta">{groups.length === 0 ? "Nothing ticked searches everything." : ""}</span>
        </fieldset>
      </form>

      {!applied.q ? (
        <EmptyState
          title="Find any claim, source or decision"
          description="Search matches by meaning, not by exact words, over the claims and sources stored for this workspace, the evidence records of this brand, and its findings, adaptations and versions. Limit it to one region to see only that region's claims."
        />
      ) : results.isPending ? (
        <LoadingState label="Searching. The first search of a brand can take a while, because its records are indexed first." />
      ) : results.error ? (
        <ErrorState error={results.error} onRetry={() => void results.refetch()} />
      ) : data?.status === "unavailable" ? (
        <EmptyState
          title="Search is unavailable"
          description={data.message ?? "Semantic search needs an embedding model configured on the backend. No keyword stand-in is used, so no results are shown."}
        />
      ) : data && data.hits.length === 0 ? (
        <EmptyState
          title="Nothing stored is close to this query"
          description={`No stored claim, source, evidence record or finding matched “${applied.q}”${applied.region ? ` in ${applied.region}` : ""}. Try other words, or remove the region and kind limits.`}
        />
      ) : (
        <section aria-label="Search results" className="space-y-2">
          <p className="type-meta">
            {data?.hits.length} {data?.hits.length === 1 ? "result" : "results"} for “{applied.q}”
            {applied.region && ` in ${applied.region}`}
            {" · Similarity ranks results; it is not a probability"}
            {data?.embedding_model && ` · ${data.embedding_model}`}
          </p>
          <ul className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
            {data?.hits.map((hit) => (
              <Hit key={`${hit.kind}-${hit.id}`} hit={hit} campaignId={campaignId} onOpenClaim={onOpenClaim} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
