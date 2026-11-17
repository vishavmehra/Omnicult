import { Activity, Clapperboard, NotebookPen, ScanSearch, Stamp, UsersRound, Vault, type LucideIcon } from "lucide-react";

export type WorkspaceKey = "desk" | "lens" | "studio" | "lab" | "launch" | "pulse" | "proof";

/** Scope tiers from docs/SCOPE_PLAN.md. Tiers 1 and 2 are the product; tier 3 is roadmap and is always labelled as such. */
export type Tier = 1 | 2 | 3;

export type Feature = { id: number; name: string; tier: Tier; note: string };

export type Stage = { key: string; label: string; summary: string; workspaces: WorkspaceKey[] };

export type Workspace = {
  key: WorkspaceKey;
  /** Position on the workflow line; carries information (the order work moves in), so it is shown. */
  number: number;
  label: string;
  Icon: LucideIcon;
  purpose: string;
  features: Feature[];
};

/** The workflow stages, in order. Navigation and the landing page group workspaces under these headings (SCOPE_PLAN rules). */
export const STAGES: Stage[] = [
  { key: "plan", label: "Plan and understand", summary: "Write the brief once, then learn the place before touching the creative.", workspaces: ["desk", "lens"] },
  { key: "create", label: "Create", summary: "Keep the original in view while every regional change is proposed, explained and versioned.", workspaces: ["studio"] },
  { key: "test", label: "Test", summary: "Rehearse with a labelled synthetic audience before spending on media.", workspaces: ["lab"] },
  { key: "decide", label: "Decide and ship", summary: "Fixed, visible rules turn scores into Go, Fix or Rethink.", workspaces: ["launch"] },
  { key: "track", label: "Track", summary: "What really happened, region by region, with its freshness stated.", workspaces: ["pulse"] },
  { key: "prove", label: "Prove", summary: "Answer “why did we make this decision?” from the record.", workspaces: ["proof"] },
];

