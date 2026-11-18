import type { RunType } from "@/lib/api/types";

/**
 * Run type → display label, and the Omnicult page that shows its result (null when the type has no page of its own).
 * Run types from earlier versions of the product stay listed so that stored runs still read well in history.
 */
export const RUN_TYPE_META: Record<RunType, { label: string; page: string | null }> = {
  market_discovery: { label: "Market discovery", page: null },
  campaign_rehearsal: { label: "Campaign rehearsal", page: null },
  campaign_adaptation: { label: "Campaign adaptation", page: null },
  campaign_evaluation: { label: "Campaign evaluation", page: null },
  cultural_profile: { label: "Cultural profile", page: null },
  market_comparison: { label: "Market comparison", page: null },
  campaign_arena: { label: "Campaign arena", page: null },
  risk_scan: { label: "Risk scan", page: null },
  population_study: { label: "Population study", page: null },
  social_simulation: { label: "Social simulation", page: null },
  transcreate: { label: "Transcreation", page: "studio" },
  creative_xray: { label: "Creative X-Ray", page: "studio/xray" },
  voice_direct: { label: "Voice Director", page: "studio" },
  remake_visual: { label: "Remake: Visuals", page: "studio/remake" },
  remake_sound: { label: "Remake: Sound", page: "studio/remake" },
};

/** The workspace page that shows a run's result, or null when the run belongs to no current page or to no campaign. */
export function runHref(run: { run_type: RunType; campaign_id?: string | null }): string | null {
  const page = RUN_TYPE_META[run.run_type].page;
  return page && run.campaign_id ? `/app/c/${run.campaign_id}/${page}` : null;
}
