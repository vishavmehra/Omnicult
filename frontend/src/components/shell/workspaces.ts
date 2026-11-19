import { Activity, Clapperboard, NotebookPen, ScanSearch, Stamp, UsersRound, Vault, type LucideIcon } from "lucide-react";

export type WorkspaceKey = "desk" | "lens" | "studio" | "lab" | "launch" | "pulse" | "proof";

/** Scope tiers from docs/SCOPE_PLAN.md. Tiers 1 and 2 are the product; tier 3 is roadmap and is always labelled as such. */
export type Tier = 1 | 2 | 3;

/** Whether a feature can be opened today. Only `built` features are links; the others are shown so nothing is hidden. */
export type FeatureStatus = "built" | "in_progress" | "roadmap";

/** Features that do something instead of going somewhere. */
export type FeatureAction = "command-bar" | "demo";

export type Feature = {
  id: number;
  name: string;
  tier: Tier;
  status: FeatureStatus;
  /** Deep link for a campaign, using the URL parameter its workspace already reads. A tab that is the workspace default links to the bare workspace. */
  href?: (campaignId: string) => string;
  action?: FeatureAction;
  note: string;
};

export type Stage = { key: string; label: string; summary: string; workspaces: WorkspaceKey[] };

/** A tab or view of a workspace page that no catalogue feature names (Original creative, Compare versions). It still gets its own chip. */
export type ExtraView = { name: string; href: (campaignId: string) => string; note: string; after: number };

export type Workspace = {
  key: WorkspaceKey;
  /** Position on the workflow line; carries information (the order work moves in), so it is shown. */
  number: number;
  label: string;
  Icon: LucideIcon;
  purpose: string;
  features: Feature[];
  /** Views with no feature of their own; each chip is placed after the chip of feature `after`. */
  extraViews?: ExtraView[];
  /** Query values that belong to the open page, not to one tab, and survive a jump to another tab (the selected state, the open report). */
  keepParams?: string[];
};

/** The workflow stages, in order. Navigation and the landing page group workspaces under these headings (SCOPE_PLAN rules). */
export const STAGES: Stage[] = [
  { key: "plan", label: "Plan and understand", summary: "Write the brief once, then learn the place before touching the creative.", workspaces: ["desk", "lens"] },
  { key: "create", label: "Create", summary: "Keep the original in view while every regional change is proposed, explained and versioned.", workspaces: ["studio"] },
  { key: "test", label: "Test", summary: "Rehearse with an audience panel before spending on media.", workspaces: ["lab"] },
  { key: "decide", label: "Decide and ship", summary: "Fixed, visible rules turn scores into Go, Fix or Rethink.", workspaces: ["launch"] },
  { key: "track", label: "Track", summary: "What really happened, region by region, with its freshness stated.", workspaces: ["pulse"] },
  { key: "prove", label: "Prove", summary: "Answer “why did we make this decision?” from the record.", workspaces: ["proof"] },
];

// Deep-link builders. `at` appends the query the workspace reads (desk and studio and lab `?tab=`, lens and proof `?view=`).
const at = (key: WorkspaceKey, query = "") => (campaignId: string) => `${workspaceHref(campaignId, key)}${query}`;
const TODAY = () => "/app";
const XRAY = (campaignId: string) => `${workspaceHref(campaignId, "studio")}/xray`;
const REMAKE = (view?: "sound" | "video") => (campaignId: string) => `${workspaceHref(campaignId, "studio")}/remake${view ? `?view=${view}` : ""}`;
const GENERATE = (campaignId: string) => `${workspaceHref(campaignId, "studio")}/generate`;
const SETTINGS = () => "/app/settings";
const USAGE = () => "/app/usage";

