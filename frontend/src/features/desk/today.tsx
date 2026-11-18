"use client";

import { ArrowUpRight, Bot, Calculator, FlaskConical, GitCompareArrows, Plus, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSyncExternalStore } from "react";

import { Tag } from "@/components/evidence/badges";
import { ModeBadge } from "@/components/evidence/badges";
import { WorkspaceShell } from "@/components/shell/workspace-shell";
import { WORKSPACES, workspaceHref } from "@/components/shell/workspaces";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { RunStatusBadge } from "@/components/workflow/run-status";
import { Verdict } from "@/components/workflow/verdict";
import { RUN_TYPE_META, sectionHref } from "@/features/project/workflow";
import type { Run } from "@/lib/api/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useToday } from "./api";
import { CommandBarButton } from "./command-bar";
import { NewCampaign } from "./new-campaign";
import type { TodayCampaign, TodayEvent } from "./types";
import { DIRECTORY_BRAND_LIMIT, useCampaignDirectory } from "./use-campaign-directory";
import { DemoSignInError, useStartDemo } from "./use-start-demo";

const noop = () => () => {};
const dateLabel = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long" });
function useToday_() {
  return useSyncExternalStore(noop, () => dateLabel.format(new Date()), () => null);
}

const ACTOR: Record<NonNullable<TodayEvent["actor"]>, { label: string; Icon: typeof Bot }> = {
  user: { label: "A person", Icon: UserRound },
  ai: { label: "An AI run", Icon: Bot },
  system: { label: "Fixed rules", Icon: Calculator },
};

