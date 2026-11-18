"use client";

import { FlaskConical, Plus } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { CountUp, EmptyIllustration, INDIA_TILES, Reveal } from "@/components/creative";
import { WorkspaceShell } from "@/components/shell/workspace-shell";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import type { Run } from "@/lib/api/types";

import { useToday } from "./api";
import { CommandBarButton } from "./command-bar";
import { NewCampaign } from "./new-campaign";
import { ChangesTile, ConflictsTile, HeroCampaign, MoreCampaigns, NextActionsTile, ReadinessTile, RunsTile, TodaySkeleton } from "./today-parts";
import { DIRECTORY_BRAND_LIMIT, useCampaignDirectory } from "./use-campaign-directory";
import { DemoSignInError, useStartDemo } from "./use-start-demo";

const noop = () => () => {};
const dateLabel = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long" });
function useToday_() {
  return useSyncExternalStore(noop, () => dateLabel.format(new Date()), () => null);
}

const plural = (n: number, one: string, many = `${one}s`) => (n === 1 ? one : many);

/**
 * Campaign Desk home: Today across every campaign the account can open, as a studio bento. The latest campaign leads
 * with its own creative (scrub its film to change the poster), readiness verdicts land on the map (click a state to
 * filter the lists), and the saved changes run along a scrubbable ribbon. Every number comes from a saved record.
 */