export const WORKSPACES: Record<WorkspaceKey, Workspace> = {
  desk: {
    key: "desk",
    number: 1,
    label: "Campaign Desk",
    Icon: NotebookPen,
    purpose: "The campaign brief and Brand Kit every other workspace reads from.",
    extraViews: [{ name: "Original creative", href: at("desk", "?tab=creative"), note: "The original copy and the scoring weights.", after: 3 }],
    features: [
      { id: 1, name: "Today View", tier: 1, status: "built", href: TODAY, note: "What is running, what finished, what failed and which campaigns need attention, across every brand." },
      { id: 2, name: "Campaign Brief", tier: 1, status: "built", href: at("desk"), note: "Product, objective, regions, languages, channels, budget, dates and success metric, entered once and read everywhere." },
      { id: 3, name: "Brand Kit", tier: 1, status: "built", href: at("desk", "?tab=brand-kit"), note: "Tone, protected terms and the elements that must never change." },
      { id: 4, name: "Brand Glossary", tier: 2, status: "built", href: at("studio", "?tab=glossary"), note: "Brand spellings by script, preferred translations, pronunciation and do-not-translate terms." },
      { id: 5, name: "Command Bar", tier: 2, status: "built", action: "command-bar", note: "Type what you want done; it runs the same tools the workspaces use." },
      { id: 6, name: "Demo Mode", tier: 1, status: "built", action: "demo", note: "A complete example campaign, kept apart from your own records." },
    ],
  },
  lens: {
    key: "lens",
    number: 2,
    label: "Market Lens",
    Icon: ScanSearch,
    purpose: "Regional cultural intelligence where every fact is traceable to its source.",
    keepParams: ["region", "compare"],
    features: [
      { id: 7, name: "Culture Atlas", tier: 1, status: "built", href: at("lens"), note: "Cultural signals for a region, each traceable to the source it came from." },
      { id: 8, name: "State Profile", tier: 1, status: "built", href: at("lens", "?view=profile"), note: "Languages, scripts, festivals, food, colours, symbols, humour, customs and sensitivities for an Indian state, every fact tagged." },
      { id: 9, name: "Language Map", tier: 2, status: "built", href: at("lens", "?view=language-map"), note: "Language and script mix, state by state." },
      { id: 10, name: "Moment Calendar", tier: 2, status: "built", href: at("lens", "?view=calendar"), note: "Festivals and moments that matter for timing." },
      { id: 11, name: "Market Compare", tier: 1, status: "built", href: at("lens", "?view=compare"), note: "States side by side on the same evidence." },
      { id: 12, name: "Trend Radar", tier: 3, status: "built", href: at("lens", "?view=trends"), note: "Rising and falling public attention by state, from Wikipedia pageviews." },
      { id: 13, name: "Share of Search", tier: 3, status: "roadmap", note: "Search interest against competitors." },
      { id: 14, name: "Category Shelf", tier: 3, status: "built", href: at("lens", "?view=shelf"), note: "Brands and products in the category, by state, with public signals." },
      { id: 15, name: "Evidence Meter", tier: 1, status: "built", href: at("lens", "?view=profile"), note: "How much of a profile is observed, calculated, interpreted or unverified, and from how many independent sources." },
    ],
  },
  studio: {
    key: "studio",
    number: 3,
    label: "Creative Studio",
    Icon: Clapperboard,
    purpose: "Inspect the original creative, adapt it per region, and compare every version with the original.",
    extraViews: [{ name: "Compare versions", href: at("studio", "?tab=compare"), note: "Any two versions side by side, with every difference marked.", after: 19 }],
    features: [
      { id: 16, name: "Creative X-Ray", tier: 1, status: "built", href: XRAY, note: "The creative decomposed into scenes, keyframes, text, transcript, claims and visual observations." },
      { id: 17, name: "Transcreate", tier: 1, status: "built", href: at("studio", "?tab=transcreate"), note: "Regional copy with an English back-translation beside every line." },
      { id: 18, name: "Tone Dials", tier: 2, status: "built", href: at("studio", "?tab=transcreate"), note: "Formality, warmth and humour per region, inside the brand voice." },
      { id: 19, name: "Tweak Chips", tier: 1, status: "built", href: at("studio", "?tab=elements"), note: "Small suggested changes, each with its reason, evidence and cost, inspected before you apply them." },
      { id: 20, name: "Lock and Edit", tier: 1, status: "built", href: at("studio", "?tab=elements"), note: "Lock logos, product areas and taglines; every operation respects the locks." },
      { id: 21, name: "Remake: Visuals", tier: 2, status: "built", href: REMAKE(), note: "A regional key visual from an image model, with Indic text set in code, never drawn by the model." },
      { id: 22, name: "Remake: Sound", tier: 2, status: "built", href: REMAKE("sound"), note: "A regional voice-over generated with text-to-speech, confirmed before it runs." },
      { id: 23, name: "Remake: Video", tier: 2, status: "built", href: REMAKE("video"), note: "A short regional clip from the remade key visual with Veo, cost confirmed before it runs." },
      { id: 24, name: "Format Fit", tier: 3, status: "built", href: at("studio", "?tab=format"), note: "Resize for every placement." },
      { id: 25, name: "Version Tree", tier: 1, status: "built", href: at("studio", "?tab=elements"), note: "Every operation creates a version; the original is never overwritten." },
      { id: 26, name: "Voice Director", tier: 2, status: "built", href: at("studio", "?tab=direct"), note: "Direct the edit by speaking." },
      { id: 27, name: "Claim Guard", tier: 3, status: "built", href: at("studio", "?tab=claims"), note: "Checks product claims against what the brand can substantiate." },
      { id: 28, name: "Script Check", tier: 3, status: "built", href: at("studio", "?tab=script"), note: "Checks rendered Indic script for shaping errors." },
      { id: 59, name: "Generate", tier: 2, status: "built", href: GENERATE, note: "A new image, voice-over or jingle made from the brief and Brand Kit, stored with its model, prompt version and cost." },
    ],
  },
  lab: {
    key: "lab",
    number: 4,
    label: "Audience Lab",
    Icon: UsersRound,
    purpose: "Audience panel rehearsals before you spend on media.",
    features: [
      { id: 29, name: "Quick Read", tier: 1, status: "built", href: at("lab"), note: "First reactions, message understanding, confusion and regional concerns from an audience panel." },
      { id: 30, name: "Audience Study", tier: 2, status: "built", href: at("lab", "?tab=study"), note: "A bounded panel with profiles by state, language, city tier and age band." },
      { id: 31, name: "Ask the Panel", tier: 2, status: "built", href: at("lab", "?tab=ask"), note: "Follow-up questions to the same participants, with their memory kept." },
      { id: 32, name: "Live Focus Group", tier: 3, status: "built", href: at("lab", "?tab=focus"), note: "A moderated panel discussion." },
      { id: 33, name: "Buzz Simulator", tier: 3, status: "built", href: at("lab", "?tab=buzz"), note: "How talk about the campaign might spread." },
      { id: 34, name: "Risk Check", tier: 1, status: "built", href: at("lab", "?tab=risk"), note: "Risk findings pinned to the image region or video moment they concern, with their evidence." },
      { id: 35, name: "Message Check", tier: 3, status: "built", href: at("lab", "?tab=check"), note: "Whether the intended message survives adaptation." },
    ],
  },
  launch: {
    key: "launch",
    number: 5,
    label: "Launch Room",
    Icon: Stamp,
    purpose: "Compare versions under fixed, visible rules and decide Go, Fix or Rethink.",
    features: [
      { id: 36, name: "Compare and Score", tier: 1, status: "built", href: at("launch", "?tab=compare"), note: "Versions scored by fixed, visible rules; the model may observe, it never sets the score." },
      { id: 37, name: "Readiness Board", tier: 1, status: "built", href: at("launch"), note: "Go, Fix or Rethink, each with its main reason and next action." },
      { id: 38, name: "Review Links", tier: 2, status: "built", href: at("launch", "?tab=review-links"), note: "Share a version for sign-off." },
      { id: 39, name: "Region Plan", tier: 2, status: "built", href: at("launch", "?tab=region-plan"), note: "Which version goes to which region, when." },
      { id: 40, name: "Asset Pack", tier: 2, status: "built", href: at("launch", "?tab=asset-pack"), note: "Export everything a region needs." },
      { id: 41, name: "Push to Platform", tier: 3, status: "roadmap", note: "Send approved versions to ad platforms." },
    ],
  },
  pulse: {
    key: "pulse",
    number: 6,
    label: "Live Pulse",
    Icon: Activity,
    purpose: "Platform results by region and version, with live, delayed and provisional data told apart.",
    features: [
      { id: 42, name: "Connect Accounts", tier: 3, status: "roadmap", note: "Google Ads, Meta and GA4 connections." },
      { id: 43, name: "Regional Dashboard", tier: 2, status: "built", href: at("pulse"), note: "Delivery, cost, response, video and outcome by region and version." },
      { id: 44, name: "Predicted vs Actual", tier: 3, status: "built", href: at("pulse", "?view=predicted"), note: "Audience Lab predictions against real results." },
      { id: 45, name: "Alerts", tier: 3, status: "built", href: at("pulse", "?view=alerts"), note: "Notice when a region moves." },
      { id: 46, name: "Comment Pulse", tier: 3, status: "built", href: at("pulse", "?view=comments"), note: "What people say under the ads, by region, language and version." },
      { id: 47, name: "Fatigue Watch", tier: 3, status: "built", href: at("pulse", "?view=fatigue"), note: "When a creative wears out." },
      { id: 48, name: "Weekly Digest", tier: 3, status: "built", href: at("pulse", "?view=digest"), note: "The week summarised from stored records, with next actions." },
    ],
  },
  proof: {
    key: "proof",
    number: 7,
    label: "Proof Vault",
    Icon: Vault,
    purpose: "The report, evidence map, search and run history behind every decision.",
    keepParams: ["report"],
    features: [
      { id: 49, name: "Proof Report", tier: 1, status: "built", href: at("proof"), note: "Findings, sources, conflicts, creative changes, audience results, risks, readiness, limitations and run metadata in one report." },
      { id: 50, name: "Evidence Map", tier: 2, status: "built", href: at("proof", "?view=map"), note: "Sources, claims, scenes, risk flags, versions and approvals as one connected map." },
      { id: 51, name: "Search", tier: 2, status: "built", href: at("proof", "?view=search"), note: "Find any claim, source or decision." },
      { id: 52, name: "Run History", tier: 1, status: "built", href: at("proof", "?view=history"), note: "Every run with its model, prompt version, cost estimate and state." },
      { id: 53, name: "Data Health", tier: 2, status: "built", href: at("proof", "?view=health"), note: "Stale sources, thin coverage and open conflicts, listed." },
    ],
  },
};

