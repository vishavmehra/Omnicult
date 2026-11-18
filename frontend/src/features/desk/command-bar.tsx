"use client";

import { useQuery } from "@tanstack/react-query";
import { Coins, CornerDownLeft, FlaskConical, Layers, LayoutList, Palette, PencilLine, Plus, Search, Signpost, Vault, Wand2 } from "lucide-react";
import { useParams, usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

import { markFeatureNav } from "@/components/shell/feature-nav";
import { PLATFORM_FEATURES, WORKSPACES, WORKSPACE_ORDER, featureHref, isWorkspaceKey, workspaceHref, type Feature, type WorkspaceKey } from "@/components/shell/workspaces";
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from "@/components/ui/command";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatRelative } from "@/lib/format";

import { useCampaignDirectory } from "./use-campaign-directory";
import { useStartDemo } from "./use-start-demo";

type BarContext = { open: boolean; setOpen(open: boolean): void };
const CommandBarContext = createContext<BarContext | null>(null);

const noop = () => () => {};
/** "⌘K" on Apple platforms, "Ctrl K" elsewhere. The server render says "Ctrl K". */
function useShortcutLabel() {
  return useSyncExternalStore(noop, () => (/mac|iphone|ipad/i.test(navigator.platform) ? "⌘K" : "Ctrl K"), () => "Ctrl K");
}

/** Mounts the Command Bar once for every /app page and opens it with Ctrl+K or Cmd+K. */
export function CommandBarProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const value = useMemo(() => ({ open, setOpen }), [open]);
  return (
    <CommandBarContext.Provider value={value}>
      {children}
      <CommandDialog open={open} onOpenChange={setOpen} title="Command Bar" description="Jump to a workspace or campaign, or run a common action. Arrow keys move, Enter runs, Escape closes." className="sm:max-w-xl">
        {open && <BarContent close={() => setOpen(false)} />}
      </CommandDialog>
    </CommandBarContext.Provider>
  );
}

/** Opens the Command Bar from elsewhere (the spine's Command Bar entry). Null outside /app. */
export function useOpenCommandBar() {
  return useContext(CommandBarContext)?.setOpen ?? null;
}

/** Every built feature with a deep link, from the catalogue in components/shell/workspaces.ts, with the place it lives in. */
const FEATURE_ENTRIES: { feature: Feature; place: string; Icon: typeof Layers }[] = [
  ...WORKSPACE_ORDER.flatMap((key) => WORKSPACES[key].features.map((feature) => ({ feature, place: WORKSPACES[key].label, Icon: WORKSPACES[key].Icon }))),
  ...PLATFORM_FEATURES.map((feature) => ({ feature, place: "Platform", Icon: Layers })),
].filter(({ feature }) => feature.status === "built" && feature.href);

/** A visible way in for pointer and touch users: the keyboard shortcut is named on the button. */
export function CommandBarButton() {
  const ctx = useContext(CommandBarContext);
  const label = useShortcutLabel();
  if (!ctx) return null;
  return (
    <button
      type="button"
      onClick={() => ctx.setOpen(true)}
      aria-keyshortcuts="Control+K Meta+K"
      className="clay inline-flex h-8 items-center gap-2 rounded-lg border border-border px-2.5 text-[13px] text-ink-secondary hover:text-ink"
    >
      <Search aria-hidden className="size-4" />
      Command Bar
      <kbd className="rounded-sm border border-border bg-surface-muted px-1.5 py-0.5 font-mono text-[10.5px] text-ink-muted">{label}</kbd>
    </button>
  );
}