export const WORKSPACES: Record<WorkspaceKey, Workspace> = {
  desk: {
    key: "desk",
    number: 1,
    label: "Campaign Desk",
    Icon: NotebookPen,
    purpose: "The campaign brief and Brand Kit every other workspace reads from.",
    features: [
      { id: 1, name: "Today View", tier: 1, note: "What is running, what finished, what failed and which campaigns need attention, across every brand." },
      { id: 2, name: "Campaign Brief", tier: 1, note: "Product, objective, regions, languages, channels, budget, dates and success metric, entered once and read everywhere." },
      { id: 3, name: "Brand Kit", tier: 1, note: "Tone, protected terms and the elements that must never change." },
      { id: 4, name: "Brand Glossary", tier: 2, note: "Brand spellings by script, preferred translations, pronunciation and do-not-translate terms." },
      { id: 5, name: "Command Bar", tier: 2, note: "Type what you want done; it runs the same tools the workspaces use." },
      { id: 6, name: "Demo Mode", tier: 1, note: "A complete sample campaign on labelled fixtures, never mixed with your records." },
    ],
  },
  lens: {
    key: "lens",
    number: 2,
    label: "Market Lens",
    Icon: ScanSearch,
    purpose: "Regional cultural intelligence where every fact is traceable to its source.",
    features: [
      { id: 7, name: "Culture Atlas", tier: 1, note: "Cultural signals for a region, each traceable to the source it came from." },
      { id: 8, name: "State Profile", tier: 1, note: "Languages, scripts, festivals, food, colours, symbols, humour, customs and sensitivities for an Indian state, every fact tagged." },
      { id: 9, name: "Language Map", tier: 2, note: "Language and script mix, state by state." },
      { id: 10, name: "Moment Calendar", tier: 2, note: "Festivals and moments that matter for timing." },
      { id: 11, name: "Market Compare", tier: 1, note: "States side by side on the same evidence." },
      { id: 12, name: "Trend Radar", tier: 3, note: "Rising public interest by region." },
      { id: 13, name: "Share of Search", tier: 3, note: "Search interest against competitors." },
      { id: 14, name: "Category Shelf", tier: 3, note: "How the category shows up regionally." },
      { id: 15, name: "Evidence Meter", tier: 1, note: "How much of a profile is observed, calculated, interpreted or unverified, and from how many independent sources." },
    ],
  },
  studio: {
    key: "studio",
    number: 3,
    label: "Creative Studio",
    Icon: Clapperboard,
    purpose: "Inspect the original creative, adapt it per region, and compare every version with the original.",
    features: [
      { id: 16, name: "Creative X-Ray", tier: 1, note: "The creative decomposed into scenes, keyframes, text, transcript, claims and visual observations." },
      { id: 17, name: "Transcreate", tier: 1, note: "Regional copy with an English back-translation beside every line." },
      { id: 18, name: "Tone Dials", tier: 2, note: "Formality, warmth and humour per region, inside the brand voice." },
      { id: 19, name: "Tweak Chips", tier: 1, note: "Small suggested changes, each with its reason, evidence and cost, inspected before you apply them." },
      { id: 20, name: "Lock and Edit", tier: 1, note: "Lock logos, product areas and taglines; every operation respects the locks." },
      { id: 21, name: "Remake: Visuals", tier: 2, note: "A regional key visual from an image model, with Indic text set in code, never drawn by the model." },
      { id: 22, name: "Remake: Sound", tier: 2, note: "A regional voice-over generated with text-to-speech, confirmed before it runs." },
      { id: 23, name: "Remake: Video", tier: 3, note: "Regional video cuts." },
      { id: 24, name: "Format Fit", tier: 3, note: "Resize for every placement." },
      { id: 25, name: "Version Tree", tier: 1, note: "Every operation creates a version; the original is never overwritten." },
      { id: 26, name: "Voice Director", tier: 2, note: "Direct the edit by speaking." },
      { id: 27, name: "Claim Guard", tier: 3, note: "Checks product claims against what the brand can substantiate." },
      { id: 28, name: "Script Check", tier: 3, note: "Checks rendered Indic script for shaping errors." },
    ],
  },
  lab: {
    key: "lab",
    number: 4,
    label: "Audience Lab",
    Icon: UsersRound,
    purpose: "Synthetic audience rehearsals, always labelled as simulation, never as consumer research.",
    features: [
      { id: 29, name: "Quick Read", tier: 1, note: "First reactions, message understanding, confusion and regional concerns from a synthetic panel, labelled synthetic throughout." },
      { id: 30, name: "Audience Study", tier: 2, note: "A bounded synthetic panel with profiles by state, language, city tier and age band." },
      { id: 31, name: "Ask the Panel", tier: 2, note: "Follow-up questions to the same synthetic participants, with their memory kept." },
      { id: 32, name: "Live Focus Group", tier: 3, note: "A moderated synthetic discussion." },
      { id: 33, name: "Buzz Simulator", tier: 3, note: "How talk about the campaign might spread." },
      { id: 34, name: "Risk Check", tier: 1, note: "Risk findings pinned to the image region or video moment they concern, with their evidence." },
      { id: 35, name: "Message Check", tier: 3, note: "Whether the intended message survives adaptation." },
    ],
  },
  launch: {
    key: "launch",
    number: 5,
    label: "Launch Room",
    Icon: Stamp,
    purpose: "Compare versions under fixed, visible rules and decide Go, Fix or Rethink.",
    features: [
      { id: 36, name: "Compare and Score", tier: 1, note: "Versions scored by fixed, visible rules; the model may observe, it never sets the score." },
      { id: 37, name: "Readiness Board", tier: 1, note: "Go, Fix or Rethink, each with its main reason and next action." },
      { id: 38, name: "Review Links", tier: 3, note: "Share a version for sign-off." },
      { id: 39, name: "Region Plan", tier: 3, note: "Which version goes to which region, when." },
      { id: 40, name: "Asset Pack", tier: 3, note: "Export everything a region needs." },
      { id: 41, name: "Push to Platform", tier: 3, note: "Send approved versions to ad platforms." },
    ],
  },
  pulse: {
    key: "pulse",
    number: 6,
    label: "Live Pulse",
    Icon: Activity,
    purpose: "Platform results by region and version, with live, delayed, provisional and sample data told apart.",
    features: [
      { id: 42, name: "Connect Accounts", tier: 3, note: "Google Ads, Meta and GA4 connections." },
      { id: 43, name: "Regional Dashboard", tier: 2, note: "Delivery, cost, response, video and outcome by region and version, on a clearly labelled sample dataset until an account is connected." },
      { id: 44, name: "Predicted vs Actual", tier: 3, note: "Audience Lab predictions against real results." },
      { id: 45, name: "Alerts", tier: 3, note: "Notice when a region moves." },
      { id: 46, name: "Comment Pulse", tier: 3, note: "What people say under the ads." },
      { id: 47, name: "Fatigue Watch", tier: 3, note: "When a creative wears out." },
      { id: 48, name: "Weekly Digest", tier: 3, note: "The week, summarised." },
    ],
  },
  proof: {
    key: "proof",
    number: 7,
    label: "Proof Vault",
    Icon: Vault,
    purpose: "The report, evidence map, search and run history behind every decision.",
    features: [
      { id: 49, name: "Proof Report", tier: 1, note: "Findings, sources, conflicts, creative changes, audience results, risks, readiness, limitations and run metadata in one report." },
      { id: 50, name: "Evidence Map", tier: 2, note: "Sources, claims, scenes, risk flags, versions and approvals as one connected map." },
      { id: 51, name: "Search", tier: 2, note: "Find any claim, source or decision." },
      { id: 52, name: "Run History", tier: 1, note: "Every run with its model, prompt version, cost estimate and state." },
      { id: 53, name: "Data Health", tier: 2, note: "Stale sources, thin coverage and open conflicts, listed." },
    ],
  },
};

/** Platform features that sit under every workspace (the trust layer on the landing page). */
export const PLATFORM_FEATURES: Feature[] = [
  { id: 54, name: "Teams and Roles", tier: 1, note: "Workspaces, brands and campaigns are private to their team; permissions are enforced on the server." },
  { id: 55, name: "Resumable Runs", tier: 1, note: "Long jobs run in the background with a visible state, and an interrupted run resumes instead of starting over." },
  { id: 56, name: "Model Gateway", tier: 1, note: "One gateway for every model call: model, prompt version, tokens, cost estimate and latency recorded, with budget limits." },
  { id: 57, name: "Country Packs: India", tier: 2, note: "All 36 states and union territories, their languages and scripts, ready for Market Lens." },
  { id: 58, name: "Usage and Credits", tier: 3, note: "Spend by workspace and campaign." },
];

export const WORKSPACE_ORDER: WorkspaceKey[] = ["desk", "lens", "studio", "lab", "launch", "pulse", "proof"];

export function workspaceHref(campaignId: string, key: WorkspaceKey) {
  return `/app/c/${campaignId}/${key}`;
}

export function isWorkspaceKey(value: string | null | undefined): value is WorkspaceKey {
  return Boolean(value && (WORKSPACE_ORDER as string[]).includes(value));
}
