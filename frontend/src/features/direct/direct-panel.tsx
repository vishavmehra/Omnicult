"use client";

import { ArrowRight, Check, ChevronRight, CircleSlash, Mic, MicOff, Square, Wand2 } from "lucide-react";
import { useId, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MutationError, NativeSelect, Status, useStudio } from "@/features/studio/parts";
import type { VersionNode } from "@/features/studio/types";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useApplyPlan, useCreatePlan, useDirectPlans, useTranscribe } from "./api";
import { PlanView } from "./plan-view";
import type { DirectPlan } from "./types";
import { MAX_SECONDS, extensionOf, useRecorder } from "./use-recorder";

const MAX_CHARS = 500;
/** The demo fixtures answer exactly these (backend app/fixtures/demo_voice.py); anything else gets "No demo fixture". */
const DEMO_EXAMPLES = [
  "Make the Tamil headline warmer, keep the brand name",
  "Lock the call to action",
  "Make the tagline shorter",
  "Suggest tweak chips for the delivery line",
  "Adapt this for West Bengal in Bengali",
  "Go back to the original",
  "Open the Launch Room",
];
const LIVE_EXAMPLES = ["Make the headline warmer, keep the brand name", "Lock the call to action", "Go back to the original", "Open the Audience Lab"];
const PLAN_STATUS = {
  applied: { tone: "success", Icon: Check, word: "Applied" },
  proposed: { tone: "neutral", Icon: ArrowRight, word: "Not applied" },
  partial: { tone: "neutral", Icon: ArrowRight, word: "Partly applied" },
  refused: { tone: "warning", Icon: CircleSlash, word: "Nothing applied" },
  unsupported: { tone: "warning", Icon: CircleSlash, word: "Not planned" },
} as const;

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/**
 * Voice Director: say or type what should change in the selected version. The server turns it into a plan of steps over the
 * Studio's own tools, checks every step in code, and nothing runs until the person confirms. Speech is recorded only while
 * the button is held, transcribed, and shown here to correct before it is planned.
 */
