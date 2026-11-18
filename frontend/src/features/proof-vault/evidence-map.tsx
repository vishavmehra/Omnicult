"use client";

import { BookOpen, FileText, GitCompareArrows, Layers, MapPin, Quote } from "lucide-react";
import { usePathname } from "next/navigation";
import { useMemo, useState, type MouseEvent } from "react";

import { ClaimBadge } from "@/components/evidence/badges";
import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { LimitationList } from "@/components/evidence/limitation-list";
import { GraphCanvas, type CanvasEdge, type CanvasNode, type LegendEntry } from "@/components/graph/graph-canvas";
import { Button } from "@/components/ui/button";
import { formatDateTime, humanize } from "@/lib/format";

import { useProofGraph, useRegions } from "./api";
import { SELECT_CLASS } from "./parts";
import type { GraphNode } from "./types";

/**
 * Node colours are drawn on the canvas's white node discs in both themes, so they are the darkened light-theme values
 * of the status palette (no purple, plum or beige), each readable on white.
 */
const LEGEND: (LegendEntry & { kinds: string[] })[] = [
  { kind: "region", label: "Regions", color: "#1f5f9e", Icon: MapPin, kinds: ["region"], description: "Regions the claims are about." },
  { kind: "claim", label: "Claims", color: "#1b1d22", Icon: Quote, kinds: ["claim"], description: "Statements with their five tags." },
  { kind: "source", label: "Sources", color: "#1f7a4d", Icon: BookOpen, kinds: ["claim_source"], description: "The stored sources behind each claim." },
  { kind: "conflict", label: "Conflicts", color: "#8a5a00", Icon: GitCompareArrows, kinds: ["conflict"], description: "Two claims that disagree, stored as a conflict." },
  { kind: "report", label: "Reports", color: "#c2410c", Icon: FileText, kinds: ["report"], description: "Proof Report snapshots and the claims they reference." },
  { kind: "other", label: "Other records", color: "#4e535c", Icon: Layers, kinds: [], description: "Runs, versions, adaptations, findings and the rest." },
];
const LAYER_OF = new Map(LEGEND.flatMap((l) => l.kinds.map((k) => [k, l.kind] as const)));

const claimIdOf = (n: GraphNode): string | null => {
  if (n.kind === "claim") return n.ref.id;
  if (n.kind === "claim_source") return n.ref.url?.split("/").pop() ?? null;
  return null;
};

/**
 * The evidence graph, read only: regions, claims, sources, conflicts and reports joined by stored links. Selecting a node
 * opens its claim detail. Nothing is inferred: an edge exists only where a stored field links two records.
 */