/** Platform features that sit under every workspace (the trust layer on the landing page). */
export const PLATFORM_FEATURES: Feature[] = [
  { id: 54, name: "Teams and Roles", tier: 1, status: "built", href: SETTINGS, note: "Workspaces, brands and campaigns are private to their team; permissions are enforced on the server." },
  { id: 55, name: "Resumable Runs", tier: 1, status: "built", href: at("proof", "?view=history"), note: "Long jobs run in the background with a visible state, and an interrupted run resumes instead of starting over." },
  { id: 56, name: "Model Gateway", tier: 1, status: "built", href: at("proof", "?view=history"), note: "One gateway for every model call: model, prompt version, tokens, cost estimate and latency recorded, with budget limits." },
  { id: 57, name: "Country Packs: India", tier: 2, status: "built", href: SETTINGS, note: "All 36 states and union territories, their languages and scripts, ready for Market Lens." },
  { id: 58, name: "Usage and Credits", tier: 3, status: "built", href: USAGE, note: "Spend by workspace and campaign." },
];

export const WORKSPACE_ORDER: WorkspaceKey[] = ["desk", "lens", "studio", "lab", "launch", "pulse", "proof"];

export function workspaceHref(campaignId: string, key: WorkspaceKey) {
  return `/app/c/${campaignId}/${key}`;
}

