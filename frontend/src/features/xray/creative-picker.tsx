"use client";

import { Plus } from "lucide-react";

import { RunStatusBadge } from "@/components/workflow/run-status";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useBlob, useObjectUrl, type Asset, type CreativeSummary } from "./api";
import { plural } from "./media-file";
import { clock } from "./parts";
import { KIND_ICON, KIND_LABEL } from "./upload-panel";

function Thumb({ path, kind }: { path: string | null; kind: CreativeSummary["kind"] }) {
  const blob = useBlob(path);
  const src = useObjectUrl(blob.data);
  const Icon = KIND_ICON[kind];
  return (
    <span className="clay-well grid h-14 w-11 shrink-0 place-items-center overflow-hidden rounded-md">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- authenticated blob
        <img src={src} alt="" className="size-full object-cover" />
      ) : (
        <Icon aria-hidden className="size-4 text-ink-muted" />
      )}
    </span>
  );
}

/**
 * The campaign's creatives, one entry each, with the state of its latest run. Uploads that were never analysed sit after
 * them with a button to start. The selected creative is marked with `aria-current`, not by colour alone.
 */
export function CreativePicker({
  creatives,
  pending,
  selectedId,
  onSelect,
  onAnalyse,
  onAdd,
}: {
  creatives: CreativeSummary[];
  pending: Asset[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAnalyse: (asset: Asset) => void;
  onAdd: () => void;
}) {
  return (
    <nav aria-label="Creatives of this campaign">
      <ul className="flex gap-2.5 overflow-x-auto pb-1">
        {creatives.map((c) => {
          const selected = c.id === selectedId;
          return (
            <li key={c.id} className="w-[15.5rem] shrink-0">
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                aria-current={selected ? "true" : undefined}
                className={cn(
                  "clay flex h-full w-full items-start gap-2.5 rounded-xl border p-2.5 text-left",
                  selected ? "border-primary" : "border-border hover:border-border-strong",
                )}
              >
                <Thumb path={c.thumbnail_url} kind={c.kind} />
                <span className="min-w-0 flex-1 space-y-0.5">
                  <span className="block truncate text-[13.5px] font-medium text-ink">{c.label}</span>
                  <span className="type-ledger block text-[12px] text-ink-secondary">
                    {KIND_LABEL[c.kind]}
                    {c.duration_ms != null && <> · {clock(c.duration_ms)}</>}
                    {c.current_run_id && <> · {plural(c.scene_count, "scene")}</>}
                  </span>
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    {c.status ? <RunStatusBadge status={c.status} /> : <span className="type-meta">Not run yet</span>}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {pending.map((a) => (
          <li key={a.id} className="w-[15.5rem] shrink-0">
            <div className="flex h-full items-start gap-2.5 rounded-xl border border-dashed border-border-strong/60 bg-surface-muted/50 p-2.5">
              <span className="clay-well grid h-14 w-11 shrink-0 place-items-center rounded-md">
                {(() => {
                  const Icon = KIND_ICON[a.kind];
                  return <Icon aria-hidden className="size-4 text-ink-muted" />;
                })()}
              </span>
              <span className="min-w-0 flex-1 space-y-1">
                <span className="block truncate text-[13.5px] font-medium text-ink">{a.filename}</span>
                <span className="type-ledger block text-[12px] text-ink-secondary">Uploaded, not analysed</span>
                <Button size="xs" variant="outline" onClick={() => onAnalyse(a)}>
                  Analyse
                </Button>
              </span>
            </div>
          </li>
        ))}
        <li className="shrink-0">
          <Button variant="outline" className="h-full min-h-[4.75rem]" onClick={onAdd}>
            <Plus aria-hidden />
            Add a creative
          </Button>
        </li>
      </ul>
    </nav>
  );
}