/** One ruled row of the activity feed: where it happened, what, which campaign, who or what, and when. */
function EventRow({ e, index }: { e: TodayEvent; index: number }) {
  const ws = WORKSPACES[e.workspace];
  const actor = e.actor ? ACTOR[e.actor] : null;
  const href = e.campaign_id ? workspaceHref(e.campaign_id, e.workspace) : null;
  const body = (
    <>
      <ws.Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-muted" />
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium text-ink">{e.title}</span>
        {e.detail && <span className="block truncate text-[12.5px] text-ink-secondary">{e.detail}</span>}
        <span className="type-meta mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span>{ws.label}</span>
          <span aria-hidden>·</span>
          <span className="truncate">{e.campaign_name ?? `${e.brand_name} brand`}</span>
          {actor && (
            <>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center gap-1">
                <actor.Icon aria-hidden className="size-3" />
                {actor.label}
              </span>
            </>
          )}
        </span>
      </span>
      <span className="type-meta shrink-0 pt-0.5" title={formatDateTime(e.at)}>
        {formatRelative(e.at)}
      </span>
    </>
  );
  const cls = "flex items-start gap-3 px-3.5 py-2.5";
  return (
    <li className="ledger-ink" style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}>
      {href ? (
        <Link href={href} className={cn(cls, "group hover:bg-surface-muted/60 focus-visible:-outline-offset-2")}>
          {body}
        </Link>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </li>
  );
}

function BriefCell({ c }: { c: TodayCampaign }) {
  if (c.brief_version === 0) return <span className="text-ink-muted">No brief saved</span>;
  return (
    <span className="inline-flex flex-col leading-tight">
      <span className="type-ledger tabular-nums text-ink-body">Version {c.brief_version}</span>
      <span className={cn("text-[11.5px]", c.brief_complete ? "text-success" : "text-warning")}>{c.brief_complete ? "Complete" : `${c.brief_missing.length} parts missing`}</span>
    </span>
  );
}

/** Campaign Desk home: the Today view across every campaign the account can open. Every number comes from a saved record. */
export function TodayView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const today = useToday_();
  const dir = useCampaignDirectory({ withRuns: true });
  const feed = useToday();
  const demo = useStartDemo();
  const composing = params.get("new") === "campaign";
  const setComposing = (open: boolean) => router.replace(open ? `${pathname}?new=campaign` : pathname, { scroll: false });

  const latestRun = new Map<string, Run>();
  for (const { run } of dir.runs) if (run.campaign_id && !latestRun.has(run.campaign_id)) latestRun.set(run.campaign_id, run);
  const card = new Map((feed.data?.campaigns ?? []).map((c) => [c.campaign_id, c]));
  const actions = (feed.data?.campaigns ?? [])
    .flatMap((c) => c.next_actions.map((a) => ({ a, c })))
    .sort((x, y) => x.a.priority - y.a.priority)
    .slice(0, 8);
  const firstRun = !dir.pending && !dir.error && dir.totalBrands === 0;

  return (
    <WorkspaceShell campaignId={dir.campaigns[0]?.id ?? null} active="today">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-border pb-5">
        <div className="space-y-1.5">
          <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Today</h1>
          <p className="text-[14.5px] text-ink-secondary">
            {today ? `${today}. ` : ""}What changed, what is open, and what to do next, across every campaign you can open.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <CommandBarButton />
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
              <section aria-labelledby="next" className="clay-panel tint-peach border border-border/50 p-4 sm:p-5">
                <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
                  <h2 id="next" className="text-[15px] font-semibold text-ink">
                    Next actions
                  </h2>
                  <span className="type-meta">Fixed rules over saved records, most urgent first</span>
                </div>
                {feed.isPending ? (
                  <LoadingState label="Working out what is next…" className="py-3" />
                ) : feed.error ? (
                  <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
                ) : actions.length === 0 ? (
                  <p className="px-1 py-2 text-[13.5px] text-ink-secondary">
                    Nothing is waiting. Every brief is complete and no run, verdict or evidence conflict needs a person.
                  </p>
                ) : (
                  <ol className="ledger-rules margin-rule clay-well overflow-hidden rounded-xl pl-2">
                    {actions.map(({ a, c }, i) => {
                      const ws = WORKSPACES[a.workspace];
                      return (
                        <li key={a.id} className="ledger-ink" style={{ animationDelay: `${Math.min(i, 8) * 45}ms` }}>
                          <Link href={workspaceHref(c.campaign_id, a.workspace)} className="group flex items-start gap-3 px-3.5 py-2.5 hover:bg-surface-muted/60 focus-visible:-outline-offset-2">
                            <ws.Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", a.priority === 1 ? "text-warning" : "text-ink-muted")} />
                            <span className="min-w-0 flex-1">
                              <span className="block text-[14px] font-medium text-ink">{a.title}</span>
                              <span className="block truncate text-[12.5px] text-ink-secondary">{a.reason}</span>
                              <span className="type-meta">
                                {ws.label} · {c.name}
                              </span>
                            </span>
                            {a.priority === 1 && <Tag className="border-warning/30 bg-warning-soft text-warning">Needs a person</Tag>}
                            <ArrowUpRight aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-muted group-hover:text-rose" />
                          </Link>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </section>

              <section aria-labelledby="campaigns" className="clay-panel border border-border/50 p-4 sm:p-5">
                <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
                  <h2 id="campaigns" className="text-[15px] font-semibold text-ink">
                    Campaigns and readiness
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
                    <table className="type-ledger w-full min-w-[46rem] text-left text-[13.5px]">
                      <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
                        <tr>
                          <th scope="col" className="px-3.5 py-2 font-medium">Campaign</th>
                          <th scope="col" className="px-3 py-2 font-medium">Brief</th>
                          <th scope="col" className="px-3 py-2 font-medium">Readiness by region</th>
                          <th scope="col" className="px-3 py-2 font-medium">Last run</th>
                          <th scope="col" className="px-3 py-2 font-medium">Updated</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {dir.campaigns.map((c) => {
                          const run = latestRun.get(c.id);
                          const t = card.get(c.id);
                          return (
                            <tr key={c.id} className="align-top hover:bg-surface-muted/60">
                              <th scope="row" className="px-3.5 py-2.5 text-left font-normal">
                                <Link href={workspaceHref(c.id, "desk")} className="font-semibold text-ink hover:text-rose hover:underline">
                                  {c.name}
                                </Link>
                                <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-ink-muted">
                                  {c.brand.name}
                                  {c.brand.mode === "demo" && <ModeBadge mode="demo" />}
                                </span>
                              </th>
                              <td className="px-3 py-2.5">{t ? <BriefCell c={t} /> : feed.isPending ? <span className="text-ink-muted">Reading…</span> : <span className="text-ink-muted">Not available</span>}</td>
                              <td className="px-3 py-2.5">
                                {!t ? (
                                  <span className="text-ink-muted">{feed.isPending ? "Reading…" : "Not available"}</span>
                                ) : t.readiness.length === 0 ? (
                                  <span className="text-ink-muted">No verdict yet</span>
                                ) : (
                                  <ul className="space-y-1">
                                    {t.readiness.map((r) => (
                                      <li key={r.region_code} className="flex flex-wrap items-center gap-2" title={`${r.main_reason} (rules ${r.rule_version}, ${formatDateTime(r.computed_at)})`}>
                                        <Verdict value={r.verdict} />
                                        <span className="text-[12.5px] text-ink-body">{r.region_name}</span>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </td>
                              <td className="px-3 py-2.5 whitespace-nowrap">{run ? <RunStatusBadge status={run.status} /> : <span className="text-ink-muted">No runs</span>}</td>
                              <td className="px-3 py-2.5 whitespace-nowrap text-ink-secondary" title={formatDateTime(c.updated_at)}>
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

              <section aria-labelledby="changed" className="clay-panel border border-border/50 p-4 sm:p-5">
                <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
                  <h2 id="changed" className="text-[15px] font-semibold text-ink">
                    What changed
                  </h2>
                  <span className="type-meta">Newest first, across every workspace</span>
                </div>
                {feed.isPending ? (
                  <LoadingState label="Reading recent changes…" className="py-3" />
                ) : feed.error ? (
                  <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
                ) : feed.data.activity.length === 0 ? (
                  <EmptyState
                    title="Nothing has changed yet"
                    description="Saving a brief, uploading a creative, running a Quick Read or computing a readiness verdict will appear here, with who or what did it."
                  />
                ) : (
                  <ol className="ledger-rules clay-well overflow-hidden rounded-xl">
                    {feed.data.activity.map((e, i) => (
                      <EventRow key={e.id} e={e} index={i} />
                    ))}
                  </ol>
                )}
                {feed.data && feed.data.limitations.length > 0 && (
                  <ul className="mt-3 space-y-1 text-[12px] text-ink-muted">
                    {feed.data.limitations.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                )}
              </section>
            </div>

            <div className="min-w-0 space-y-6 self-start">
              <aside aria-labelledby="conflicts" className="clay-panel tint-rose min-w-0 border border-border/50 p-4 sm:p-5">
                <div className="mb-2.5 flex items-baseline justify-between gap-2">
                  <h2 id="conflicts" className="inline-flex items-center gap-1.5 text-[15px] font-semibold text-ink">
                    <GitCompareArrows aria-hidden className="size-4 text-ink-muted" />
                    Open evidence conflicts
                  </h2>
                  {feed.data && <span className="type-meta tabular-nums">{feed.data.conflicts.length}</span>}
                </div>
                {feed.isPending ? (
                  <LoadingState label="Checking evidence…" className="py-3" />
                ) : feed.error ? (
                  <p className="text-[13px] text-danger">Could not read the conflicts.</p>
                ) : feed.data.conflicts.length === 0 ? (
                  <p className="rounded-card border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-muted">
                    No open conflicts. Sources do not currently disagree on anything your campaigns rely on.
                  </p>
                ) : (
                  <ol className="ledger-rules clay-well rounded-xl">
                    {feed.data.conflicts.map((c) => {
                      const target = c.campaign_ids[0] ?? dir.campaigns[0]?.id;
                      const inner = (
                        <>
                          <span className="flex items-baseline justify-between gap-2">
                            <span className="text-[13.5px] font-medium text-ink">{c.region_name ?? "Workspace-wide"}</span>
                            <span className="type-meta">{c.status === "open" ? "Open" : "Review requested"}</span>
                          </span>
                          <span className="mt-0.5 block text-[12.5px] text-ink-secondary">{c.reason}</span>
                          <span className="mt-1 grid gap-0.5 text-[12px] text-ink-body">
                            <span>
                              <span className="type-meta mr-1.5">A</span>
                              {c.claim_a}
                            </span>
                            <span>
                              <span className="type-meta mr-1.5">B</span>
                              {c.claim_b}
                            </span>
                          </span>
                        </>
                      );
                      return (
                        <li key={c.id}>
                          {target ? (
                            <Link href={workspaceHref(target, "lens")} className="block px-3.5 py-2.5 hover:bg-surface-muted/60 focus-visible:-outline-offset-2">
                              {inner}
                            </Link>
                          ) : (
                            <div className="px-3.5 py-2.5">{inner}</div>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </aside>

              <aside aria-labelledby="recent-runs" className="clay-panel tint-sky min-w-0 border border-border/50 p-4 sm:p-5">
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
                    {dir.runs.slice(0, 10).map(({ run, brand }) => {
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
          </div>
        )}
      </div>
    </WorkspaceShell>
  );
}
