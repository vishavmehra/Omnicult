"use client";

import { Check, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type ReactNode } from "react";

import { WorkspaceShell } from "@/components/shell/workspace-shell";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCampaignDirectory } from "@/features/desk/use-campaign-directory";
import { cn } from "@/lib/utils";

import { roleLabel, useCreateWorkspace, useMe, type WorkspaceDetail } from "./api";

export const SELECT_CLASS =
  "h-8 min-w-0 rounded-lg border border-input bg-surface-raised px-2 text-[13.5px] text-ink shadow-well outline-none focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50 dark:bg-surface-muted";

/** The shell for every settings page: Settings sits outside any campaign, so the spine links to the most recent one. */
export function SettingsLayout({ children }: { children: ReactNode }) {
  const dir = useCampaignDirectory();
  return (
    <WorkspaceShell campaignId={dir.campaigns[0]?.id ?? null} active="settings">
      {children}
    </WorkspaceShell>
  );
}

const TABS = [
  { href: "/app/settings", label: "Team and roles" },
  { href: "/app/settings/workspace", label: "Workspace and usage" },
  { href: "/app/settings/country-packs/in", label: "Country pack: India", noWorkspace: true },
];

/** The workspace the settings pages act on, chosen with ?w= (default: the first workspace the account belongs to). */
export function useSettingsWorkspace() {
  const me = useMe();
  const params = useSearchParams();
  const wanted = params.get("w");
  const workspaces = me.data?.workspaces ?? [];
  const selected = workspaces.find((w) => w.id === wanted) ?? workspaces[0] ?? null;
  return { me, workspaces, selected };
}

function NewWorkspace({ onCreated, onCancel }: { onCreated: (w: WorkspaceDetail) => void; onCancel: () => void }) {
  const create = useCreateWorkspace();
  const [name, setName] = useState("");
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) create.mutate(name.trim(), { onSuccess: onCreated });
      }}
    >
      <label className="sr-only" htmlFor="new-workspace-name">
        Team workspace name
      </label>
      <Input id="new-workspace-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Team workspace name" maxLength={80} className="w-56" />
      <Button type="submit" disabled={!name.trim() || create.isPending}>
        Create workspace
      </Button>
      <Button type="button" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
      {create.error && <ErrorState error={create.error} className="basis-full" />}
    </form>
  );
}

/** Title, workspace picker and the three settings sections. `needsWorkspace` pages wait for the account's workspaces. */
export function SettingsFrame({ children, needsWorkspace = true }: { children: (workspace: { id: string; name: string; role: string; kind: string }) => ReactNode; needsWorkspace?: boolean }) {
  const pathname = usePathname();
  const router = useRouter();
  const { me, workspaces, selected } = useSettingsWorkspace();
  const [creating, setCreating] = useState(false);
  const withW = (href: string, noWorkspace?: boolean) => (selected && !noWorkspace ? `${href}?w=${selected.id}` : href);

  return (
    <>
      <header className="mb-5 space-y-1.5 border-b border-border pb-5">
        <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Settings</h1>
        <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">Who can work in a workspace and what they can do, how the workspace is set up, and the reference pack behind the regions.</p>
      </header>

      <nav aria-label="Settings sections" className="mb-5 flex flex-wrap gap-1.5">
        {TABS.map((t) => {
          const on = t.href === "/app/settings" ? pathname === t.href : pathname.startsWith(t.href);
          return (
            <Link
              key={t.href}
              href={withW(t.href, t.noWorkspace)}
              aria-current={on ? "page" : undefined}
              className={cn("flex h-10 items-center rounded-lg border px-3 text-[14px]", on ? "clay border-border font-medium text-ink" : "border-transparent text-ink-secondary hover:bg-surface-muted hover:text-ink")}
            >
              {t.label}
            </Link>
          );
        })}
      </nav>

      {needsWorkspace && (
        <div className="mb-6 flex flex-wrap items-end gap-x-4 gap-y-2">
          <div className="space-y-1">
            <label htmlFor="workspace-picker" className="type-meta block">
              Workspace
            </label>
            <select
              id="workspace-picker"
              className={cn(SELECT_CLASS, "h-10 w-[min(22rem,calc(100vw-2rem))]")}
              value={selected?.id ?? ""}
              disabled={!workspaces.length}
              onChange={(e) => router.replace(`${pathname}?w=${e.target.value}`, { scroll: false })}
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name} ({w.kind === "personal" ? "personal" : "team"}, {roleLabel(w.role)})
                </option>
              ))}
            </select>
          </div>
          {!me.data?.is_anonymous &&
            (creating ? (
              <NewWorkspace
                onCancel={() => setCreating(false)}
                onCreated={(w) => {
                  setCreating(false);
                  router.replace(`${pathname}?w=${w.id}`, { scroll: false });
                }}
              />
            ) : (
              <Button variant="outline" size="lg" onClick={() => setCreating(true)}>
                <Plus aria-hidden />
                New team workspace
              </Button>
            ))}
        </div>
      )}

      {needsWorkspace ? (
        me.error ? (
          <ErrorState error={me.error} onRetry={() => void me.refetch()} />
        ) : !selected ? (
          <LoadingState label="Loading your workspaces…" />
        ) : (
          children(selected)
        )
      ) : (
        children({ id: "", name: "", role: "", kind: "" })
      )}
    </>
  );
}

export function Saved({ show, children = "Saved" }: { show: boolean; children?: ReactNode }) {
  return (
    <span role="status" className={cn("inline-flex items-center gap-1 text-[13px] text-success", !show && "sr-only")}>
      {show && <Check aria-hidden className="size-3.5" />}
      {show ? children : ""}
    </span>
  );
}