export function DirectPanel({
  version,
  number,
  numbers,
  onOpenVersion,
  onShowRun,
}: {
  version: VersionNode;
  number: number;
  numbers: Map<string, number>;
  onOpenVersion(id: string): void;
  onShowRun(runId: string): void;
}) {
  const { campaignId, demo, languages } = useStudio();
  const textId = useId();
  const hintId = useId();
  const text = useRef<HTMLTextAreaElement>(null);
  const [instruction, setInstruction] = useState("");
  const [heard, setHeard] = useState<string | null>(null);
  const [speech, setSpeech] = useState("");
  const [plan, setPlan] = useState<DirectPlan | null>(null);
  const [voiceNote, setVoiceNote] = useState<string | null>(null);

  const create = useCreatePlan(campaignId);
  const apply = useApplyPlan(campaignId);
  const transcribe = useTranscribe(campaignId);
  const history = useDirectPlans(campaignId);
  const recorder = useRecorder((clip, mime) => {
    setVoiceNote(null);
    transcribe.mutate(
      { clip, filename: `instruction.${extensionOf(mime)}`, language: speech },
      {
        onSuccess: (r) => {
          if (r.status === "transcribed" && r.transcript) {
            setInstruction(r.transcript);
            setHeard(r.transcript);
            requestAnimationFrame(() => text.current?.focus());
          } else {
            setVoiceNote(r.message ?? "No speech was heard. Hold the button while you speak, or type the instruction.");
          }
        },
      },
    );
  });

  const examples = demo ? DEMO_EXAMPLES : LIVE_EXAMPLES;
  const trimmed = instruction.trim();
  const planning = create.isPending;
  const elements = version.elements;
  const recording = recorder.state === "recording";
  const micDisabled = demo || !recorder.supported || transcribe.isPending || planning;
  const micWord = !recorder.supported
    ? "Voice input is not available here. It needs a secure page and a browser that can record audio. Type the instruction instead."
    : demo
      ? "Voice input needs a live project. Demo projects never call a model provider, so type the instruction."
      : recorder.state === "denied"
        ? "Microphone access is blocked. Allow it for this site in the browser's address bar or settings, then hold the button again. Or type the instruction."
        : recorder.state === "requesting"
          ? "Waiting for your answer to the browser's microphone prompt…"
          : (recorder.message ?? voiceNote);
  const speechOptions = useMemo(() => languages.map((l) => ({ code: l.code, name: l.name })).sort((a, b) => a.name.localeCompare(b.name)), [languages]);

  function submit() {
    if (!trimmed || planning) return;
    create.mutate(
      { versionId: version.id, instruction: trimmed, source: heard ? "voice" : "typed", transcript: heard },
      {
        onSuccess: (p) => {
          setPlan(p);
          apply.reset();
        },
      },
    );
  }

  const recent = (history.data?.items ?? []).filter((p) => p.id !== plan?.id);

  return (
    <div className="space-y-5">
      <section aria-labelledby="direct-title" className="space-y-3 rounded-card border border-border bg-surface px-4 py-3.5">
        <div className="space-y-1">
          <h2 id="direct-title" className="flex items-center gap-2 text-[16px] font-semibold text-ink">
            <Wand2 aria-hidden className="size-4 text-ink-secondary" />
            Direct this version
            <span className="font-mono text-[13px] font-normal text-ink-muted">v{number}</span>
          </h2>
          <p className="max-w-[68ch] text-[13.5px] text-ink-body">
            Say or type what should change. You get a plan made of the same steps the rest of this page offers, checked against the locks and the glossary, and nothing runs until you confirm.
          </p>
        </div>

        <form
          className="space-y-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label htmlFor={textId} className="block text-[13px] font-medium text-ink">
            Instruction
          </label>
          <Textarea
            id={textId}
            ref={text}
            value={instruction}
            maxLength={MAX_CHARS}
            rows={3}
            disabled={planning}
            placeholder={demo ? DEMO_EXAMPLES[0] : "For example: make the Tamil headline warmer, keep the brand name"}
            aria-describedby={heard ? hintId : undefined}
            onChange={(e) => {
              setInstruction(e.target.value);
              if (!e.target.value) setHeard(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            {heard ? (
              <p id={hintId} role="status" className="type-meta">
                Heard from your voice. Correct anything that is wrong before you plan it.
              </p>
            ) : (
              <span />
            )}
            <span className="type-meta tabular-nums">
              {instruction.length}/{MAX_CHARS}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <Button type="submit" disabled={!trimmed || planning}>
              <Wand2 aria-hidden />
              {planning ? "Planning…" : "Plan the steps"}
            </Button>

            <Button
              type="button"
              variant="outline"
              disabled={micDisabled}
              aria-pressed={recording}
              aria-describedby={`${hintId}-mic`}
              onPointerDown={(e) => {
                if (e.button !== 0 || micDisabled) return;
                e.currentTarget.setPointerCapture(e.pointerId);
                void recorder.start();
              }}
              onPointerUp={recorder.stop}
              onPointerCancel={recorder.stop}
              onLostPointerCapture={recorder.stop}
              onKeyDown={(e) => {
                if ((e.key === " " || e.key === "Enter") && !e.repeat) {
                  e.preventDefault();
                  void recorder.start();
                }
              }}
              onKeyUp={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault();
                  recorder.stop();
                }
              }}
              onBlur={recorder.stop}
              onContextMenu={(e) => e.preventDefault()}
              className={cn("touch-none select-none", recording && "border-danger text-danger")}
            >
              {recording ? <Square aria-hidden className="fill-current" /> : micDisabled ? <MicOff aria-hidden /> : <Mic aria-hidden />}
              {recording ? "Release to stop" : "Hold to talk"}
            </Button>

            {recorder.supported && !demo && (
              <div className="flex items-center gap-1.5">
                <label htmlFor={`${hintId}-lang`} className="text-[12.5px] text-ink-secondary">
                  Spoken in
                </label>
                <NativeSelect id={`${hintId}-lang`} value={speech} onChange={(e) => setSpeech(e.target.value)} disabled={recording || transcribe.isPending} className="w-auto min-w-[8rem]">
                  <option value="">Detect it</option>
                  {speechOptions.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}
          </div>

          <div id={`${hintId}-mic`} className="min-h-5 text-[12.5px] text-ink-secondary">
            {recording ? (
              <p className="flex items-center gap-2 font-medium text-danger">
                <span aria-hidden className="size-2.5 rounded-full bg-danger motion-safe:animate-pulse" />
                Recording <span className="tabular-nums" aria-hidden>{mmss(recorder.seconds)} of {mmss(MAX_SECONDS)}</span>
              </p>
            ) : transcribe.isPending ? (
              <LoadingState label="Transcribing what you said…" className="py-0" />
            ) : micWord ? (
              <p role="status">{micWord}</p>
            ) : recorder.supported && !demo ? (
              <p>Hold the button (or hold Space while it has focus) and speak, then release. Up to {MAX_SECONDS} seconds. The recording is transcribed and not kept.</p>
            ) : null}
          </div>
          {transcribe.isError && <MutationError error={transcribe.error} />}
        </form>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          <span className="type-meta">{demo ? "Demo instructions:" : "Try:"}</span>
          {examples.map((example) => (
            <Button
              key={example}
              type="button"
              size="xs"
              variant="outline"
              disabled={planning}
              onClick={() => {
                setInstruction(example);
                setHeard(null);
                text.current?.focus();
              }}
            >
              {example}
            </Button>
          ))}
        </div>
      </section>

      {planning && <LoadingState label="Reading the instruction and checking each step against the locks, glossary and reference lists…" />}
      {create.isError && <MutationError error={create.error} onRetry={submit} />}
      {plan && (
        <PlanView
          key={plan.id}
          plan={plan}
          elements={elements}
          numbers={numbers}
          applying={apply.isPending}
          applyError={apply.error}
          onApply={(stepIds) =>
            apply.mutate(
              { planId: plan.id, stepIds },
              {
                onSuccess: (p) => {
                  setPlan(p);
                  const done = p.steps.filter((s) => stepIds.includes(s.id) && s.status === "applied").length;
                  if (done > 0) toast.success(done === 1 ? "Step applied" : `${done} steps applied`);
                  else toast.warning("Nothing was applied. The steps say why.");
                },
              },
            )
          }
          onOpenVersion={onOpenVersion}
          onShowRun={onShowRun}
        />
      )}

      {recent.length > 0 && (
        <details className="group rounded-card border border-border bg-surface px-4 py-2.5">
          <summary className="flex cursor-pointer items-center gap-2 text-[13.5px] font-semibold text-ink select-none">
            <ChevronRight aria-hidden className="size-3.5 transition-transform group-open:rotate-90" />
            Earlier directions
            <span className="font-normal text-ink-muted">{recent.length}</span>
          </summary>
          <ul className="ledger-rules mt-2">
            {recent.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[13px]">
                <span className="min-w-0 flex-1 truncate text-ink-body">&ldquo;{p.instruction}&rdquo;</span>
                <span className="font-mono text-[11.5px] text-ink-muted">v{numbers.get(p.version_id) ?? "?"}</span>
                <Status tone={PLAN_STATUS[p.status].tone} Icon={PLAN_STATUS[p.status].Icon}>
                  {PLAN_STATUS[p.status].word}
                </Status>
                <span className="type-meta" title={p.created_at}>
                  {formatRelative(p.created_at)}
                </span>
                <Button size="xs" variant="outline" onClick={() => setPlan(p)}>
                  Open
                </Button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
