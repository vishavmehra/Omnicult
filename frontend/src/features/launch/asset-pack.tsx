"use client";

import { Check, Clock3, Copy, Download, FileArchive, Info, LoaderCircle, PackageCheck } from "lucide-react";
import { useState } from "react";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { LedgerList, SectionTitle } from "@/features/workspaces/parts";
import { useNow } from "@/hooks/use-now";
import { formatDateTime, formatElapsed, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCapabilities } from "./api";
import { NativeSelect } from "./bits";
import {
  absoluteDownloadUrl,
  useAssetPackPreview,
  useAssetPacks,
  useCreateAssetPack,
  useRegionPlan,
  type AssetPackCreated,
  type AssetPackManifest,
  type PackFile,
} from "./delivery-api";
import type { DeliveryTab } from "./region-plan";

const ROLE: Record<PackFile["role"], string> = {
  copy_json: "Copy (JSON)",
  copy_text: "Copy (text)",
  captions: "Captions",
  creative: "Creative file",
  brand_kit_file: "Brand Kit file",
  brand_kit_data: "Brand Kit data",
  checksums: "Checksums",
  manifest: "Manifest",
};

const ORDER: PackFile["role"][] = ["creative", "captions", "copy_json", "copy_text", "brand_kit_file", "brand_kit_data"];

const bytes = (n: number) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

