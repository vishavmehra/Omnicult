"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Field, TermListInput } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { checkWeights, WEIGHT_FIELDS } from "@/features/project/campaign-form";
import { campaignKeys } from "@/features/workspaces/campaign-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Campaign, CampaignUpdate, EvaluationCriteria } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const optional = (s: string) => (s.trim() ? s.trim() : null);

/**
 * Edit the original creative copy and the scoring weights. The brief (objective, regions, dates and the rest) has its own
 * editor; this only touches what the campaign record keeps apart: the copy, which versions on save, and the weights.
 */
export function CopyEditor({ campaign, demo, onDone, onCancel }: { campaign: Campaign; demo: boolean; onDone(): void; onCancel(): void }) {
  const uid = useId();
  const queryClient = useQueryClient();
  const current = campaign.current_version.content;
  const [headline, setHeadline] = useState(current.headline ?? "");
  const [body, setBody] = useState(current.body ?? "");
  const [cta, setCta] = useState(current.call_to_action ?? "");
  const [terms, setTerms] = useState<string[]>(current.reference_terms);
  const [weights, setWeights] = useState<Record<keyof EvaluationCriteria, string>>(
    () => Object.fromEntries(WEIGHT_FIELDS.map((f) => [f.key, String(campaign.evaluation_criteria[f.key])])) as Record<keyof EvaluationCriteria, string>,
  );
  const check = checkWeights(weights);
  const content = { headline: optional(headline), body: optional(body), call_to_action: optional(cta), reference_terms: terms };
  const contentChanged =
    content.headline !== current.headline || content.body !== current.body || content.call_to_action !== current.call_to_action || terms.join("\n") !== current.reference_terms.join("\n");
  const weightsChanged = WEIGHT_FIELDS.some((f) => check.values[f.key] !== campaign.evaluation_criteria[f.key]);
  const hasCopy = Boolean(content.headline || content.body);

  const save = useMutation({
    mutationFn: () => {
      const patch: CampaignUpdate = {};
      if (contentChanged && !demo) patch.original_content = content;
      if (weightsChanged) patch.evaluation_criteria = check.values;
      return unwrap(api.PATCH("/api/v1/campaigns/{campaign_id}", { params: { path: { campaign_id: campaign.id } }, body: patch }));
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: campaignKeys.detail(campaign.id) });
      void queryClient.invalidateQueries({ queryKey: ["directory"] });
      toast.success(contentChanged && !demo ? `Copy saved as version ${saved.current_version.version_number}` : "Weights saved");
      onDone();
    },
  });

  const blockers = [!hasCopy && !demo && "a headline or body", !check.valid && "weights that total 1.000"].filter(Boolean);
  const dirty = (contentChanged && !demo) || weightsChanged;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!save.isPending && dirty && blockers.length === 0) save.mutate();
  }

  return (
    <form onSubmit={submit} className="space-y-5" aria-label="Edit the original creative and scoring weights">
      <fieldset className="space-y-4 rounded-card border border-border bg-surface p-4 sm:p-5" disabled={demo}>
        <legend className="px-1 text-[15px] font-semibold text-ink">
          Original copy{!demo && <span className="font-normal text-ink-secondary"> (a change saves as a new version; the old one stays)</span>}
        </legend>
        {demo && (
          <p className="flex items-start gap-2 text-[13px] text-ink-secondary">
            <Lock aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            Demo copy is fixed so the saved demonstration results stay truthful. Create a live brand and campaign to test your own copy.
          </p>
        )}
        <Field label="Headline" htmlFor={`${uid}-h`} hint={`${headline.length}/300`}>
          <Input id={`${uid}-h`} value={headline} maxLength={300} onChange={(e) => setHeadline(e.target.value)} className="bg-surface" />
        </Field>
        <Field label="Body" htmlFor={`${uid}-b`} hint={`${body.length}/5000`}>
          <Textarea id={`${uid}-b`} rows={5} value={body} maxLength={5000} onChange={(e) => setBody(e.target.value)} className="bg-surface" />
        </Field>
        <Field label="Call to action" htmlFor={`${uid}-c`}>
          <Input id={`${uid}-c`} value={cta} maxLength={200} onChange={(e) => setCta(e.target.value)} className="bg-surface" />
        </Field>
        <Field label="Cultural references in the copy" htmlFor={`${uid}-t`} hint="Up to 20.">
          <TermListInput id={`${uid}-t`} value={terms} onChange={setTerms} max={20} placeholder="Add a reference" disabled={demo} />
        </Field>
      </fieldset>

      <fieldset className="space-y-3 rounded-card border border-border bg-surface p-4 sm:p-5">
        <legend className="px-1 text-[15px] font-semibold text-ink">Scoring weights</legend>
        <p className="max-w-prose text-[12.5px] text-ink-secondary">How Launch Room weighs each criterion. They must total exactly 1.000; Omnicult never rescales them.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {WEIGHT_FIELDS.map((f) => (
            <div key={f.key} className="space-y-1">
              <label htmlFor={`${uid}-w-${f.key}`} className="flex items-baseline justify-between gap-2 text-[13px] text-ink">
                {f.label}
                <span className="text-[11px] text-ink-secondary">{f.help}</span>
              </label>
              <Input id={`${uid}-w-${f.key}`} type="number" inputMode="decimal" min={0} max={1} step={0.05} value={weights[f.key]} onChange={(e) => setWeights({ ...weights, [f.key]: e.target.value })} className="bg-surface tabular-nums" />
            </div>
          ))}
        </div>
        <p role="status" className={cn("w-fit rounded-sm px-2 py-1 text-[13px] tabular-nums", check.valid ? "bg-accent text-primary" : "bg-danger-soft text-danger")}>
          Total {check.total.toFixed(3)}: {check.valid ? "valid" : "must equal 1.000 (±0.001) before saving"}
        </p>
      </fieldset>

      {save.error && <ErrorState error={save.error} />}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={save.isPending || !dirty || blockers.length > 0}>
          {save.isPending ? "Saving…" : "Save changes"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={save.isPending}>
          Cancel
        </Button>
        <p className="text-xs text-ink-secondary" aria-live="polite">
          {blockers.length > 0 ? `Needs ${blockers.join(", ")}.` : !dirty ? "No changes to save." : null}
        </p>
      </div>
    </form>
  );
}
