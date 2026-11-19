"use client";

import { Check, ChevronsUpDown, LayoutList, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useCampaignDirectory } from "@/features/desk/use-campaign-directory";
import { cn } from "@/lib/utils";

import { workspaceHref, type WorkspaceKey } from "./workspaces";

/**
 * Header campaign selector. Switching keeps you in the same workspace for the new campaign, so the place you were working
 * survives the switch; unsaved edits are guarded by the editors themselves.
 */
export function CampaignSelector({ campaignId, workspace }: { campaignId: string | null; workspace: WorkspaceKey | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const { campaigns, brands, pending } = useCampaignDirectory();
  const current = campaigns.find((c) => c.id === campaignId) ?? null;

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={current ? `Campaign: ${current.name}, ${current.brand.name}. Switch campaign` : "Choose a campaign"}
        className="clay group flex h-10 max-w-[min(26rem,62vw)] min-w-0 items-center gap-2.5 rounded-lg border border-border px-2.5 text-left"
      >
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-[13.5px] font-semibold text-ink">{current ? current.name : pending ? "Loading campaigns…" : "Choose a campaign"}</span>
          <span className="block truncate text-[11.5px] text-ink-muted">{current ? current.brand.name : `${campaigns.length} ${campaigns.length === 1 ? "campaign" : "campaigns"} across ${brands.length} ${brands.length === 1 ? "brand" : "brands"}`}</span>
        </span>
        <ChevronsUpDown aria-hidden className="size-4 shrink-0 text-ink-muted group-hover:text-ink" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(24rem,calc(100vw-2rem))] p-0">
        <Command>
          <CommandInput placeholder="Find a campaign or brand" />
          <CommandList className="max-h-80">
            <CommandEmpty>{pending ? "Loading campaigns…" : "No campaign matches."}</CommandEmpty>
            {brands.map((brand) => {
              const items = campaigns.filter((c) => c.brand.id === brand.id);
              if (!items.length) return null;
              return (
                <CommandGroup key={brand.id} heading={brand.name}>
                  {items.map((c) => (
                    <CommandItem key={c.id} value={`${c.name} ${brand.name} ${c.id}`} onSelect={() => go(workspaceHref(c.id, workspace ?? "desk"))}>
                      <span className="min-w-0 flex-1 truncate">{c.name}</span>
                      <Check aria-hidden className={cn("size-4", c.id === campaignId ? "opacity-100" : "opacity-0")} />
                    </CommandItem>
                  ))}
                </CommandGroup>
              );
            })}
            <CommandSeparator />
            <CommandGroup>
              <CommandItem value="today all campaigns" onSelect={() => go("/app")}>
                <LayoutList aria-hidden />
                Today, all campaigns
              </CommandItem>
              <CommandItem value="new campaign create" onSelect={() => go("/app?new=campaign")}>
                <Plus aria-hidden />
                New campaign
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