function FilesTable({ manifest }: { manifest: AssetPackManifest }) {
  const files = [...manifest.files].sort((a, b) => ORDER.indexOf(a.role) - ORDER.indexOf(b.role) || a.path.localeCompare(b.path));
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>File</TableHead>
            <TableHead>What it is</TableHead>
            <TableHead>Channel</TableHead>
            <TableHead className="text-right">Size</TableHead>
            <TableHead>SHA-256</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {files.map((f) => (
            <TableRow key={f.path}>
              <TableCell className="max-w-[26rem] font-mono text-[12px] break-all whitespace-normal text-ink">{f.path}</TableCell>
              <TableCell className="text-[13px] text-ink-body">
                {ROLE[f.role]}
                {f.rights_confirmed_at && <span className="block text-[11.5px] text-ink-muted">Rights confirmed {formatRelative(f.rights_confirmed_at)}</span>}
              </TableCell>
              <TableCell className="text-[13px] text-ink-body">
                {f.channel}
                {f.also_channels.length > 0 && <span className="block text-[11.5px] text-ink-muted">also {f.also_channels.join(", ")}</span>}
                {f.channel_match !== "none" && <span className="block text-[11.5px] text-ink-muted">{f.channel_match === "creative_ref" ? "named in the brief" : "matched by format"}</span>}
              </TableCell>
              <TableCell className="text-right text-[13px] tabular-nums text-ink-body">{bytes(f.size)}</TableCell>
              <TableCell className="font-mono text-[11.5px] text-ink-muted" title={f.sha256}>
                {f.sha256.slice(0, 12)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function Built({ pack, onNew }: { pack: AssetPackCreated; onNew(): void }) {
  const now = useNow(true, 1000);
  const [copied, setCopied] = useState(false);
  const remaining = Date.parse(pack.expires_at) - now;
  const expired = remaining <= 0;
  const url = absoluteDownloadUrl(pack.download_url);
  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="space-y-2.5 rounded-card border border-success/40 bg-success-soft/30 px-4 py-3.5">
      <p className="flex items-center gap-2 text-[14px] font-semibold text-ink">
        <PackageCheck aria-hidden className="size-4 text-success" />
        Pack built for {pack.region_name}
      </p>
      <p className="type-ledger flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[13px] text-ink-body">
        <span className="font-medium text-ink">{pack.filename}</span>
        <span className="text-ink-muted">
          {pack.file_count} files · {bytes(pack.byte_size)}
        </span>
        <span className="font-mono text-[11.5px] text-ink-muted" title={`SHA-256 of the ZIP: ${pack.sha256}`}>
          sha256 {pack.sha256.slice(0, 12)}
        </span>
      </p>
      <p className={cn("flex items-center gap-1.5 text-[13px]", expired ? "text-warning" : "text-ink-body")} role="status">
        <Clock3 aria-hidden className="size-4 shrink-0" />
        {expired ? (
          <>This link expired at {formatDateTime(pack.expires_at)}. Build the pack again for a new link.</>
        ) : (
          <>
            The download link works until {formatDateTime(pack.expires_at)}, for <span className="tabular-nums">{formatElapsed(remaining)}</span> more.
          </>
        )}
      </p>
      <p className="max-w-[72ch] text-[12.5px] text-ink-muted">Anyone who has this link can download the pack until it expires. It needs no sign-in, so share it with care.</p>
      <div className="flex flex-wrap gap-2">
        {expired ? (
          <span aria-disabled className={cn(buttonVariants({ variant: "outline" }), "pointer-events-none opacity-50")}>
            <Download aria-hidden />
            Download
          </span>
        ) : (
          <a href={url} download={pack.filename} className={buttonVariants()}>
            <Download aria-hidden />
            Download ZIP
          </a>
        )}
        <Button variant="outline" onClick={() => void copy()} disabled={expired}>
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? "Link copied" : "Copy link"}
        </Button>
        <Button variant="ghost" onClick={onNew}>
          Done
        </Button>
      </div>
    </div>
  );
}

/**
 * Asset Pack (feature 40): a ZIP per region for the version a person approved, built on the server and handed over through an
 * expiring link. Only files whose rights were confirmed go in; everything left out is listed with the reason.
 */
export function AssetPackTab({ region: wanted, onOpen }: { region: string | null; onOpen(tab: DeliveryTab, region?: string): void }) {
  const { campaign, project } = useCampaign();
  const caps = useCapabilities();
  const plan = useRegionPlan(campaign.id);
  const packs = useAssetPacks(campaign.id);
  const build = useCreateAssetPack(campaign.id);
  const [region, setRegion] = useState(wanted ?? "");
  const [built, setBuilt] = useState<AssetPackCreated | null>(null);

  // A region picked on the Region Plan wins (this tab mounts fresh when it opens); otherwise the first region that can be packed.
  const regions = plan.data?.regions ?? [];
  const current = region || regions.find((r) => r.pack_available)?.region_code || regions[0]?.region_code || "";
  const preview = useAssetPackPreview(campaign.id, current);
  const demo = project.mode === "demo";

  function submit() {
    build.mutate({ region_code: current }, { onSuccess: setBuilt });
  }

  return (
    <div className="space-y-10">
      <section aria-labelledby="pack-title" className="space-y-3">
        <SectionTitle id="pack-title" meta={plan.data ? `${regions.filter((r) => r.pack_available).length} of ${regions.length} regions can be packed` : undefined}>
          Asset Pack
        </SectionTitle>
        <p className="max-w-[72ch] text-[13.5px] text-ink-secondary">
          A pack holds what a region needs to run the version a person approved: its copy as JSON and text, its creative files and caption sidecar, the Brand Kit files, and a manifest with where each file came from and its checksum. Files are named omc_campaign_version_region_channel.
        </p>
        {plan.error ? (
          <ErrorState error={plan.error} onRetry={() => void plan.refetch()} />
        ) : plan.isPending ? (
          <LoadingState label="Reading the regions…" />
        ) : regions.length === 0 ? (
          <EmptyState title="No region to pack yet" description="A pack is built for one region at a time, from the version approved for it. Name the regions in the Campaign Brief and approve a version on the Readiness Board." needs={[{ label: "Target regions in the Campaign Brief" }, { label: "An approved version for a region" }]} />
        ) : (
          <div className="flex flex-wrap items-end gap-4">
            <div className="w-64 space-y-1">
              <label htmlFor="pack-region" className="block text-[12.5px] text-ink-secondary">Region</label>
              <NativeSelect id="pack-region" value={current} onChange={(e) => { setRegion(e.target.value); setBuilt(null); build.reset(); }}>
                {regions.map((r) => (
                  <option key={r.region_code} value={r.region_code}>
                    {r.region_name}{r.pack_available ? "" : ", no approval yet"}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>
        )}
      </section>

      {current && (
        <section aria-labelledby="pack-preview-title" className="space-y-3">
          <SectionTitle id="pack-preview-title">What goes in</SectionTitle>
          {preview.error ? (
            <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
          ) : preview.isPending ? (
            <LoadingState label="Working out what the pack would hold…" />
          ) : !preview.data.can_build || !preview.data.manifest ? (
            <EmptyState
              title="Nothing to pack for this region yet"
              description={preview.data.blocked_reason ?? "No version has a standing approval for this region."}
              needs={[{ label: "A version approved by a person for this region, on the Readiness Board" }]}
              action={
                <Button variant="outline" size="sm" onClick={() => onOpen("readiness")}>
                  Open the Readiness Board
                </Button>
              }
            />
          ) : (
            <>
              <LedgerList
                rows={[
                  { label: "Version", value: <>{preview.data.manifest.version.label} <span className="text-ink-muted">{preview.data.manifest.version.language ? `· ${preview.data.manifest.version.language}` : ""}</span></> },
                  {
                    label: "Approval",
                    value: (
                      <>
                        Approved by {preview.data.manifest.approval.decided_by_name ?? "a member"}, {formatDateTime(preview.data.manifest.approval.decided_at)}
                        {preview.data.manifest.approval.overrides_recommendation && <span className="text-warning"> · against the recommendation ({preview.data.manifest.approval.verdict_at_decision ?? "none on record"})</span>}
                      </>
                    ),
                  },
                  { label: "Reason given", value: preview.data.manifest.approval.reason },
                  { label: "File names", value: <span className="font-mono text-[12.5px]">{preview.data.manifest.naming}</span> },
                  { label: "Download link", value: `Works for ${Math.round(preview.data.url_ttl_seconds / 60)} minutes after you build the pack` },
                ]}
              />
              {preview.data.approved_versions.length > 1 && (
                <p className="text-[12.5px] text-ink-secondary">
                  {preview.data.approved_versions.length} versions are approved for this region; the newest decision is packed: {preview.data.approved_versions.map((v) => v.label).join(", ")}.
                </p>
              )}

              <h3 className="text-[13.5px] font-semibold text-ink">Files ({preview.data.manifest.files.length + 2} with the manifest and checksums)</h3>
              <FilesTable manifest={preview.data.manifest} />

              {preview.data.manifest.excluded.length > 0 && (
                <div className="space-y-1.5">
                  <h3 className="text-[13.5px] font-semibold text-ink">Left out ({preview.data.manifest.excluded.length})</h3>
                  <ul className="ledger-rules rounded-card border border-border bg-surface" aria-label="Files left out">
                    {preview.data.manifest.excluded.map((x, i) => (
                      <li key={`${x.kind}-${x.label}-${i}`} className="grid gap-0.5 px-3.5 py-2 sm:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] sm:gap-x-4">
                        <span className="text-[13.5px] text-ink">
                          {x.label} <Tag className="ml-1 border-border text-ink-secondary">{x.kind.replace("brand_kit_", "Brand Kit ").replace("creative", "Creative")}</Tag>
                        </span>
                        <span className="text-[12.5px] text-ink-secondary">{x.reason}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="space-y-2.5">
                <div className="flex flex-wrap items-center gap-2.5">
                  <Button disabled={!caps.canCompute || build.isPending} onClick={submit}>
                    {build.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <FileArchive aria-hidden />}
                    {build.isPending ? "Building the pack…" : "Build the pack"}
                  </Button>
                  {!caps.loading && !caps.canCompute && caps.reason && (
                    <p role="status" className="flex max-w-[60ch] items-start gap-2 text-[13px] text-ink-secondary">
                      <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
                      Building a pack needs the owner or editor role. {caps.reason}
                    </p>
                  )}
                </div>
                {build.error && <ErrorState error={build.error} onRetry={submit} />}
                {built && built.region_code === current && <Built pack={built} onNew={() => setBuilt(null)} />}
              </div>
              <ul className="list-disc space-y-0.5 pl-5 text-[12px] text-ink-muted">
                {preview.data.manifest.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      <section aria-labelledby="packs-title" className="space-y-3">
        <SectionTitle id="packs-title" meta={packs.data ? `${packs.data.total} built` : undefined}>
          Packs built for this campaign
        </SectionTitle>
        {packs.error ? (
          <ErrorState error={packs.error} onRetry={() => void packs.refetch()} />
        ) : packs.isPending ? (
          <LoadingState label="Reading the built packs…" />
        ) : packs.data.items.length === 0 ? (
          <EmptyState title="No pack built yet" description="Each pack you build is listed here with its checksum and when its download link stops working. The link itself is shown once, when you build." />
        ) : (
          <ul className="ledger-rules rounded-card border border-border bg-surface" aria-label="Built packs">
            {packs.data.items.map((p) => (
              <li key={p.id} className="grid gap-x-4 gap-y-0.5 px-4 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                <div className="min-w-0">
                  <p className="truncate font-mono text-[12.5px] text-ink" title={p.filename}>{p.filename}</p>
                  <p className="type-meta">
                    {p.region_name} · {p.version_label} · {p.file_count} files · {bytes(p.byte_size)} · built {formatRelative(p.created_at)} by {p.created_by_name ?? "a member"} · sha256 {p.sha256.slice(0, 10)}
                  </p>
                </div>
                <Tag className={p.status === "active" ? "border-success/30 bg-success-soft text-success" : "border-border bg-surface-muted text-ink-secondary"}>
                  {p.status === "active" ? `Link active until ${formatDateTime(p.expires_at)}` : "Link expired"}
                </Tag>
              </li>
            ))}
          </ul>
        )}
        {demo && <p className="type-meta">Source: demonstration data. The fictional brand’s files had their rights confirmed by the demo seed; nothing here is a live asset.</p>}
      </section>
    </div>
  );
}
