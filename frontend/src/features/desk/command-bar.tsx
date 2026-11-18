"use client";

import { useQuery } from "@tanstack/react-query";
import { Command as CommandPrimitive } from "cmdk";
import { Coins, CornerDownLeft, FlaskConical, Layers, LayoutList, Palette, PencilLine, Plus, Search, Settings, Wand2 } from "lucide-react";
import { useParams, usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

import { RoleMark } from "@/components/creative/role-mark";
import { markFeatureNav } from "@/components/shell/feature-nav";
import { PLATFORM_FEATURES, WORKSPACES, WORKSPACE_ORDER, featureHref, isWorkspaceKey, workspaceHref, type Feature, type WorkspaceKey } from "@/components/shell/workspaces";
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandItem, CommandList, CommandSeparator } from "@/components/ui/command";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

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
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title="Command Bar"
        description="Jump to a workspace or campaign, or run a common action. Arrow keys move, Enter runs, Escape closes."
        className="top-[14%] rounded-[20px]! border border-border/60 bg-surface shadow-float ring-0 duration-200 sm:max-w-2xl"
      >
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
const FEATURE_ENTRIES: { feature: Feature; place: string; Icon: typeof Layers; key: WorkspaceKey | null }[] = [
  ...WORKSPACE_ORDER.flatMap((key) => WORKSPACES[key].features.map((feature) => ({ feature, place: WORKSPACES[key].label, Icon: WORKSPACES[key].Icon, key }))),
  ...PLATFORM_FEATURES.map((feature) => ({ feature, place: "Platform", Icon: Layers, key: null })),
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
      className="clay group inline-flex h-8 items-center gap-2 rounded-lg border border-border px-2.5 text-[13px] text-ink-secondary transition-[color,translate] duration-200 hover:-translate-y-px hover:text-ink"
    >
      <Search aria-hidden className="size-4 text-pop transition-[rotate] duration-300 group-hover:-rotate-12" />
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
    <Command label="Command Bar" className="max-h-[min(34rem,74dvh)] rounded-[20px]! bg-surface p-0">
      <div className="flex items-center gap-3 border-b border-border px-4">
        <Search aria-hidden className="size-5 shrink-0 text-pop" />
        <CommandPrimitive.Input
          autoFocus
          placeholder="Go to a workspace or campaign, or run an action"
          className="h-14 w-full min-w-0 bg-transparent text-[16px] text-ink placeholder:text-ink-muted"
        />
        <kbd className="hidden shrink-0 rounded-md border border-border bg-surface-muted px-1.5 py-0.5 font-mono text-[10.5px] text-ink-muted sm:block">Esc</kbd>
      </div>
      <CommandList className="max-h-[min(26rem,56dvh)] p-2">
        <CommandEmpty className="flex flex-col items-center gap-2 py-8 text-[13.5px] text-ink-secondary">
          <Search aria-hidden className="size-5 text-ink-muted" />
          Nothing matches. Try a workspace, a campaign or an action.
        </CommandEmpty>

        <CommandGroup heading={campaignLabel ? `Workspaces in ${campaignLabel}` : "Workspaces"} className={GROUP}>
          <CommandItem value="today all campaigns home" onSelect={() => go("/app")} className={ITEM}>
            <Tile>
              <LayoutList aria-hidden />
            </Tile>
            Today
            <span className="ml-auto text-xs text-ink-muted">All campaigns</span>
          </CommandItem>
          {activeId &&
            WORKSPACE_ORDER.map((key) => {
              const ws = WORKSPACES[key];
              return (
                <CommandItem key={key} value={`workspace ${ws.label} ${key}`} onSelect={() => go(workspaceHref(activeId, key))} className={ITEM}>
                  <RoleMark workspace={key} size="xs" />
                  {ws.label}
                  <span className="ml-auto font-mono text-[11px] text-ink-muted">{here === key ? "here" : ws.number}</span>
                </CommandItem>
              );
            })}
        </CommandGroup>

        {activeId && (
          <>
            <CommandSeparator className="my-1" />
            <CommandGroup heading="Open feature" className={GROUP}>
              {FEATURE_ENTRIES.map(({ feature, place, Icon, key }) => (
                <CommandItem key={feature.id} value={`open feature ${feature.name} ${place}`} onSelect={() => go(featureHref(feature, activeId)!)} className={ITEM}>
                  {key ? (
                    <RoleMark workspace={key} size="xs" />
                  ) : (
                    <Tile>
                      <Icon aria-hidden />
                    </Tile>
                  )}
                  {feature.name}
                  <span className="ml-auto text-xs text-ink-muted">{place}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        <CommandSeparator className="my-1" />
        <CommandGroup heading="Actions" className={GROUP}>
          <CommandItem value="new campaign create brand" onSelect={() => go("/app?new=campaign")} className={ITEM}>
            <Tile tone="pop">
              <Plus aria-hidden />
            </Tile>
            New campaign
          </CommandItem>
          {activeId && (
            <>
              <CommandItem value="start quick read audience lab synthetic panel" onSelect={() => go(`${workspaceHref(activeId, "lab")}?start=quick-read`)} className={ITEM}>
                <RoleMark workspace="lab" size="xs" />
                Start a Quick Read
                <span className="ml-auto text-xs text-ink-muted">Audience Lab</span>
              </CommandItem>
              {latestReport.data && (
                <CommandItem value="open latest report proof" onSelect={() => go(`${workspaceHref(activeId, "proof")}?report=${latestReport.data!.id}`)} className={ITEM}>
                  <RoleMark workspace="proof" size="xs" />
                  Open the latest report
                  <span className="ml-auto text-xs text-ink-muted">
                    v{latestReport.data.version_number}, {formatRelative(latestReport.data.created_at)}
                  </span>
                </CommandItem>
              )}
              <CommandItem
                value="direct this version voice director instruction speak say studio"
                onSelect={() => {
                  if (here === "studio") {
                    close();
                    window.dispatchEvent(new CustomEvent("omnicult:studio-tab", { detail: "direct" }));
                  } else go(`${workspaceHref(activeId, "studio")}?tab=direct`);
                }}
                className={ITEM}
              >
                <Tile>
                  <Wand2 aria-hidden />
                </Tile>
                Direct this version…
                <span className="ml-auto text-xs text-ink-muted">Creative Studio</span>
              </CommandItem>
              <CommandItem value="edit brief campaign desk" onSelect={() => go(`${workspaceHref(activeId, "desk")}?edit=brief`)} className={ITEM}>
                <Tile>
                  <PencilLine aria-hidden />
                </Tile>
                Edit the brief
              </CommandItem>
              <CommandItem value="open brand kit logo colours fonts" onSelect={() => go(`${workspaceHref(activeId, "desk")}?tab=brand-kit`)} className={ITEM}>
                <Tile>
                  <Palette aria-hidden />
                </Tile>
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
            className={ITEM}
          >
            <Tile>
              <FlaskConical aria-hidden />
            </Tile>
            Try the demo
            <span className="ml-auto text-xs text-ink-muted">Labelled sample data</span>
          </CommandItem>
        </CommandGroup>

        <CommandSeparator className="my-1" />
        <CommandGroup heading="Platform" className={GROUP}>
          <CommandItem value="usage and credits spend cost budget model calls" onSelect={() => go("/app/usage")} className={ITEM}>
            <Tile>
              <Coins aria-hidden />
            </Tile>
            Usage and credits
            <span className="ml-auto text-xs text-ink-muted">Spend, budget, failed calls</span>
          </CommandItem>
          <CommandItem value="team settings members roles invites country pack" onSelect={() => go("/app/settings")} className={ITEM}>
            <Tile>
              <Settings aria-hidden />
            </Tile>
            Team and settings
            <span className="ml-auto text-xs text-ink-muted">Members, roles, Country Pack</span>
          </CommandItem>
        </CommandGroup>

        {campaigns.length > 0 && (
          <>
            <CommandSeparator className="my-1" />
            <CommandGroup heading="Campaigns" className={GROUP}>
              {campaigns.map((c) => (
                <CommandItem key={c.id} value={`campaign ${c.name} ${c.brand.name} ${c.id}`} onSelect={() => go(workspaceHref(c.id, here ?? "desk"))} className={ITEM}>
                  <Tile>
                    <Layers aria-hidden />
                  </Tile>
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
        {dir.pending && (
          <p role="status" className="px-3 py-2 text-xs text-ink-muted">
            Loading campaigns…
          </p>
        )}
      </CommandList>
      <div className="flex items-center gap-4 border-t border-border bg-surface-muted/50 px-4 py-2.5 text-[11.5px] text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <kbd className={KBD}>↑</kbd>
          <kbd className={KBD}>↓</kbd>
          move
        </span>
        <span className="inline-flex items-center gap-1.5">
          <kbd className={KBD}>
            <CornerDownLeft aria-hidden className="size-3" />
          </kbd>
          runs
        </span>
        <span className="inline-flex items-center gap-1.5">
          <kbd className={KBD}>Esc</kbd>
          closes
        </span>
      </div>
    </Command>
  );
}

const KBD = "inline-grid min-w-5 place-items-center rounded-md border border-border bg-surface-raised px-1 py-0.5 font-mono text-[10.5px] text-ink-secondary shadow-clay";
const GROUP = "p-0 pb-1 **:[[cmdk-group-heading]]:px-2.5 **:[[cmdk-group-heading]]:pt-2 **:[[cmdk-group-heading]]:pb-1.5 **:[[cmdk-group-heading]]:text-[11.5px] **:[[cmdk-group-heading]]:text-ink-muted";
const ITEM =
  "gap-3 px-2.5 py-1.5 text-[14px] text-ink in-data-[slot=dialog-content]:rounded-xl! data-selected:bg-surface-raised data-selected:shadow-clay data-selected:[&_.ml-auto]:text-ink-secondary";

/** A small clay well for an action's icon (workspace entries use their RoleMark instead). */
function Tile({ children, tone }: { children: ReactNode; tone?: "pop" }) {
  return (
    <span aria-hidden className={cn("grid size-6 shrink-0 place-items-center rounded-md shadow-well [&>svg]:size-3.5!", tone === "pop" ? "bg-pop text-pop-ink" : "bg-surface-muted text-ink-secondary")}>
      {children}
    </span>
  );
}