export function TodayView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const today = useToday_();
  const dir = useCampaignDirectory({ withRuns: true });
  const feed = useToday();
  const demo = useStartDemo();
  const [region, setRegion] = useState<string | null>(null);
  const composing = params.get("new") === "campaign";
  const setComposing = (open: boolean) => router.replace(open ? `${pathname}?new=campaign` : pathname, { scroll: false });

  const latestRun = new Map<string, Run>();
  for (const { run } of dir.runs) if (run.campaign_id && !latestRun.has(run.campaign_id)) latestRun.set(run.campaign_id, run);
  const cards = new Map((feed.data?.campaigns ?? []).map((c) => [c.campaign_id, c]));
  const actions = (feed.data?.campaigns ?? [])
    .flatMap((c) => c.next_actions.map((a) => ({ a, c })))
    .sort((x, y) => x.a.priority - y.a.priority)
    .slice(0, 8);
  const firstRun = !dir.pending && !dir.error && dir.totalBrands === 0;
  const hero = dir.campaigns[0];
  const regionName = region ? (INDIA_TILES[region]?.name ?? null) : null;
  const verdicts = (feed.data?.campaigns ?? []).flatMap((c) => c.readiness);
  const goCount = verdicts.filter((r) => r.verdict === "go").length;
  const fixCount = verdicts.filter((r) => r.verdict === "fix").length;
  const rethinkCount = verdicts.filter((r) => r.verdict === "rethink").length;
  const total = `${dir.campaigns.length} ${plural(dir.campaigns.length, "campaign")} across ${dir.brands.length} ${plural(dir.brands.length, "brand")}${
    dir.totalBrands > DIRECTORY_BRAND_LIMIT ? ` (the ${DIRECTORY_BRAND_LIMIT} most recent of ${dir.totalBrands})` : ""
  }`;

  return (
    <WorkspaceShell campaignId={dir.campaigns[0]?.id ?? null} active="today">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 space-y-2">
          <h1 className="type-hero text-[40px] text-ink sm:text-[48px]">Today</h1>
          {/* The day in one sentence, every number live from the API; each part jumps to its tile. */}
          {!feed.data || firstRun ? (
            <p className="max-w-[68ch] text-[15px] leading-relaxed text-ink-secondary">
              {today ? `${today}. ` : ""}What changed, what is open, and what to do next, across every campaign you can open.
            </p>
          ) : (
            <p className="max-w-[68ch] text-[15px] leading-relaxed text-ink-secondary">
              {today ? `${today}. ` : ""}
              <CountUp value={dir.campaigns.length} className="font-semibold text-ink" /> {plural(dir.campaigns.length, "campaign")} in motion
              {verdicts.length > 0 && (
                <>
                  , with <CountUp value={goCount} className="font-semibold text-success" /> Go, <CountUp value={fixCount} className="font-semibold text-warning" /> Fix
                  {rethinkCount > 0 && (
                    <>
                      {" "}
                      and <CountUp value={rethinkCount} className="font-semibold text-danger" /> Rethink
                    </>
                  )}{" "}
                  across the regions
                </>
              )}
              .{" "}
              <a href="#next" className="underline decoration-border-strong underline-offset-4 hover:text-ink hover:decoration-pop">
                <CountUp value={actions.length} className="font-semibold text-ink" /> next {plural(actions.length, "action")}
              </a>
              ,{" "}
              <a href="#conflicts" className="underline decoration-border-strong underline-offset-4 hover:text-ink hover:decoration-pop">
                <CountUp value={feed.data.conflicts.length} className="font-semibold text-ink" /> open {plural(feed.data.conflicts.length, "conflict")}
              </a>{" "}
              and{" "}
              <a href="#changes" className="underline decoration-border-strong underline-offset-4 hover:text-ink hover:decoration-pop">
                <CountUp value={feed.data.activity.length} className="font-semibold text-ink" /> saved {plural(feed.data.activity.length, "change")}
              </a>
              .
            </p>
          )}
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

      <div className="space-y-5">
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
          <TodaySkeleton />
        ) : firstRun ? (
          <EmptyState
            illustration={<EmptyIllustration kind="ledger" className="h-28" />}
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
        ) : !hero ? (
          <EmptyState
            illustration={<EmptyIllustration kind="film" />}
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
          <div className="space-y-4">
            {/* Two stacks instead of grid rows, so tiles of different heights never leave holes. Reading order is the
                left stack (the campaign, what to do, what changed), then the right (where it stands, conflicts, runs). */}
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
              <div className="flex min-w-0 flex-col gap-4 lg:w-[58%] lg:flex-none">
                <Reveal index={0}>
                  <HeroCampaign campaign={hero} card={cards.get(hero.id)} run={latestRun.get(hero.id)} />
                </Reveal>
                <Reveal index={2}>
                  <NextActionsTile
                    actions={actions}
                    regionName={regionName}
                    onClearRegion={() => setRegion(null)}
                    pending={feed.isPending}
                    error={feed.error}
                    onRetry={() => void feed.refetch()}
                  />
                </Reveal>
                <Reveal index={4}>
                  <ChangesTile
                    events={feed.data?.activity ?? []}
                    regionName={regionName}
                    onClearRegion={() => setRegion(null)}
                    pending={feed.isPending}
                    error={feed.error}
                    onRetry={() => void feed.refetch()}
                  />
                </Reveal>
              </div>
              <div className="flex min-w-0 flex-1 flex-col gap-4">
                <Reveal index={1}>
                  <ReadinessTile campaigns={dir.campaigns} cards={cards} region={region} onRegion={setRegion} pending={feed.isPending} />
                </Reveal>
                <Reveal index={3}>
                  <ConflictsTile conflicts={feed.data?.conflicts ?? []} fallbackCampaign={hero.id} regionName={regionName} pending={feed.isPending} error={feed.error} />
                </Reveal>
                <Reveal index={5}>
                  <RunsTile runs={dir.runs} pending={dir.runsPending} />
                </Reveal>
              </div>
            </div>
            {dir.campaigns.length > 1 && <MoreCampaigns campaigns={dir.campaigns.slice(1)} cards={cards} latestRun={latestRun} total={total} />}
          </div>
        )}

        {feed.data && feed.data.limitations.length > 0 && !firstRun && <p className="max-w-[90ch] text-[12px] text-ink-muted">{feed.data.limitations.join(" ")}</p>}
      </div>
    </WorkspaceShell>
  );
}
