"use client";

import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { CampaignForm } from "@/features/project/campaign-form";
import { ProjectForm } from "@/features/project/project-form";
import type { ProjectSummary } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const NEW_BRAND = "__new_brand__";

/**
 * Create a campaign: pick its brand (API project) or create a brand first, then fill the brief. On success the new campaign
 * opens in its Campaign Desk. Both steps use the existing project and campaign endpoints.
 */
export function NewCampaign({ brands, onClose }: { brands: ProjectSummary[]; onClose(): void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const live = brands.filter((b) => b.status === "active");
  const [brandId, setBrandId] = useState<string>(live.find((b) => b.mode === "live")?.id ?? live[0]?.id ?? NEW_BRAND);
  const brand = live.find((b) => b.id === brandId) ?? null;

  return (
    <section aria-labelledby="new-campaign" className="rounded-card border border-border bg-surface">
      <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
        <h2 id="new-campaign" className="type-title text-[22px] text-ink">
          New campaign
        </h2>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close without creating">
          <X aria-hidden />
        </Button>
      </header>
      <div className="space-y-6 px-5 py-5">
        <fieldset className="space-y-2">
          <legend className="text-[13px] font-medium text-ink">Brand</legend>
          <div className="flex flex-wrap gap-2">
            {live.map((b) => (
              <label
                key={b.id}
                className={cn(
                  "inline-flex h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 text-[13.5px] has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
                  b.id === brandId ? "clay border-border font-medium text-ink" : "border-border text-ink-secondary hover:bg-surface-muted",
                )}
              >
                <input type="radio" name="brand" value={b.id} checked={b.id === brandId} onChange={() => setBrandId(b.id)} className="sr-only" />
                {b.name}
                {b.mode === "demo" && <span className="text-[11.5px] text-warning">demo</span>}
              </label>
            ))}
            <label
              className={cn(
                "inline-flex h-10 cursor-pointer items-center gap-2 rounded-lg border border-dashed px-3 text-[13.5px] has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
                brandId === NEW_BRAND ? "border-rose font-medium text-ink" : "border-border-strong/60 text-ink-secondary hover:bg-surface-muted",
              )}
            >
              <input type="radio" name="brand" value={NEW_BRAND} checked={brandId === NEW_BRAND} onChange={() => setBrandId(NEW_BRAND)} className="sr-only" />
              New brand
            </label>
          </div>
          {brand?.mode === "demo" && (
            <p className="text-[12.5px] text-warning">Demo brands run on labelled fixtures only. Create a new brand to work with your own copy and live sources.</p>
          )}
        </fieldset>

        {brandId === NEW_BRAND ? (
          <div className="space-y-2">
            <p className="text-[13px] text-ink-secondary">First the brand and its Brand Kit; the campaign brief comes next.</p>
            <ProjectForm onCancel={onClose} onCreated={(p) => setBrandId(p.id)} />
          </div>
        ) : brand ? (
          <CampaignForm
            key={brand.id}
            projectId={brand.id}
            demo={brand.mode === "demo"}
            onCancel={onClose}
            onDone={(campaign) => {
              void queryClient.invalidateQueries({ queryKey: ["directory"] });
              router.push(`/app/c/${campaign.id}/desk`);
            }}
          />
        ) : (
          <LoadingState label="Adding the new brand…" />
        )}
      </div>
    </section>
  );
}
