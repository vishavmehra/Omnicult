"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Coins, LayoutList, LogOut, Menu, Moon, PanelRightClose, PanelRightOpen, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTheme } from "next-themes";
import { createPortal } from "react-dom";

import { roleColor } from "@/components/creative/motion";
import { ModeBadge } from "@/components/evidence/badges";
import { EvidenceInspectorProvider } from "@/components/evidence/evidence-inspector";
import { arrivingFromOutside } from "@/components/field/transition";
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { CommandBarButton } from "@/features/desk/command-bar";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { DataMode } from "@/lib/api/types";
import { signOut, useAccount } from "@/lib/auth/session";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

import { CampaignSelector } from "./campaign-selector";
import { FeatureRow, useActiveFeatureIds } from "./feature-links";
import { arrivedAt, latestFeatureNav } from "./feature-nav";
import { ThemeToggle } from "./theme-toggle";
import { Wordmark } from "./wordmark";
import { STAGES, WORKSPACES, navFeatures, workspaceHref, type WorkspaceKey } from "./workspaces";

// ---------- context panel slot ----------

type PanelSlot = { el: HTMLElement | null; register(): () => void };
const PanelContext = createContext<PanelSlot | null>(null);

/**
 * Renders its children into the shell's context panel: a docked clay panel from 1280px, a right-hand drawer below it (opened
 * from the header). Pages decide what context they need; the shell decides where it lives.
 */
export function ContextPanel({ title, children }: { title: string; children: ReactNode }) {
  const slot = useContext(PanelContext);
  const register = slot?.register;
  useEffect(() => register?.(), [register]);
  if (!slot?.el) return null;
  return createPortal(
    <div className="space-y-5">
      <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      {children}
    </div>,
    slot.el,
  );
}

// ---------- account ----------