/** Where a feature goes for this campaign, or null when it has no link (or needs a campaign and there is none). */
export function featureHref(feature: Feature, campaignId: string | null): string | null {
  if (!feature.href) return null;
  if (campaignId) return feature.href(campaignId);
  const href = feature.href("");
  return href.startsWith("/app/c/") ? null : href;
}

/** Features a person can click: built ones that go somewhere. */
export const isOpenable = (feature: Feature) => feature.status === "built" && Boolean(feature.href);

/** The built features of a workspace that navigation lists. Action-only features (Command Bar, Demo Mode) stay in the catalogue but are never listed. */
export const navFeatures = (key: WorkspaceKey) => WORKSPACES[key].features.filter(isOpenable);

/** One chip of the "In this workspace" row: a distinct place, named after every feature that opens it. */
export type WorkspaceView = { name: string; title: string; href: (campaignId: string) => string };

/** The workspace a feature opens: the campaign page it links into, else the workspace that lists it (Today View is Campaign Desk's). */
function opensIn(feature: Feature, listedIn: WorkspaceKey | null): WorkspaceKey | null {
  const segment = /^\/app\/c\/[^/]*\/([^/?]+)/.exec(feature.href?.("") ?? "")?.[1];
  return isWorkspaceKey(segment) ? segment : listedIn;
}

