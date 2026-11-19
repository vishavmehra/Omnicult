"use client";

import { LayoutTemplate } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useCreatives } from "@/features/xray/api";

import { useCreateVersion } from "./api";
import { MutationError } from "./parts";

/** Creatives of the campaign with a usable X-Ray result: the layout the original version can be built from. */
export function useXRayLayoutReady(campaignId: string) {
  const creatives = useCreatives(campaignId);
  const ready = (creatives.data ?? []).filter((c) => c.current_run_id && c.scene_count > 0);
  return { ready, loading: creatives.isPending };
}

/**
 * "Use the X-Ray layout": a new original version whose elements are what Creative X-Ray found in the campaign's creatives, each
 * with the position the vision model located and the scene it sits in. Remake, Risk Check and Format Fit need those positions.
 */
export function UseXRayLayoutButton({
  campaignId,
  onCreated,
  size = "lg",
  variant = "default",
}: {
  campaignId: string;
  onCreated(versionId: string): void;
  size?: "lg" | "default" | "sm";
  variant?: "default" | "outline";
}) {
  const create = useCreateVersion(campaignId);
  const { ready } = useXRayLayoutReady(campaignId);
  const names = ready.map((c) => c.label).join(", ");
  return (
    <div className="space-y-2">
      <Button
        size={size}
        variant={variant}
        disabled={!ready.length || create.isPending}
        title={ready.length ? `Build the original from the X-Ray of ${names}.` : "Run Creative X-Ray on a creative first."}
        onClick={() =>
          create.mutate(
            { label: "Original · X-Ray layout", from_xray: true },
            { onSuccess: (node) => { toast.success(`Original made from the X-Ray layout: ${node.elements.length} elements`); onCreated(node.id); } },
          )
        }
      >
        <LayoutTemplate aria-hidden />
        {create.isPending ? "Building…" : "Use the X-Ray layout"}
      </Button>
      {create.isError && <MutationError error={create.error} />}
    </div>
  );
}
