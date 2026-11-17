"use client";

import { ArrowUpRight, CircleAlert, FlaskConical, LoaderCircle, MapPinOff, Plus, Target, TriangleAlert, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSyncExternalStore, type ReactNode } from "react";

import { ModeBadge } from "@/components/evidence/badges";
import { WorkspaceShell } from "@/components/shell/workspace-shell";
import { workspaceHref } from "@/components/shell/workspaces";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { RunStatusBadge } from "@/components/workflow/run-status";
import { RUN_TYPE_META, sectionHref } from "@/features/project/workflow";
import type { Run } from "@/lib/api/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { NewCampaign } from "./new-campaign";
import { DIRECTORY_BRAND_LIMIT, useCampaignDirectory, type DirectoryCampaign } from "./use-campaign-directory";
import { DemoSignInError, useStartDemo } from "./use-start-demo";

const noop = () => () => {};
const dateLabel = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long" });
function useToday() {
  return useSyncExternalStore(noop, () => dateLabel.format(new Date()), () => null);
}

type Attention = { key: string; Icon: LucideIcon; tone: string; title: ReactNode; detail?: ReactNode; href: string; when?: string };

/** What needs a person, from real records only: failed, unfinished and gapped runs, and briefs missing what work needs. */
function attentionItems(campaigns: DirectoryCampaign[], runs: { run: Run }[]): Attention[] {
  const name = new Map(campaigns.map((c) => [c.id, c.name]));
  const items: Attention[] = [];
  for (const { run } of runs) {
    const meta = RUN_TYPE_META[run.run_type];
    const href = sectionHref(run.project_id, meta.segment, run.campaign_id);
    const on = run.campaign_id && name.get(run.campaign_id) ? ` · ${name.get(run.campaign_id)}` : "";
    if (run.status === "failed")
      items.push({ key: run.id, Icon: CircleAlert, tone: "text-danger", title: `${meta.label} failed${on}`, detail: run.error?.message, href, when: run.completed_at ?? run.created_at });
    else if (run.status === "partial")
      items.push({ key: run.id, Icon: TriangleAlert, tone: "text-warning", title: `${meta.label} completed with gaps${on}`, detail: run.error?.message, href, when: run.completed_at ?? run.created_at });
    else if (run.status === "queued" || run.status === "running")
      items.push({ key: run.id, Icon: LoaderCircle, tone: "text-info", title: `${meta.label} ${run.status}${on}`, detail: run.progress?.message, href, when: run.created_at });
  }
  for (const c of campaigns) {
    if (!c.target_markets.length)
      items.push({ key: `${c.id}-regions`, Icon: MapPinOff, tone: "text-warning", title: `No target regions · ${c.name}`, detail: "Market Lens and Audience Lab need at least one region.", href: workspaceHref(c.id, "desk") });
    else if (!c.objective)
      items.push({ key: `${c.id}-objective`, Icon: Target, tone: "text-ink-secondary", title: `No objective · ${c.name}`, detail: "Scores check consistency with the objective.", href: workspaceHref(c.id, "desk") });
  }
  return items;
}

