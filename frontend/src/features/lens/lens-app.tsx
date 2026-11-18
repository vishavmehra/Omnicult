"use client";

import { CalendarDays, Columns3, Languages, LayoutGrid, UserRoundSearch } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { useAtlas } from "./api";
import { AtlasView } from "./atlas";
import { CalendarView } from "./calendar";
import { CompareView } from "./compare";
import { LanguageMapView } from "./language-map";
import { ProfileView, type LensView } from "./profile";

const VIEWS: { key: LensView; label: string; Icon: typeof LayoutGrid }[] = [
  { key: "atlas", label: "Atlas", Icon: LayoutGrid },
  { key: "profile", label: "State profile", Icon: UserRoundSearch },
  { key: "calendar", label: "Moment calendar", Icon: CalendarDays },
  { key: "compare", label: "Compare", Icon: Columns3 },
  { key: "language-map", label: "Language map", Icon: Languages },
];
const isView = (v: string | null): v is LensView => VIEWS.some((x) => x.key === v);

/**
 * The five Market Lens views over one selection. The view, the state and the compared states live in the URL
 * (`?view=profile&region=IN-TN`), so a view can be linked to, reloaded and opened from another workspace.
 */
export function LensApp({ campaignId }: { campaignId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const atlas = useAtlas(campaignId);

  const viewParam = params.get("view");
  const view: LensView = isView(viewParam) ? viewParam : "atlas";
  const region = params.get("region");
  const built = (atlas.data?.states ?? []).filter((s) => s.claims > 0).map((s) => s.code);
  const compareParam = params.get("compare");
  const compare = compareParam ? compareParam.split(",").filter(Boolean).slice(0, 4) : built.slice(0, 3);
  // Views other than the atlas open on something instead of an empty picker: the first state that has claims.
  const active = region ?? built[0] ?? null;

  const go = useCallback(
    (next: { view?: LensView; region?: string | null; compare?: string[] }) => {
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
    <Tabs value={view} onValueChange={(v) => go({ view: v as LensView })} className="gap-6">
      <TabsList variant="line" aria-label="Market Lens views" className="h-auto w-full flex-wrap justify-start gap-x-1 gap-y-1 border-b border-border pb-1.5">
        {VIEWS.map(({ key, label, Icon }) => (
          <TabsTrigger key={key} value={key} className="h-9 min-w-11 flex-none px-3 text-[14px]">
            <Icon aria-hidden />
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="atlas">
        <AtlasView campaignId={campaignId} selected={region} onSelect={(code) => go({ region: code })} onOpenProfile={(code) => go({ view: "profile", region: code })} />
      </TabsContent>
      <TabsContent value="profile">
        <ProfileView campaignId={campaignId} region={active} onRegion={(code) => go({ region: code })} onNavigate={(v) => go({ view: v })} />
      </TabsContent>
      <TabsContent value="calendar">
        <CalendarView campaignId={campaignId} region={active} onRegion={(code) => go({ region: code })} />
      </TabsContent>
      <TabsContent value="compare">
        <CompareView campaignId={campaignId} regions={compare} onRegions={(codes) => go({ compare: codes })} />
      </TabsContent>
      <TabsContent value="language-map">
        <LanguageMapView campaignId={campaignId} region={active} onRegion={(code) => go({ region: code })} />
      </TabsContent>
    </Tabs>
  );
}
