"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

import type { GlossaryTermCreate, GlossaryTermUpdate, Tone } from "./types";

/** Every Studio query hangs under ["studio", campaignId], so one invalidation refreshes the whole screen after a change. */
export const studioKeys = {
  all: (campaignId: string) => ["studio", campaignId] as const,
  versions: (campaignId: string) => ["studio", campaignId, "versions"] as const,
  version: (campaignId: string, id: string | null) => ["studio", campaignId, "version", id] as const,
  operations: (campaignId: string) => ["studio", campaignId, "operations"] as const,
  locks: (campaignId: string) => ["studio", campaignId, "locks"] as const,
  chips: (campaignId: string, versionId: string | null, elementId: string) => ["studio", campaignId, "chips", versionId, elementId] as const,
  diff: (campaignId: string, from: string | null, to: string | null) => ["studio", campaignId, "diff", from, to] as const,
  glossary: (campaignId: string) => ["studio", campaignId, "glossary"] as const,
  claim: (workspaceId: string | null, claimId: string) => ["claim", workspaceId, claimId] as const,
  regions: ["regions", "IN"] as const,
};

const PAGE = 100;
const MAX_PAGES = 5;

/** Reads every page up to a bound (500 records). `total` says whether the bound cut the list. */
async function allPages<T>(page: (offset: number) => Promise<{ items: T[]; total: number }>) {
  const items: T[] = [];
  let total = 0;
  for (let i = 0; i < MAX_PAGES; i += 1) {
    const next = await page(i * PAGE);
    items.push(...next.items);
    total = next.total;
    if (items.length >= total || next.items.length === 0) break;
  }
  return { items, total };
}

// ---------- reads ----------

export function useVersions(campaignId: string) {
  return useQuery({
    queryKey: studioKeys.versions(campaignId),
    queryFn: () =>
      allPages((offset) =>
        unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions", { params: { path: { campaign_id: campaignId }, query: { limit: PAGE, offset } } })),
      ),
  });
}

export function useVersion(campaignId: string, versionId: string | null) {
  return useQuery({
    queryKey: studioKeys.version(campaignId, versionId),
    enabled: Boolean(versionId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions/{version_id}", { params: { path: { campaign_id: campaignId, version_id: versionId! } } })),
  });
}

/** Every operation, newest first, refused ones included. */
export function useOperations(campaignId: string) {
  return useQuery({
    queryKey: studioKeys.operations(campaignId),
    queryFn: () =>
      allPages((offset) =>
        unwrap(api.GET("/api/v1/campaigns/{campaign_id}/operations", { params: { path: { campaign_id: campaignId }, query: { limit: PAGE, offset } } })),
      ),
  });
}

export function useLocks(campaignId: string) {
  return useQuery({
    queryKey: studioKeys.locks(campaignId),
    queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/locks", { params: { path: { campaign_id: campaignId }, query: { limit: PAGE } } })),
  });
}

export function useChips(campaignId: string, versionId: string | null, elementId: string, enabled: boolean) {
  return useQuery({
    queryKey: studioKeys.chips(campaignId, versionId, elementId),
    enabled: enabled && Boolean(versionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/chips", {
          params: { path: { campaign_id: campaignId }, query: { limit: PAGE, version_id: versionId, element_id: elementId } },
        }),
      ),
  });
}

export function useDiff(campaignId: string, from: string | null, to: string | null) {
  return useQuery({
    queryKey: studioKeys.diff(campaignId, from, to),
    enabled: Boolean(from && to),
    queryFn: () =>
      unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions/{from_id}/diff/{to_id}", { params: { path: { campaign_id: campaignId, from_id: from!, to_id: to! } } })),
  });
}

export function useGlossary(campaignId: string) {
  return useQuery({
    queryKey: studioKeys.glossary(campaignId),
    queryFn: () =>
      allPages((offset) =>
        unwrap(api.GET("/api/v1/campaigns/{campaign_id}/glossary", { params: { path: { campaign_id: campaignId }, query: { limit: PAGE, offset } } })),
      ),
  });
}

/** India's regions with their languages (the reference lists from the culture pack). */
export function useRegions() {
  return useQuery({
    queryKey: studioKeys.regions,
    staleTime: 10 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/regions", { params: { query: { country_code: "IN", limit: PAGE } } })),
  });
}

/** One claim with its five tags, for the evidence rows under a chip or a transcreated line. */
export function useClaim(workspaceId: string | null, claimId: string, enabled = true) {
  return useQuery({
    queryKey: studioKeys.claim(workspaceId, claimId),
    enabled: enabled && Boolean(workspaceId),
    staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/claims/{claim_id}", { params: { path: { workspace_id: workspaceId!, claim_id: claimId } } })),
  });
}

// ---------- writes ----------

