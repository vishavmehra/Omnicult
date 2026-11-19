"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { CategoryShelfView } from "@/features/lens-t3/category-shelf";
import { TrendRadarView } from "@/features/lens-t3/trend-radar";

import { useAtlas, useAutoBuild } from "./api";
import { AtlasView } from "./atlas";
import { CalendarView } from "./calendar";
import { CompareView } from "./compare";
import { LanguageMapView } from "./language-map";
import { ProfileView, type LensView } from "./profile";
import { AutoBuildStrip } from "./state-data";

type AppView = LensView | "trends" | "shelf";

/** Every view a `?view=` value opens. The workspace header's chips link to these; the atlas is the default. */
const VIEWS: readonly AppView[] = ["atlas", "profile", "language-map", "calendar", "compare", "trends", "shelf"];
const isView = (v: string | null): v is AppView => VIEWS.includes(v as AppView);

/**
 * The Market Lens views over one selection. The view, the state and the compared states live in the URL
 * (`?view=profile&region=IN-TN`), so a view can be linked to, reloaded and opened from another workspace. The views are
 * switched from the workspace header's navigation row, not from a tab list here.
 */
export function LensApp({ campaignId }: { campaignId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const atlas = useAtlas(campaignId);
  const autoBuild = useAutoBuild(campaignId);

  const viewParam = params.get("view");
  const view: AppView = isView(viewParam) ? viewParam : "atlas";
  const region = params.get("region");
  const states = atlas.data?.states ?? [];
  // The campaign's own states lead (origin first), then the states that have claims.
  const campaign = [...states.filter((s) => s.campaign_role === "origin"), ...states.filter((s) => s.campaign_role === "target")].map((s) => s.code);
  const built = states.filter((s) => s.claims > 0).map((s) => s.code);
  const compareParam = params.get("compare");
  const fallback = campaign.length >= 2 ? campaign : [...new Set([...campaign, ...built])];
  const compare = compareParam ? compareParam.split(",").filter(Boolean).slice(0, 4) : fallback.slice(0, 4);
  // Views other than the atlas open on something instead of an empty picker: the campaign's origin, else a state with claims.
  const active = region ?? campaign[0] ?? built[0] ?? null;

  const go = useCallback(
    (next: { view?: AppView; region?: string | null; compare?: string[] }) => {
      const q = new URLSearchParams(params.toString());
      if (next.view) q.set("view", next.view);
      if (next.region !== undefined) {
        if (next.region) q.set("region", next.region);
        else q.delete("region");
      }
      if (next.compare) {
        if (next.compare.length) q.set("compare", next.compare.join(","));
        else q.delete("compare");
      }
      router.replace(`${pathname}?${q.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );

  return (
    <div className="space-y-6">
      <AutoBuildStrip status={autoBuild} />
      {view === "atlas" && (
        <AtlasView campaignId={campaignId} selected={region} onSelect={(code) => go({ region: code })} onOpenProfile={(code) => go({ view: "profile", region: code })} />
      )}
      {view === "profile" && <ProfileView campaignId={campaignId} region={active} onRegion={(code) => go({ region: code })} onNavigate={(v) => go({ view: v })} />}
      {view === "calendar" && <CalendarView campaignId={campaignId} region={active} onRegion={(code) => go({ region: code })} />}
      {view === "compare" && <CompareView campaignId={campaignId} regions={compare} onRegions={(codes) => go({ compare: codes })} />}
      {view === "language-map" && <LanguageMapView campaignId={campaignId} region={active} onRegion={(code) => go({ region: code })} />}
      {view === "trends" && <TrendRadarView campaignId={campaignId} />}
      {view === "shelf" && <CategoryShelfView campaignId={campaignId} />}
    </div>
  );
}
