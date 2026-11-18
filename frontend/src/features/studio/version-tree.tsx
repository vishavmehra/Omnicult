"use client";

import { ArrowLeftRight, Bot, FileText, History, Languages, Pencil, Replace, Settings2, SlidersHorizontal, Sparkles, User, type LucideIcon } from "lucide-react";
import { useMemo } from "react";

import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { buildTree, formatCost, OPERATION_LABEL, placeTag } from "./model";
import type { Operation, OperationKind, VersionSummary } from "./types";

const OP_ICON: Record<OperationKind, LucideIcon> = {
  manual_edit: Pencil,
  replace_text: Replace,
  transcreate: Languages,
  apply_chip: Sparkles,
  swap_reference: ArrowLeftRight,
  change_setting: Settings2,
  tone_shift: SlidersHorizontal,
  restore: History,
  remake: Bot,
};

/**
 * The version tree as a ruled list. A node continues its parent's line; when one version has several children each opens a
 * branch (two regions transcreated from the same original). Every row says who or what made it, by which operation, why, and
 * what the AI part cost (an estimate). The original is a root and is never changed by anything below it.
 */
export function VersionTree({
  versions,
  total,
  operations,
  selectedId,
  newestId,
  onSelect,
}: {
  versions: VersionSummary[];
  total: number;
  operations: Operation[];
  selectedId: string;
  newestId: string | null;
  onSelect(id: string): void;
}) {
  const rows = useMemo(() => buildTree(versions), [versions]);
  const opById = useMemo(() => new Map(operations.map((o) => [o.id, o])), [operations]);

  return (
    <div className="space-y-2">
      <ul aria-label="Versions" className="space-y-0.5">
        {rows.map(({ version: v, number, depth, branchStart }) => {
          const op = v.operation_id ? opById.get(v.operation_id) : undefined;
          const selected = v.id === selectedId;
          const Icon = op ? OP_ICON[op.kind] : FileText;
          const place = placeTag(v);
          const cost = v.actor === "ai" ? formatCost(op?.estimated_cost_usd) : null;
          return (
            <li key={v.id} style={{ marginLeft: depth * 14 }} className={cn(depth > 0 && "border-l border-border pl-2")}>
              <button
                type="button"
                onClick={() => onSelect(v.id)}
                aria-current={selected ? "true" : undefined}
                className={cn(
                  "w-full rounded-lg px-2.5 py-2 text-left transition-colors",
                  selected ? "clay text-ink" : "text-ink-body hover:bg-surface-muted",
                )}
              >
                <span className="flex items-baseline gap-2">
                  <span className="font-mono text-[12px] text-ink-muted">v{number}</span>
                  <span className={cn("min-w-0 flex-1 truncate text-[13.5px]", selected && "font-semibold")}>{v.label}</span>
                  {v.id === newestId && <span className="type-meta shrink-0">newest</span>}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[12px] text-ink-secondary">
                  <span className="inline-flex items-center gap-1">
                    <Icon aria-hidden className="size-3.5" />
                    {op ? OPERATION_LABEL[op.kind] : "Original"}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    {v.actor === "ai" ? <Bot aria-hidden className="size-3.5" /> : <User aria-hidden className="size-3.5" />}
                    {v.actor === "ai" ? "AI proposal" : "Person"}
                  </span>
                  {place && <span className="font-mono text-[11.5px]">{place}</span>}
                  <span title={v.created_at}>{formatRelative(v.created_at)}</span>
                  {cost && <span>est. {cost.replace("about ", "")}</span>}
                </span>
                {op && <span className="mt-1 line-clamp-2 block text-[12.5px] leading-snug text-ink-secondary">{op.reason}</span>}
                {branchStart && <span className="sr-only">Starts a branch.</span>}
              </button>
            </li>
          );
        })}
      </ul>
      {total > versions.length && (
        <p className="type-meta">
          Showing {versions.length} of {total} versions.
        </p>
      )}
    </div>
  );
}
