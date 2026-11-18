"use client";

import { RotateCcw } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { components } from "@/lib/api/schema";

import { ALL_REGIONS, DEFAULT_FILTERS, type Filters } from "./api";
import { platformLabel, rangePresets, regionLabel, sameRange, sortRegions, type Platform } from "./logic";
import { Segmented, SelectField } from "./ui";

type Status = components["schemas"]["DatasetStatus"];

/**
 * One row of filters above everything it scopes: the regional ledger, the trend, the version comparison. (The alert preview
 * has its own thresholds, which is a different kind of control, and says so.)
 */
export function FilterRow({ status, value, onChange, names }: { status: Status; value: Filters; onChange: (f: Filters) => void; names: Record<string, string> }) {
  const fromId = useId();
  const toId = useId();
  const presets = rangePresets(status);
  const activePreset = presets.find((p) => sameRange(p.range, value.range))?.key ?? null;
  const first = status.date_from ?? undefined;
  const last = status.date_to ?? undefined;
  const dirty = JSON.stringify(value) !== JSON.stringify(DEFAULT_FILTERS);
  return (
    <div role="group" aria-label="Filters for the sections below" className="flex flex-wrap items-end gap-x-5 gap-y-3 border-b border-border pb-4">
      <div className="space-y-1">
        <p className="text-[12px] font-medium text-ink-secondary">Period</p>
        <Segmented
          label="Period"
          value={activePreset}
          onChange={(k) => onChange({ ...value, range: presets.find((p) => p.key === k)?.range ?? value.range })}
          options={presets.map((p) => ({ value: p.key, label: p.label }))}
        />
      </div>
      <div className="flex items-end gap-2">
        <div className="space-y-1">
          <label htmlFor={fromId} className="block text-[12px] font-medium text-ink-secondary">
            From
          </label>
          <Input
            id={fromId}
            type="date"
            min={first}
            max={value.range.to ?? last}
            value={value.range.from ?? first ?? ""}
            onChange={(e) => e.target.value && onChange({ ...value, range: { ...value.range, from: e.target.value === first ? null : e.target.value } })}
            className="w-[9.25rem] text-[13px] md:text-[13px]"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={toId} className="block text-[12px] font-medium text-ink-secondary">
            To
          </label>
          <Input
            id={toId}
            type="date"
            min={value.range.from ?? first}
            max={last}
            value={value.range.to ?? last ?? ""}
            onChange={(e) => e.target.value && onChange({ ...value, range: { ...value.range, to: e.target.value === last ? null : e.target.value } })}
            className="w-[9.25rem] text-[13px] md:text-[13px]"
          />
        </div>
      </div>
      <div className="space-y-1">
        <p className="text-[12px] font-medium text-ink-secondary">Platform</p>
        <Segmented
          label="Platform"
          value={value.platform}
          onChange={(p) => onChange({ ...value, platform: p })}
          options={[{ value: "all" as Platform | "all", label: "All" }, ...status.platforms.map((p) => ({ value: p as Platform | "all", label: platformLabel(p) }))]}
        />
      </div>
      <SelectField
        label="Region"
        value={value.region}
        onChange={(region) => onChange({ ...value, region })}
        className="w-44"
        options={[{ value: ALL_REGIONS, label: "All regions" }, ...sortRegions(status.regions, (r) => r).map((r) => ({ value: r, label: regionLabel(r, names) }))]}
      />
      {dirty && (
        <Button variant="ghost" size="sm" onClick={() => onChange(DEFAULT_FILTERS)} className="text-ink-secondary">
          <RotateCcw aria-hidden />
          Reset filters
        </Button>
      )}
    </div>
  );
}