function BarContent({ close }: { close(): void }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams<{ campaignId?: string }>();
  const dir = useCampaignDirectory();
  const demo = useStartDemo();

  const inCampaign = params.campaignId ?? null;
  const campaigns = dir.campaigns;
  const active = campaigns.find((c) => c.id === inCampaign) ?? (inCampaign ? null : (campaigns[0] ?? null));
  const activeId = inCampaign ?? active?.id ?? null;
  const here: WorkspaceKey | null = (() => {
    const seg = pathname.split("/")[4];
    return isWorkspaceKey(seg) ? seg : null;
  })();

  const latestReport = useQuery({
    queryKey: ["desk", "latest-report", activeId],
    enabled: Boolean(activeId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/campaigns/{campaign_id}/proof-reports", { params: { path: { campaign_id: activeId! }, query: { limit: 1 } } }))).items[0] ?? null,
  });

  const go = useCallback(
    (href: string) => {
      close();
      markFeatureNav(href);
      router.push(href);
    },
    [close, router],
  );

  const campaignLabel = active ? active.name : null;

  return (
    <Command label="Command Bar" className="max-h-[min(30rem,70dvh)]">
      <CommandInput placeholder="Go to a workspace or campaign, or run an action" autoFocus />
      <CommandList className="max-h-[min(24rem,52dvh)]">
        <CommandEmpty>Nothing matches. Try a workspace, a campaign or an action.</CommandEmpty>

        <CommandGroup heading={campaignLabel ? `Workspaces in ${campaignLabel}` : "Workspaces"}>
          <CommandItem value="today all campaigns home" onSelect={() => go("/app")}>
            <LayoutList aria-hidden />
            Today
            <span className="ml-auto text-xs text-ink-muted">All campaigns</span>
          </CommandItem>
          {activeId
            ? WORKSPACE_ORDER.map((key) => {
                const ws = WORKSPACES[key];
                return (
                  <CommandItem key={key} value={`workspace ${ws.label} ${key}`} onSelect={() => go(workspaceHref(activeId, key))}>
                    <ws.Icon aria-hidden />
                    {ws.label}
                    <span className="ml-auto font-mono text-[11px] text-ink-muted">{here === key ? "here" : ws.number}</span>
                  </CommandItem>
                );
              })
            : (
              <CommandItem disabled value="workspaces need a campaign">
                Create or open a campaign to reach the seven workspaces
              </CommandItem>
            )}
        </CommandGroup>

        {activeId && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Open feature…">
              {FEATURE_ENTRIES.map(({ feature, place, Icon }) => (
                <CommandItem key={feature.id} value={`open feature ${feature.name} ${place}`} onSelect={() => go(featureHref(feature, activeId)!)}>
                  <Icon aria-hidden />
                  {feature.name}
                  <span className="ml-auto text-xs text-ink-muted">{place}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        <CommandSeparator />
        <CommandGroup heading="Actions">
          <CommandItem value="new campaign create brand" onSelect={() => go("/app?new=campaign")}>
            <Plus aria-hidden />
            New campaign
          </CommandItem>
          {activeId && (
            <>
              <CommandItem value="start quick read audience lab synthetic panel" onSelect={() => go(`${workspaceHref(activeId, "lab")}?start=quick-read`)}>
                <WORKSPACES.lab.Icon aria-hidden />
                Start a Quick Read
                <span className="ml-auto text-xs text-ink-muted">Audience Lab</span>
              </CommandItem>
              {latestReport.data ? (
                <CommandItem value="open latest report proof" onSelect={() => go(`${workspaceHref(activeId, "proof")}?report=${latestReport.data!.id}`)}>
                  <Vault aria-hidden />
                  Open the latest report
                  <span className="ml-auto text-xs text-ink-muted">v{latestReport.data.version_number}, {formatRelative(latestReport.data.created_at)}</span>
                </CommandItem>
              ) : (
                <CommandItem disabled value="open latest report proof none">
                  <Vault aria-hidden />
                  {latestReport.isPending ? "Looking for the latest report…" : "No report yet for this campaign"}
                </CommandItem>
              )}
              <CommandItem value="direct this version voice director instruction speak say studio" onSelect={() => {
                  if (here === "studio") {
                    close();
                    window.dispatchEvent(new CustomEvent("omnicult:studio-tab", { detail: "direct" }));
                  } else go(`${workspaceHref(activeId, "studio")}?tab=direct`);
                }}>
                <Wand2 aria-hidden />
                Direct this version…
                <span className="ml-auto text-xs text-ink-muted">Creative Studio</span>
              </CommandItem>
              <CommandItem value="edit brief campaign desk" onSelect={() => go(`${workspaceHref(activeId, "desk")}?edit=brief`)}>
                <PencilLine aria-hidden />
                Edit the brief
              </CommandItem>
              <CommandItem value="open brand kit logo colours fonts" onSelect={() => go(`${workspaceHref(activeId, "desk")}?tab=brand-kit`)}>
                <Palette aria-hidden />
                Open the Brand Kit
              </CommandItem>
            </>
          )}
          <CommandItem
            value="try the demo sample brand fixtures"
            onSelect={() => {
              close();
              demo.mutate();
            }}
          >
            <FlaskConical aria-hidden />
            Try the demo
            <span className="ml-auto text-xs text-ink-muted">Labelled sample data</span>
          </CommandItem>
        </CommandGroup>

        <CommandSeparator />
        <CommandGroup heading="Platform">
          <CommandItem value="usage and credits spend cost budget model calls" onSelect={() => go("/app/usage")}>
            <Coins aria-hidden />
            Usage and credits
            <span className="ml-auto text-xs text-ink-muted">Spend, budget, failed calls</span>
          </CommandItem>
          <CommandItem value="roadmap planned features not built share of search video push connect accounts" onSelect={() => go("/app/roadmap")}>
            <Signpost aria-hidden />
            Roadmap
            <span className="ml-auto text-xs text-ink-muted">Planned, not built</span>
          </CommandItem>
        </CommandGroup>

        {campaigns.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Campaigns">
              {campaigns.map((c) => (
                <CommandItem key={c.id} value={`campaign ${c.name} ${c.brand.name} ${c.id}`} onSelect={() => go(workspaceHref(c.id, here ?? "desk"))}>
                  <span className="min-w-0 flex-1 truncate">{c.name}</span>
                  <span className="max-w-[40%] shrink-0 truncate text-xs text-ink-muted">
                    {c.brand.name}
                    {c.brand.mode === "demo" ? " · demo" : ""}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
        {dir.pending && <p role="status" className="px-3 py-2 text-xs text-ink-muted">Loading campaigns…</p>}
      </CommandList>
      <div className="flex items-center gap-3 border-t border-border px-3 py-2 text-[11.5px] text-ink-muted">
        <span>Arrow keys move</span>
        <span className="inline-flex items-center gap-1">
          <CornerDownLeft aria-hidden className="size-3" />
          runs
        </span>
        <span>Esc closes</span>
      </div>
    </Command>
  );
}
