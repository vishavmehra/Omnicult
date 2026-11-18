"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { draftKey, emptyDraft, loadDrafts, saveDrafts, type Draft } from "./observations";

type Store = {
  /** The observation inputs for one version in one region (an empty draft when nothing was entered). */
  get(versionId: string, regionCode: string): Draft;
  update(versionId: string, regionCode: string, change: (d: Draft) => Draft): void;
  clear(versionId: string, regionCode: string): void;
};

const Ctx = createContext<Store | null>(null);

/**
 * Holds the observation drafts for this campaign, shared by Compare and Score and the Readiness Board so an input is typed once.
 * Remembered in this browser only; mounted after the campaign has loaded on the client, so reading storage here is safe.
 */
export function InputsProvider({ campaignId, children }: { campaignId: string; children: ReactNode }) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() => loadDrafts(campaignId));

  const update = useCallback(
    (versionId: string, regionCode: string, change: (d: Draft) => Draft) => {
      setDrafts((prev) => {
        const key = draftKey(versionId, regionCode);
        const next = { ...prev, [key]: change(prev[key] ?? emptyDraft()) };
        saveDrafts(campaignId, next);
        return next;
      });
    },
    [campaignId],
  );
  const clear = useCallback(
    (versionId: string, regionCode: string) => {
      setDrafts((prev) => {
        const rest = { ...prev };
        delete rest[draftKey(versionId, regionCode)];
        saveDrafts(campaignId, rest);
        return rest;
      });
    },
    [campaignId],
  );

  const store = useMemo<Store>(
    () => ({ get: (v, r) => drafts[draftKey(v, r)] ?? emptyDraft(), update, clear }),
    [drafts, update, clear],
  );
  return <Ctx.Provider value={store}>{children}</Ctx.Provider>;
}

export function useInputs(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useInputs must be used inside the Launch Room.");
  return ctx;
}