export function EvidenceMap({
  projectId,
  campaignId,
  onOpenClaim,
  onOpenReport,
  suggestedRegion,
}: {
  projectId: string;
  campaignId: string;
  onOpenClaim: (claimId: string) => void;
  onOpenReport: (reportId: string) => void;
  /** The newest snapshot's first region: claims only draw for a region, and campaigns do not carry one yet. */
  suggestedRegion?: string;
}) {
  const pathname = usePathname();
  const regions = useRegions();
  const [chosen, setChosen] = useState<string | null>(null);
  const region = chosen ?? suggestedRegion ?? "";
  const setRegion = setChosen;
  const [everything, setEverything] = useState(false);
  const [limit, setLimit] = useState(200);
  const graph = useProofGraph(projectId, campaignId, region, limit);

  const raw = useMemo(() => new Map((graph.data?.nodes ?? []).map((n) => [n.id, n])), [graph.data]);
  const nodes = useMemo<CanvasNode[]>(
    () =>
      (graph.data?.nodes ?? [])
        .filter((n) => everything || LAYER_OF.has(n.kind))
        .map((n) => {
          const claimId = claimIdOf(n);
          return {
            id: n.id,
            label: n.label,
            kind: LAYER_OF.get(n.kind) ?? "other",
            isDemo: n.is_demo,
            isSynthetic: n.claim_type === "synthetic" || n.evidence_type === "synthetic_response",
            facts: { Kind: humanize(n.kind), Confidence: n.confidence ? humanize(n.confidence) : null, Created: n.created_at ? formatDateTime(n.created_at) : null },
            href: claimId ? `${pathname}?view=map&claim=${claimId}` : n.kind === "report" && n.ref.resource === "proof_report" ? `${pathname}?view=report&report=${n.ref.id}` : null,
          };
        }),
    [graph.data, everything, pathname],
  );
  const edges = useMemo<CanvasEdge[]>(() => (graph.data?.edges ?? []).map((e) => ({ id: e.id, source: e.source, target: e.target, relation: e.relation, provenance: e.provenance })), [graph.data]);
  const legend = LEGEND.filter((l) => l.kind !== "other" || everything);

  /** Delegated from the wrapper: a click on a node (React Flow marks each with data-id) opens its claim detail; other nodes only show their details. */
  function onCanvasClick(e: MouseEvent) {
    const el = (e.target as HTMLElement).closest<HTMLElement>(".react-flow__node");
    const n = el ? raw.get(el.dataset.id ?? "") : undefined;
    const claimId = n ? claimIdOf(n) : null;
    if (claimId) onOpenClaim(claimId);
  }

  return (
    <div className="space-y-4">
      <div className="max-w-[72ch] space-y-1 text-[13.5px] text-ink-secondary">
        <p>Select a claim or a source to open its detail. Only stored links are drawn, and each connection names the field that records it.</p>
        <p>Claims, sources and conflicts appear when a region is chosen below, or when the campaign has target regions.</p>
      </div>
      <div onClick={onCanvasClick}>
      <GraphCanvas
        label="Evidence map"
        isLoading={graph.isPending}
        error={graph.error}
        onRetry={() => void graph.refetch()}
        nodes={nodes}
        edges={edges}
        legend={legend}
        truncated={graph.data?.truncated}
        limitations={graph.data?.limitations ?? []}
        emptyTitle={everything ? "No linked records yet" : "No claims, sources or conflicts are drawn"}
        emptyDescription="Choose a region above, or set target regions on the campaign. A region only has claims once Market Lens has stored sourced evidence for it."
        filters={
          <div className="flex flex-wrap items-end gap-x-4 gap-y-2.5 rounded-card border border-border bg-surface px-4 py-3">
            <div className="space-y-1">
              <label htmlFor="map-region" className="type-meta block">
                Region
              </label>
              <select id="map-region" value={region} onChange={(e) => setRegion(e.target.value)} className={SELECT_CLASS}>
                <option value="">The campaign&apos;s target regions</option>
                {regions.data?.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.name} ({r.code})
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label htmlFor="map-limit" className="type-meta block">
                Show up to
              </label>
              <select id="map-limit" value={limit} onChange={(e) => setLimit(Number(e.target.value))} className={SELECT_CLASS}>
                {[50, 200, 500].map((n) => (
                  <option key={n} value={n}>
                    {n} nodes
                  </option>
                ))}
              </select>
            </div>
            <label className="flex h-8 items-center gap-2 text-[13.5px] text-ink-body">
              <input type="checkbox" checked={everything} onChange={(e) => setEverything(e.target.checked)} className="size-4 accent-[var(--primary)]" />
              Also show runs, versions and other records
            </label>
          </div>
        }
        renderDetails={(node) => {
          const n = raw.get(node.id);
          if (!n) return null;
          const claimId = claimIdOf(n);
          const linkedClaims = n.kind === "conflict" ? edges.filter((e) => e.source === n.id && e.target.startsWith("claim:")).map((e) => e.target.slice("claim:".length)) : [];
          return (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                {n.claim_type && <ClaimBadge claim={n.claim_type} />}
                {n.confidence && <ConfidenceIndicator level={n.confidence} />}
              </div>
              <p className="font-mono text-[11px] break-all text-ink-secondary">
                {n.ref.resource} · {n.ref.id}
              </p>
              {claimId && (
                <Button size="sm" onClick={() => onOpenClaim(claimId)}>
                  Open claim detail
                </Button>
              )}
              {linkedClaims.map((id, i) => (
                <Button key={id} size="sm" variant="outline" className="mr-1.5" onClick={() => onOpenClaim(id)}>
                  Open claim {i === 0 ? "A" : "B"}
                </Button>
              ))}
              {n.kind === "report" && n.ref.resource === "proof_report" && (
                <Button size="sm" variant="outline" onClick={() => onOpenReport(n.ref.id)}>
                  Open this report
                </Button>
              )}
              <LimitationList items={n.limitations} />
            </div>
          );
        }}
        height={560}
      />
      </div>
    </div>
  );
}