/**
 * The chips for a workspace: every place its features open, one chip per place. Features that open the same place share a chip
 * (Transcreate and Tone Dials), so the row never highlights two chips for one view; views with no feature of their own are added.
 */
export function workspaceViews(key: WorkspaceKey): WorkspaceView[] {
  const candidates = [
    ...WORKSPACE_ORDER.flatMap((k) => WORKSPACES[k].features.map((feature) => ({ feature, listedIn: k as WorkspaceKey | null }))),
    ...PLATFORM_FEATURES.map((feature) => ({ feature, listedIn: null })),
  ].filter(({ feature, listedIn }) => isOpenable(feature) && opensIn(feature, listedIn) === key);
  // The workspace's own features come first, in catalogue order; features listed elsewhere that open here (Brand Glossary) follow.
  candidates.sort((a, b) => Number(b.listedIn === key) - Number(a.listedIn === key));
  const groups = new Map<string, { ids: number[]; features: Feature[] }>();
  for (const { feature } of candidates) {
    const place = feature.href!("");
    const group = groups.get(place) ?? { ids: [], features: [] };
    group.ids.push(feature.id);
    group.features.push(feature);
    groups.set(place, group);
  }
  const views = [...groups.values()].map((g) => ({
    ids: g.ids,
    name: g.features.map((f) => f.name).join(" · "),
    title: g.features.map((f) => (g.features.length > 1 ? `${f.name}: ${f.note}` : f.note)).join("\n"),
    href: g.features[0].href!,
  }));
  for (const extra of WORKSPACES[key].extraViews ?? []) {
    const index = views.findIndex((v) => v.ids.includes(extra.after));
    views.splice(index < 0 ? views.length : index + 1, 0, { ids: [], name: extra.name, title: extra.note, href: extra.href });
  }
  return views.map(({ name, title, href }) => ({ name, title, href }));
}

export function isWorkspaceKey(value: string | null | undefined): value is WorkspaceKey {
  return Boolean(value && (WORKSPACE_ORDER as string[]).includes(value));
}