/** Each write refreshes the whole Studio tree of queries, because a new version changes the tree, the locks' effect and the history. */
function useStudioMutation<V, R>(campaignId: string, fn: (vars: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => client.invalidateQueries({ queryKey: studioKeys.all(campaignId) }),
    // A refusal usually means a lock changed under us: re-read the locks so the screen shows the real state.
    onError: () => client.invalidateQueries({ queryKey: studioKeys.locks(campaignId) }),
  });
}

const path = (campaignId: string) => ({ params: { path: { campaign_id: campaignId } } });

export function useCreateVersion(campaignId: string) {
  return useStudioMutation(campaignId, (vars: { label: string; language: string }) =>
    unwrap(api.POST("/api/v1/campaigns/{campaign_id}/versions", { ...path(campaignId), body: vars })),
  );
}

export function useEditElement(campaignId: string) {
  return useStudioMutation(campaignId, (vars: { versionId: string; elementId: string; value: string; reason: string }) =>
    unwrap(
      api.POST("/api/v1/campaigns/{campaign_id}/operations", {
        ...path(campaignId),
        body: {
          version_id: vars.versionId,
          reason: vars.reason,
          claim_ids: [],
          operation: { kind: "manual_edit", edits: [{ element_id: vars.elementId, set: { value: vars.value } }] },
        },
      }),
    ),
  );
}

export function useRestoreVersion(campaignId: string) {
  return useStudioMutation(campaignId, (vars: { versionId: string }) =>
    unwrap(api.POST("/api/v1/campaigns/{campaign_id}/versions/{version_id}/restore", { params: { path: { campaign_id: campaignId, version_id: vars.versionId } }, body: { reason: "Restored an earlier version." } })),
  );
}

export function useSetLock(campaignId: string) {
  return useStudioMutation(campaignId, (vars: { elementId: string; locked: boolean }) =>
    vars.locked
      ? unwrap(api.PUT("/api/v1/campaigns/{campaign_id}/locks/{element_id}", { params: { path: { campaign_id: campaignId, element_id: vars.elementId } }, body: {} }))
      : unwrap(api.DELETE("/api/v1/campaigns/{campaign_id}/locks/{element_id}", { params: { path: { campaign_id: campaignId, element_id: vars.elementId } } })),
  );
}

export function useGenerateChips(campaignId: string) {
  return useStudioMutation(campaignId, (vars: { versionId: string; elementId: string; regionCode: string }) =>
    unwrap(
      api.POST("/api/v1/campaigns/{campaign_id}/chips/generate", {
        ...path(campaignId),
        body: { version_id: vars.versionId, element_id: vars.elementId, region_code: vars.regionCode, max_chips: 4 },
      }),
    ),
  );
}

export function useApplyChip(campaignId: string) {
  return useStudioMutation(campaignId, (vars: { chipId: string; versionId: string }) =>
    unwrap(api.POST("/api/v1/campaigns/{campaign_id}/chips/{chip_id}/apply", { params: { path: { campaign_id: campaignId, chip_id: vars.chipId } }, body: { version_id: vars.versionId } })),
  );
}

export type TranscreateVars = { versionId: string; regionCode: string; language: string; elementIds: string[] | null; tone: Tone };

export function useStartTranscreate(campaignId: string) {
  return useStudioMutation(campaignId, (vars: TranscreateVars) =>
    unwrap(
      api.POST("/api/v1/campaigns/{campaign_id}/transcreate", {
        ...path(campaignId),
        // One key per click: a double click or a retried request cannot start two paid runs.
        headers: { "Idempotency-Key": globalThis.crypto?.randomUUID?.() ?? `studio-${Date.now()}-${Math.random().toString(36).slice(2)}` },
        body: { version_id: vars.versionId, region_code: vars.regionCode, language: vars.language, element_ids: vars.elementIds, tone: vars.tone },
      }),
    ),
  );
}

export function useCreateTerm(campaignId: string) {
  return useStudioMutation(campaignId, (body: GlossaryTermCreate) => unwrap(api.POST("/api/v1/campaigns/{campaign_id}/glossary", { ...path(campaignId), body })));
}

export function useUpdateTerm(campaignId: string) {
  return useStudioMutation(campaignId, (vars: { id: string; body: GlossaryTermUpdate }) =>
    unwrap(api.PATCH("/api/v1/campaigns/{campaign_id}/glossary/{term_id}", { params: { path: { campaign_id: campaignId, term_id: vars.id } }, body: vars.body })),
  );
}

export function useDeleteTerm(campaignId: string) {
  return useStudioMutation(campaignId, (vars: { id: string }) =>
    unwrap(api.DELETE("/api/v1/campaigns/{campaign_id}/glossary/{term_id}", { params: { path: { campaign_id: campaignId, term_id: vars.id } } })),
  );
}