/** Campaign Desk home: the Today view across every campaign the account can open. */
export function TodayView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const today = useToday();
  const dir = useCampaignDirectory({ withRuns: true });
  const demo = useStartDemo();
  const composing = params.get("new") === "campaign";
  const setComposing = (open: boolean) => router.replace(open ? `${pathname}?new=campaign` : pathname, { scroll: false });

  const latestRun = new Map<string, Run>();
  for (const { run } of dir.runs) if (run.campaign_id && !latestRun.has(run.campaign_id)) latestRun.set(run.campaign_id, run);
  const attention = attentionItems(dir.campaigns, dir.runs);
  const firstRun = !dir.pending && !dir.error && dir.totalBrands === 0;

  return (
    <WorkspaceShell campaignId={dir.campaigns[0]?.id ?? null} active="today">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-border pb-5">
        <div className="space-y-1.5">
          <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Today</h1>
          <p className="text-[14.5px] text-ink-secondary">
            {today ? `${today}. ` : ""}What is running, what needs a person, and every campaign you can open.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => demo.mutate()} disabled={demo.isPending}>
            <FlaskConical aria-hidden />
            {demo.isPending ? "Preparing the demo…" : "Try the demo"}
          </Button>
          <Button onClick={() => setComposing(true)} disabled={composing || dir.pending}>
            <Plus aria-hidden />
            New campaign
          </Button>
        </div>
      </header>

      <div className="space-y-6">
        {demo.error &&
          (demo.error instanceof DemoSignInError ? (
            <p role="alert" className="rounded-card border border-danger/35 bg-danger-soft/60 px-4 py-3 text-[13.5px] text-ink">
              {demo.error.message}
            </p>
          ) : (
            <ErrorState error={demo.error} onRetry={() => demo.mutate()} />
          ))}
        {dir.error && <ErrorState error={dir.error} onRetry={dir.refetch} />}
        {composing && dir.projects.data && <NewCampaign brands={dir.brands} onClose={() => setComposing(false)} />}

        {dir.pending ? (
          <LoadingState label="Reading your brands and campaigns…" />
        ) : firstRun ? (
          <EmptyState
            title="No brands or campaigns yet"
            description="Omnicult keeps one brief per campaign and reads it in every workspace. Start with the demo, a sample brand on labelled fixtures, or create your own brand and campaign."
            action={
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => demo.mutate()} disabled={demo.isPending}>
                  <FlaskConical aria-hidden />
                  {demo.isPending ? "Preparing the demo…" : "Try the demo"}
                </Button>
                <Button variant="outline" onClick={() => setComposing(true)}>
                  <Plus aria-hidden />
                  Create a brand and campaign
                </Button>
              </div>
            }
          />
        ) : (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)]">
            <div className="min-w-0 space-y-6">
              <section aria-labelledby="attention" className="clay-panel tint-peach border border-border/50 p-4 sm:p-5">
                <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
                  <h2 id="attention" className="text-[15px] font-semibold text-ink">
                    Needs attention
                  </h2>
                  <span className="type-meta">Approvals are not tracked by the API yet</span>
                </div>
                {dir.runsPending ? (
                  <LoadingState label="Checking recent runs…" className="py-3" />
                ) : attention.length === 0 ? (
                  <p className="px-1 py-2 text-[13.5px] text-ink-secondary">
                    Nothing needs attention: no failed or unfinished runs, and every brief has regions and an objective.
                  </p>
                ) : (
                  <ol className="ledger-rules margin-rule clay-well overflow-hidden rounded-xl pl-2">
                    {attention.map((a, i) => (
                      <li key={a.key} className="ledger-ink" style={{ animationDelay: `${Math.min(i, 8) * 45}ms` }}>
                        <Link href={a.href} className="group flex items-start gap-3 px-3.5 py-2.5 hover:bg-surface-muted/60 focus-visible:-outline-offset-2">
                          <a.Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", a.tone, a.Icon === LoaderCircle && "animate-spin motion-reduce:animate-none")} />
                          <span className="min-w-0 flex-1">
                            <span className="block text-[14px] font-medium text-ink">{a.title}</span>
                            {a.detail && <span className="block truncate text-[12.5px] text-ink-secondary">{a.detail}</span>}
                          </span>
                          {a.when && (
                            <span className="type-meta shrink-0 pt-0.5" title={formatDateTime(a.when)}>
                              {formatRelative(a.when)}
                            </span>
                          )}
                          <ArrowUpRight aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-muted group-hover:text-rose" />
                        </Link>
                      </li>
                    ))}
                  </ol>
                )}
              </section>

              <section aria-labelledby="campaigns" className="clay-panel border border-border/50 p-4 sm:p-5">
                <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
                  <h2 id="campaigns" className="text-[15px] font-semibold text-ink">
                    Campaigns
                  </h2>
                  <span className="type-meta">
                    {dir.campaigns.length} {dir.campaigns.length === 1 ? "campaign" : "campaigns"} across {dir.brands.length} {dir.brands.length === 1 ? "brand" : "brands"}
                    {dir.totalBrands > DIRECTORY_BRAND_LIMIT && ` (showing the ${DIRECTORY_BRAND_LIMIT} most recent of ${dir.totalBrands})`}
                  </span>
                </div>
                {dir.campaigns.length === 0 ? (
                  <EmptyState
                    title="Your brands have no campaigns yet"
                    description="A campaign holds the brief, the original creative and every version made from it."
                    action={
                      <Button variant="outline" onClick={() => setComposing(true)}>
                        <Plus aria-hidden />
                        New campaign
                      </Button>
                    }
                  />
                ) : (
                  <div className="clay-well overflow-x-auto rounded-xl">
                    <table className="type-ledger w-full min-w-[38rem] text-left text-[13.5px] [&_td]:whitespace-nowrap">
                      <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
                        <tr>
                          <th scope="col" className="px-3.5 py-2 font-medium">Campaign</th>
                          <th scope="col" className="px-3 py-2 font-medium">Brand</th>
                          <th scope="col" className="px-3 py-2 font-medium">Regions</th>
                          <th scope="col" className="px-3 py-2 font-medium">Version</th>
                          <th scope="col" className="px-3 py-2 font-medium">Last run</th>
                          <th scope="col" className="px-3 py-2 font-medium">Updated</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {dir.campaigns.map((c) => {
                          const run = latestRun.get(c.id);
                          return (
                            <tr key={c.id} className="hover:bg-surface-muted/60">
                              <th scope="row" className="px-3.5 py-2.5 font-normal">
                                <Link href={workspaceHref(c.id, "desk")} className="font-semibold text-ink hover:text-rose hover:underline">
                                  {c.name}
                                </Link>
                              </th>
                              <td className="px-3 py-2.5 text-ink-body">
                                <span className="inline-flex items-center gap-2">
                                  {c.brand.name}
                                  {c.brand.mode === "demo" && <ModeBadge mode="demo" />}
                                </span>
                              </td>
                              <td className="max-w-[14rem] truncate px-3 py-2.5 text-ink-body">
                                {c.target_markets.length ? c.target_markets.map((m) => m.display_name).join(", ") : <span className="text-ink-muted">None</span>}
                              </td>
                              <td className="px-3 py-2.5 text-ink-secondary tabular-nums">
                                v{c.current_version.version_number} <span className="text-ink-muted">of {c.versions.length}</span>
                              </td>
                              <td className="px-3 py-2.5">{run ? <RunStatusBadge status={run.status} /> : <span className="text-ink-muted">No runs</span>}</td>
                              <td className="px-3 py-2.5 text-ink-secondary" title={formatDateTime(c.updated_at)}>
                                {formatRelative(c.updated_at)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>

            <aside aria-labelledby="recent-runs" className="clay-panel tint-sky min-w-0 self-start border border-border/50 p-4 sm:p-5">
              <div className="mb-2.5 flex items-baseline justify-between gap-2">
                <h2 id="recent-runs" className="text-[15px] font-semibold text-ink">
                  Recent runs
                </h2>
                <span className="type-meta">All brands, newest first</span>
              </div>
              {dir.runsPending ? (
                <LoadingState label="Loading runs…" className="py-3" />
              ) : dir.runs.length === 0 ? (
                <p className="rounded-card border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-muted">No runs yet. Runs appear here as soon as any workspace starts one.</p>
              ) : (
                <ol className="ledger-rules clay-well rounded-xl">
                  {dir.runs.slice(0, 12).map(({ run, brand }) => {
                    const meta = RUN_TYPE_META[run.run_type];
                    return (
                      <li key={run.id}>
                        <Link href={sectionHref(run.project_id, meta.segment, run.campaign_id)} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 px-3.5 py-2.5 hover:bg-surface-muted/60 focus-visible:-outline-offset-2">
                          <span className="truncate text-[13.5px] font-medium text-ink">{meta.label}</span>
                          <RunStatusBadge status={run.status} />
                          <span className="truncate text-[12px] text-ink-muted">
                            {brand.name}
                            {run.mode === "demo" && " · demo fixture"}
                          </span>
                          <span className="type-meta text-right" title={formatDateTime(run.created_at)}>
                            {formatRelative(run.created_at)}
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                </ol>
              )}
            </aside>
          </div>
        )}
      </div>
    </WorkspaceShell>
  );
}