function AccountMenu() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const account = useAccount();
  const { resolvedTheme, setTheme } = useTheme();
  const light = resolvedTheme === "light";
  const initial = account.status === "user" ? account.label[0]?.toUpperCase() : account.status === "anonymous" ? "A" : account.status === "dev" ? "D" : "·";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={`Account: ${account.label ?? "loading"}`}
        className="flex size-9 items-center justify-center rounded-full bg-surface-raised text-[13px] font-semibold text-ink shadow-clay"
      >
        {initial}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel>{account.label ?? "Account"}</DropdownMenuLabel>
          {account.status === "dev" && <DropdownMenuItem disabled>Local development token, no sign-in</DropdownMenuItem>}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={() => router.push("/app/settings")}>
            <Settings aria-hidden />
            Team and settings
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => router.push("/app/usage")}>
            <Coins aria-hidden />
            Usage
          </DropdownMenuItem>
          {/* The header's theme toggle makes way for the Command Bar on a phone; the same switch lives here. */}
          <DropdownMenuItem className="sm:hidden" onClick={() => setTheme(light ? "dark" : "light")}>
            {light ? <Moon aria-hidden /> : <Sun aria-hidden />}
            {light ? "Switch to the dark theme" : "Switch to the light theme"}
          </DropdownMenuItem>
        </DropdownMenuGroup>
        {env.authMode === "firebase" && account.status !== "signed-out" && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={async () => {
                await signOut();
                queryClient.clear();
                router.replace("/login");
              }}
            >
              <LogOut aria-hidden />
              Sign out
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// ---------- spine (navigation) ----------

/** Pages that sit beside the seven workspaces rather than inside a campaign. */
type PlatformPage = "today" | "settings" | "usage" | "roadmap";
const inCampaign = (active: WorkspaceKey | PlatformPage): active is WorkspaceKey => active in WORKSPACES;

/**
 * A halo that rides the workflow line to the active station, so moving between workspaces reads as travelling along the
 * line. Positioned by transform from a measurement after layout (and again when feature lists open or close); the first
 * placement skips the transition.
 */
function useStationHalo(active: string, deps: unknown) {
  const line = useRef<HTMLOListElement>(null);
  const halo = useRef<HTMLSpanElement>(null);
  const placed = useRef(false);
  useLayoutEffect(() => {
    const list = line.current;
    const ring = halo.current;
    if (!list || !ring) return;
    const place = () => {
      const station = list.querySelector<HTMLElement>("[data-station-active]");
      if (!station) {
        ring.style.opacity = "0";
        return;
      }
      const top = station.getBoundingClientRect().top - list.getBoundingClientRect().top + station.offsetHeight / 2 - 15;
      if (!placed.current) ring.style.transition = "none";
      ring.style.opacity = "1";
      ring.style.transform = `translateY(${top}px)`;
      if (!placed.current) {
        void ring.offsetWidth;
        ring.style.transition = "";
        placed.current = true;
      }
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(list);
    return () => ro.disconnect();
  }, [active, deps]);
  return { line, halo };
}

function Spine({ campaignId, active, onNavigate }: { campaignId: string | null; active: WorkspaceKey | PlatformPage; onNavigate?: () => void }) {
  const item = "group/item flex h-10 items-center gap-2.5 rounded-xl px-3 text-[14px] transition-[background-color,color,box-shadow] duration-200";
  const on = "bg-surface-raised font-medium text-ink shadow-clay";
  const off = "text-ink-secondary hover:bg-surface-muted/70 hover:text-ink";
  const nudge = "transition-[translate] duration-200 ease-out group-hover/item:translate-x-0.5";
  const activeIds = useActiveFeatureIds(campaignId);
  // The open workspace starts expanded and the others collapsed; a person's own choice wins until they leave.
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  const isOpen = (key: string, fallback: boolean) => chosen[key] ?? fallback;
  const toggle = (key: string, fallback: boolean) => setChosen((c) => ({ ...c, [key]: !(c[key] ?? fallback) }));
  const chevron = (open: boolean) => <ChevronRight aria-hidden className={cn("size-4 transition-transform duration-200 motion-reduce:transition-none", open && "rotate-90")} />;
  const featureList = "mt-0.5 mb-1 space-y-px";
  const { line, halo } = useStationHalo(active, chosen);
  return (
    <div className="flex h-full flex-col">
      <div className="px-4 pt-5 pb-5 text-ink">
        <Wordmark />
      </div>
      <nav aria-label="Workspaces" className="flex-1 overflow-y-auto px-2.5 pb-5">
        <Link href="/app" onClick={onNavigate} aria-current={active === "today" ? "page" : undefined} className={cn(item, "mb-4", active === "today" ? on : off)}>
          <LayoutList aria-hidden className={cn("size-[18px]", nudge, active === "today" && "text-pop")} />
          Today
        </Link>
        <ol ref={line} className="relative space-y-3.5">
          {/* The workflow line: stations sit on it in the order work moves; the halo marks where you are. */}
          <span aria-hidden className="absolute top-3 bottom-3 left-[23.5px] w-px bg-border" />
          <span
            ref={halo}
            aria-hidden
            className="pointer-events-none absolute top-0 left-[8.5px] z-20 size-[30px] rounded-full border-2 border-pop/45 opacity-0 shadow-[0_0_0_4px_color-mix(in_oklab,var(--pop)_12%,transparent)] transition-[transform,opacity] duration-500 ease-out"
          />
          {STAGES.map((stage) => (
            <li key={stage.key}>
              <p className="relative mb-1 ml-10 text-[11px] font-semibold tracking-[0.08em] text-ink-muted uppercase">{stage.label}</p>
              <ul className="space-y-0.5">
                {stage.workspaces.map((key) => {
                  const ws = WORKSPACES[key];
                  const isActive = active === key;
                  const open = isOpen(key, isActive);
                  const inner = (
                    <>
                      <span
                        aria-hidden
                        data-station-active={isActive ? "" : undefined}
                        className={cn(
                          "relative z-10 flex size-[22px] shrink-0 items-center justify-center rounded-full font-mono text-[10.5px] tabular-nums",
                          isActive ? "bg-pop text-pop-ink" : "border-[1.5px] bg-surface text-ink-secondary",
                        )}
                        style={isActive ? undefined : { borderColor: roleColor(key, true) }}
                      >
                        {ws.number}
                      </span>
                      <ws.Icon aria-hidden className={cn("size-4 shrink-0", nudge, isActive ? "text-pop" : "text-ink-muted")} />
                      <span className="truncate">{ws.label}</span>
                    </>
                  );
                  return (
                    <li key={key}>
                      {campaignId ? (
                        <div className="relative">
                          <Link href={workspaceHref(campaignId, key)} onClick={onNavigate} aria-current={isActive ? "page" : undefined} className={cn(item, "pr-8 max-lg:pr-11", isActive ? on : off)}>
                            {inner}
                          </Link>
                          <button
                            type="button"
                            onClick={() => toggle(key, isActive)}
                            aria-expanded={open}
                            aria-controls={`spine-${key}`}
                            aria-label={`${ws.label} features`}
                            className="absolute top-1.5 right-1 flex size-7 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-muted hover:text-ink max-lg:top-0.5 max-lg:size-9"
                          >
                            {chevron(open)}
                          </button>
                        </div>
                      ) : (
                        <span aria-disabled className={cn(item, off, "cursor-not-allowed opacity-60 hover:bg-transparent")} title="Create or open a campaign first">
                          {inner}
                        </span>
                      )}
                      {campaignId && (
                        <ul id={`spine-${key}`} aria-label={`${ws.label} features`} hidden={!open} className={cn(featureList, "ml-[30px]")}>
                          {navFeatures(key).map((f) => (
                            <FeatureRow key={f.id} feature={f} campaignId={campaignId} active={activeIds.has(f.id)} onNavigate={onNavigate} />
                          ))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ol>
      </nav>
    </div>
  );
}

/**
 * Some workspaces read their tab from the address only when they mount, so a jump to another tab of the page you are on
 * (a spine link, a header chip, the Command Bar) would change the address and leave the tab behind. After such a jump the
 * page is remounted from the new address. Anything else that changes the address, such as a tab clicked in the page, is left alone.
 */
function useRemountOnFeatureNav() {
  const pathname = usePathname();
  const search = useSearchParams();
  const query = search.toString();
  const [seen, setSeen] = useState(() => ({ pathname, query, count: 0, mark: latestFeatureNav()?.id ?? 0 }));
  if (seen.pathname !== pathname || seen.query !== query) {
    // The address changed. A jump marked since the last change is spent now, whether or not this was it.
    const mark = latestFeatureNav();
    const fresh = mark !== null && mark.id !== seen.mark;
    const hit = fresh && seen.pathname === pathname && arrivedAt(mark, pathname, search);
    setSeen({ pathname, query, count: seen.count + (hit ? 1 : 0), mark: mark?.id ?? seen.mark });
  }
  return seen.count;
}

// ---------- shell ----------

/**
 * The Omnicult frame: floating clay panels over the continuous ground. A spine with the seven workspaces as stations grouped
 * by stage, a header bar with the campaign selector and data mode, the main area, and an optional context panel.
 */
export function WorkspaceShell({
  campaignId,
  active,
  mode,
  children,
}: {
  /** The campaign the workspace links point at (on Today: the most recent one, if any). */
  campaignId: string | null;
  active: WorkspaceKey | PlatformPage;
  mode?: DataMode;
  children: ReactNode;
}) {
  const [arriving] = useState(arrivingFromOutside);
  const [navOpen, setNavOpen] = useState(false);
  const [panelEl, setPanelEl] = useState<HTMLElement | null>(null);
  const [panelCount, setPanelCount] = useState(0);
  const [panelOpen, setPanelOpen] = useState(false);
  const docked = useMediaQuery("(min-width: 1280px)");
  const pageKey = useRemountOnFeatureNav();
  const pathname = usePathname();
  // The header carries the place's colour role as a thin light strip: ember on Today, the workspace's role inside one.
  const strip = inCampaign(active) ? roleColor(active, true) : active === "today" ? "var(--pop)" : "var(--role-proof-strong)";
  const register = useCallback(() => {
    setPanelCount((n) => n + 1);
    return () => setPanelCount((n) => n - 1);
  }, []);
  const slot = useMemo(() => ({ el: panelEl, register }), [panelEl, register]);
  const hasPanel = panelCount > 0;
  const drawerOpen = hasPanel && !docked && panelOpen;

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPanelOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  return (
    <EvidenceInspectorProvider>
      <PanelContext.Provider value={slot}>
        <div className={cn("min-h-dvh", arriving && "shell-arrive")}>
          <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm">
            Skip to content
          </a>
          <aside className="arrive-spine fixed top-3 bottom-3 left-3 z-30 hidden w-[232px] lg:block">
            <div className="clay-panel h-full border border-border/60">
              <Spine campaignId={campaignId} active={active} />
            </div>
          </aside>
          <Sheet open={navOpen} onOpenChange={setNavOpen}>
            <SheetContent side="left" className="w-[284px] gap-0 border-0 bg-surface p-0 data-[side=left]:w-[284px]">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <Spine campaignId={campaignId} active={active} onNavigate={() => setNavOpen(false)} />
            </SheetContent>
          </Sheet>

          <div className="lg:pl-[256px]">
            <header className="arrive-1 sticky top-3 z-20 mx-3 sm:mx-4 lg:mr-4 lg:ml-0">
              <div className="clay-panel relative flex h-14 items-center gap-2.5 border border-border/60 px-2.5 sm:px-3">
                <span
                  aria-hidden
                  className="pointer-events-none absolute inset-x-8 -bottom-px h-[2px] rounded-full opacity-80 transition-[background] duration-500"
                  style={{ background: `linear-gradient(90deg, transparent, ${strip} 30%, ${strip} 70%, transparent)` }}
                />
                <button
                  type="button"
                  onClick={() => setNavOpen(true)}
                  aria-label="Open navigation"
                  className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg text-ink-secondary hover:bg-surface-muted lg:hidden"
                >
                  <Menu aria-hidden className="size-5" />
                </button>
                <CampaignSelector campaignId={inCampaign(active) ? campaignId : null} workspace={inCampaign(active) ? active : null} />
                {mode && <ModeBadge mode={mode} />}
                <div className="ml-auto flex items-center gap-1.5">
                  {hasPanel && !docked && (
                    <button
                      type="button"
                      onClick={() => setPanelOpen((o) => !o)}
                      aria-expanded={panelOpen}
                      aria-controls="context-panel"
                      className="inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-ink-secondary hover:bg-surface-muted hover:text-ink"
                    >
                      {panelOpen ? <PanelRightClose aria-hidden className="size-4" /> : <PanelRightOpen aria-hidden className="size-4" />}
                      <span className="hidden sm:inline">Context</span>
                      <span className="sr-only sm:hidden">Context panel</span>
                    </button>
                  )}
                  <CommandBarButton />
                  <ThemeToggle className="max-sm:hidden" />
                  <AccountMenu />
                </div>
              </div>
            </header>

            <div className={cn("xl:grid xl:items-start", hasPanel && "xl:grid-cols-[minmax(0,1fr)_340px]")}>
              <main id="main" className="arrive-2 min-w-0 px-3 pt-6 pb-16 sm:px-4 lg:pr-4 lg:pl-1">
                {/* Each page enters over the persistent ground; tab and filter changes (query only) do not replay it. */}
                <div key={`${pathname}:${pageKey}`} className="page-enter">
                  {children}
                </div>
              </main>
              {drawerOpen && <div aria-hidden className="fixed inset-0 z-30 bg-black/45 xl:hidden" onClick={() => setPanelOpen(false)} />}
              <aside
                id="context-panel"
                aria-label="Context"
                inert={!docked && !drawerOpen}
                className={cn(
                  "arrive-2",
                  !hasPanel && "hidden",
                  docked
                    ? "clay-panel sticky top-[5.25rem] mt-6 mr-4 mb-6 max-h-[calc(100dvh-6.75rem)] overflow-y-auto border border-border/60 px-5 py-5"
                    : "fixed top-2 right-2 bottom-2 z-40 w-[min(360px,calc(100vw-1rem))] overflow-y-auto rounded-2xl border border-border/60 bg-surface px-5 py-5 shadow-float transition-transform duration-300 ease-out-expo",
                  !docked && !drawerOpen && "translate-x-[calc(100%+1rem)]",
                )}
              >
                <div ref={setPanelEl} />
              </aside>
            </div>
          </div>
        </div>
      </PanelContext.Provider>
    </EvidenceInspectorProvider>
  );
}
