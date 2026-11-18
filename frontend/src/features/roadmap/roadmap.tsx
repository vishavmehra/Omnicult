import { CircleDashed } from "lucide-react";

import { Tag } from "@/components/evidence/badges";

type Item = {
  id: number;
  name: string;
  workspace: string;
  does: string[];
  needs: string[];
  meanwhile: string;
};

/**
 * Four planned features that are not built. Each one waits on access or a cost decision. This is a list, not a preview:
 * nothing here is mocked up, and none of it is described as working.
 */
const ITEMS: Item[] = [
  {
    id: 13,
    name: "Share of Search",
    workspace: "Market Lens",
    does: [
      "Set a brand against its competitors for one region and one time range, and show how public search interest compares, using the same search terms and the same period for every brand.",
      "It would show search interest only. It would never be called market share, and it says nothing about sales or purchase intent.",
    ],
    needs: [
      "Access to the Google Trends API, which is in alpha. Google has to grant it to the project; it cannot be switched on from here.",
      "A written list of the search terms to compare, shown beside every result.",
    ],
    meanwhile: "Nothing in the product stands in for search interest.",
  },
  {
    id: 23,
    name: "Remake: Video",
    workspace: "Creative Studio",
    does: [
      "Make a short regional cut of an approved creative with Google's Veo model, keep the locked brand elements, set Indic text in code, and render the vertical and standard sizes with ffmpeg.",
      "Every generation would ask for approval first and run under a cost ceiling.",
    ],
    needs: [
      "Veo access on the Google Cloud project.",
      "A confirmed Veo cost on the trial credit. Veo bills for the video it generates, and no price has been checked for this project, so none is shown here.",
      "A per-run cost ceiling that fits that price, and a check that the output quality is dependable enough to offer.",
    ],
    meanwhile: "Creative X-Ray reads an uploaded video. Nothing in the product generates one.",
  },
  {
    id: 41,
    name: "Push to Platform",
    workspace: "Launch Room",
    does: [
      "Send an approved creative to Google Ads or YouTube as a draft, attached to the right campaign, with the platform's own ID stored and any failure shown.",
      "It would never publish a live campaign on its own. A person authorizes each publishing action.",
    ],
    needs: [
      "Developer access for the ad platforms: Google Ads (a developer token) and Meta (an app with ads permissions).",
      "OAuth tokens from the account that owns the ads, which means Connect Accounts has to exist first, with encrypted storage, limited scopes and a way to revoke.",
      "Platform-specific checks of the creative before a draft is made.",
    ],
    meanwhile: "Launch Room still decides Go, Fix or Rethink. Publishing stays a step you take in the ad platform.",
  },
  {
    id: 42,
    name: "Connect Accounts",
    workspace: "Live Pulse",
    does: [
      "Let a workspace owner connect their own Google Ads, Meta Ads and GA4 accounts so Live Pulse can show real results beside the sample dataset, and say when each account was last synced.",
      "Connections would be read-only where the platform allows it, listed with their status, and revocable at any time.",
    ],
    needs: [
      "Developer access and an approved app on each platform: Google Ads, Meta and GA4.",
      "OAuth consent set up for each, with tokens kept on the server in encrypted storage and never sent to the browser.",
      "A sync schedule, and a visible error state when an account stops answering.",
    ],
    meanwhile: "Live Pulse runs on its labelled sample dataset.",
  },
];

export function Roadmap() {
  return (
    <>
      <header className="mb-6 space-y-1.5 border-b border-border pb-5">
        <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Roadmap</h1>
        <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">
          Four features are planned and not built. Each waits on access or a cost decision that is not ours to assume. None of them is mocked up or shown as working anywhere in Omnicult.
        </p>
      </header>

      <ol className="space-y-5">
        {ITEMS.map((item) => (
          <li key={item.id}>
            <article aria-labelledby={`roadmap-${item.id}`} className="rounded-card border border-border bg-surface p-4 sm:p-5">
              <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
                <span aria-label={`Feature ${item.id}`} className="font-mono text-[12px] text-ink-muted">
                  {String(item.id).padStart(2, "0")}
                </span>
                <h2 id={`roadmap-${item.id}`} className="type-title text-[22px] text-ink">
                  {item.name}
                </h2>
                <span className="text-[13.5px] text-ink-secondary">{item.workspace}</span>
                <Tag className="ml-auto border-dashed border-ink-secondary/50 bg-surface-muted text-ink-secondary">
                  <CircleDashed aria-hidden />
                  Not built
                </Tag>
              </div>
              <div className="grid gap-5 md:grid-cols-2">
                <section aria-label={`What ${item.name} would do`} className="space-y-2">
                  <h3 className="text-[15px] font-semibold text-ink">What it would do</h3>
                  {item.does.map((p) => (
                    <p key={p} className="max-w-[60ch] text-[14px] leading-relaxed text-ink-body">
                      {p}
                    </p>
                  ))}
                </section>
                <section aria-label={`What ${item.name} needs`} className="space-y-2">
                  <h3 className="text-[15px] font-semibold text-ink">What it needs</h3>
                  <ul className="space-y-1.5">
                    {item.needs.map((n) => (
                      <li key={n} className="flex items-start gap-2 text-[14px] leading-relaxed text-ink-body">
                        <CircleDashed aria-hidden className="mt-1 size-3.5 shrink-0 text-ink-muted" />
                        <span>
                          <span className="sr-only">Needed: </span>
                          {n}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
              <p className="mt-4 border-t border-border pt-3 text-[13.5px] text-ink-secondary">
                <span className="font-medium text-ink">Today: </span>
                {item.meanwhile}
              </p>
            </article>
          </li>
        ))}
      </ol>
    </>
  );
}
