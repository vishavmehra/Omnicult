"use client";

import { Pencil, Plus, Power, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCapabilities } from "@/features/launch/api";
import { useDatasetStatus } from "@/features/pulse/api";
import { regionLabel, shortVersion } from "@/features/pulse/logic";
import { SelectField } from "@/features/pulse/ui";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import { useAlertRules, useDefaultRules, useDeleteRule, useSaveRule } from "./api";
import {
  ALERT_TYPE_ORDER, ALERT_TYPES, describeRule, emptyForm, FIELDS, formFromRule, parseRuleForm, scopeText, type AlertRuleType, type AlertRuleView, type CostMetric, type RuleForm,
} from "./logic";
import { NumberField } from "./ui";

type Create = components["schemas"]["AlertRuleCreate"];

function RuleEditor({ campaignId, rule, type: initialType, onDone }: { campaignId: string; rule: AlertRuleView | null; type: AlertRuleType; onDone: () => void }) {
  const status = useDatasetStatus(campaignId);
  const save = useSaveRule(campaignId);
  const [type, setType] = useState<AlertRuleType>(initialType);
  const [form, setForm] = useState<RuleForm>(rule ? formFromRule(rule) : emptyForm(initialType));
  const [shown, setShown] = useState(false);
  const parsed = parseRuleForm(type, form);
  const errors = parsed.ok ? {} : parsed.errors;
  const regions = status.data?.regions ?? [];
  const versions = status.data?.versions ?? [];

  const choose = (next: AlertRuleType) => {
    setType(next);
    setForm({ ...emptyForm(next), region: form.region, version: form.version });
  };

  const submit = () => {
    setShown(true);
    if (!parsed.ok) return;
    const body: Create = {
      name: form.name.trim(),
      alert_type: type,
      region_code: form.region || null,
      version_label: form.version || null,
      enabled: form.enabled,
      params: parsed.params,
    };
    save.mutate(
      {
        id: rule?.id ?? null,
        create: body,
        update: {
          name: body.name,
          enabled: body.enabled,
          params: body.params,
          region_code: body.region_code,
          version_label: body.version_label,
          clear_region: !form.region,
          clear_version: !form.version,
        },
      },
      {
        onSuccess: () => {
          toast.success(rule ? "Rule changed and evaluated." : "Rule saved and evaluated.");
          onDone();
        },
        onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not save the rule."),
      },
    );
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="space-y-4 rounded-card border border-border-strong/50 bg-surface px-4 py-4"
      aria-label={rule ? `Change the rule ${rule.name}` : "New alert rule"}
    >
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
        {!rule && (
          <SelectField
            label="Alert type"
            value={type}
            onChange={(v) => choose(v as AlertRuleType)}
            options={ALERT_TYPE_ORDER.map((t) => ({ value: t, label: ALERT_TYPES[t].label }))}
          />
        )}
        <div className="space-y-1">
          <label htmlFor="rule-name" className="block text-[12px] font-medium text-ink-secondary">
            Name
          </label>
          <Input id="rule-name" value={form.name} maxLength={60} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-invalid={shown && Boolean(errors.name)} />
          {shown && errors.name && (
            <p role="alert" className="text-[12px] font-medium text-danger">
              {errors.name}
            </p>
          )}
        </div>
        <SelectField
          label="Region"
          value={form.region}
          onChange={(v) => setForm({ ...form, region: v })}
          options={[{ value: "", label: "Every region" }, ...regions.map((r) => ({ value: r, label: regionLabel(r) }))]}
        />
        <SelectField
          label="Version"
          value={form.version}
          onChange={(v) => setForm({ ...form, version: v })}
          options={[{ value: "", label: "Every version" }, ...versions.map((v) => ({ value: v, label: v }))]}
        />
      </div>
      <p className="max-w-[70ch] text-[12.5px] text-ink-secondary">{ALERT_TYPES[type].rule}</p>
      <fieldset className="space-y-3">
        <legend className="sr-only">Thresholds</legend>
        <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
          {ALERT_TYPES[type].fields.map((key) => (
            <NumberField
              key={key}
              label={FIELDS[key].label}
              suffix={FIELDS[key].suffix}
              step={FIELDS[key].step}
              value={form.values[key] ?? ""}
              error={shown ? errors[key] : undefined}
              onChange={(v) => setForm({ ...form, values: { ...form.values, [key]: v } })}
            />
          ))}
          {type === "cost_spike" && (
            <SelectField
              label="Cost to watch"
              value={form.costMetric}
              onChange={(v) => setForm({ ...form, costMetric: v as CostMetric })}
              options={[
                { value: "both", label: "CPM and CPA" },
                { value: "cpm", label: "CPM only" },
                { value: "cpa", label: "CPA only" },
              ]}
            />
          )}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-[13px] text-ink">
        <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} className="size-4 accent-[var(--primary)]" />
        Rule is on
      </label>
      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
        <Button type="submit" size="sm" disabled={save.isPending}>
          {rule ? "Save changes" : "Save rule"}
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <p className="type-meta">Saving evaluates the rules at once. Out-of-range values are not sent.</p>
      </div>
    </form>
  );
}

function RuleRow({ campaignId, rule, canEdit, onEdit }: { campaignId: string; rule: AlertRuleView; canEdit: boolean; onEdit: () => void }) {
  const save = useSaveRule(campaignId);
  const remove = useDeleteRule(campaignId);
  const [confirm, setConfirm] = useState(false);
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Could not change the rule.");
  return (
    <li className="space-y-1.5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="text-[14px] font-semibold text-ink">{rule.name}</p>
        <Tag className="border-border bg-surface-muted text-ink">{ALERT_TYPES[rule.alert_type].label}</Tag>
        <Tag className={rule.enabled ? "border-success/25 bg-success-soft text-success" : "border-border bg-surface-muted text-ink-secondary"}>{rule.enabled ? "On" : "Off"}</Tag>
        {rule.open_alerts > 0 && (
          <span className="type-meta">
            {rule.open_alerts} {rule.open_alerts === 1 ? "alert" : "alerts"} not resolved
          </span>
        )}
        {canEdit && (
          <span className="flex flex-wrap items-center gap-1.5 sm:ml-auto">
            <Button variant="outline" size="sm" onClick={onEdit} aria-label={`Change ${rule.name}`}>
              <Pencil aria-hidden />
              Change
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={save.isPending}
              aria-label={`${rule.enabled ? "Switch off" : "Switch on"} ${rule.name}`}
              onClick={() => save.mutate(
                  { id: rule.id, create: { name: rule.name, alert_type: rule.alert_type, enabled: rule.enabled }, update: { enabled: !rule.enabled, clear_region: false, clear_version: false } },
                  { onError: fail },
                )}
            >
              <Power aria-hidden />
              {rule.enabled ? "Switch off" : "Switch on"}
            </Button>
            {confirm ? (
              <>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(rule.id, { onSuccess: () => toast.success("Rule deleted. Its alerts are resolved and stay in the history."), onError: fail })}
                >
                  Delete the rule
                </Button>
                <Button variant="outline" size="sm" onClick={() => setConfirm(false)}>
                  Keep it
                </Button>
              </>
            ) : (
              <Button variant="outline" size="sm" onClick={() => setConfirm(true)} aria-label={`Delete ${rule.name}`}>
                <Trash2 aria-hidden />
                Delete
              </Button>
            )}
          </span>
        )}
      </div>
      <p className="text-[13px] text-ink-body">{describeRule(rule)}</p>
      <p className="type-meta">
        {scopeText(rule, (code) => regionLabel(code))}
        {rule.version_label ? ` (${shortVersion(rule.version_label)})` : ""}
      </p>
    </li>
  );
}

/** The saved rules of the campaign: add, change, switch off, delete. Each save evaluates at once. */
export function AlertRules({ campaignId }: { campaignId: string }) {
  const rules = useAlertRules(campaignId);
  const defaults = useDefaultRules(campaignId);
  const caps = useCapabilities();
  const [editing, setEditing] = useState<{ rule: AlertRuleView | null; type: AlertRuleType } | null>(null);

  if (rules.error) return <ErrorState error={rules.error} onRetry={() => void rules.refetch()} />;
  if (!rules.data) return <LoadingState label="Reading the alert rules…" />;
  const items = rules.data.items;

  return (
    <div className="space-y-3">
      {items.length === 0 && !editing ? (
        <EmptyState
          title="No alert rules yet"
          description="Rules are saved with the campaign and run over the Pulse series on every refresh, on demand and on the schedule. Start from the four defaults, or write one."
          action={
            caps.canCompute ? (
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={defaults.isPending}
                  onClick={() => defaults.mutate(undefined, { onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not add the rules.") })}
                >
                  Start from the defaults
                </Button>
                <Button variant="outline" size="sm" onClick={() => setEditing({ rule: null, type: "ctr_drop" })}>
                  <Plus aria-hidden />
                  Add a rule
                </Button>
              </div>
            ) : (
              <p className="text-[12.5px] text-ink-secondary">{caps.reason}</p>
            )
          }
        />
      ) : (
        <>
          {items.length > 0 && (
            <ul className="ledger-rules rounded-card border border-border bg-surface">
              {items.map((r) =>
                editing?.rule?.id === r.id ? (
                  <li key={r.id} className="p-3">
                    <RuleEditor campaignId={campaignId} rule={r} type={r.alert_type} onDone={() => setEditing(null)} />
                  </li>
                ) : (
                  <RuleRow key={r.id} campaignId={campaignId} rule={r} canEdit={caps.canCompute} onEdit={() => setEditing({ rule: r, type: r.alert_type })} />
                ),
              )}
            </ul>
          )}
          {!editing && caps.canCompute && (
            <Button variant="outline" size="sm" onClick={() => setEditing({ rule: null, type: "ctr_drop" })}>
              <Plus aria-hidden />
              Add a rule
            </Button>
          )}
          {!caps.canCompute && caps.reason && <p className="text-[12.5px] text-ink-secondary">{caps.reason}</p>}
        </>
      )}
      {editing && !editing.rule && <RuleEditor campaignId={campaignId} rule={null} type={editing.type} onDone={() => setEditing(null)} />}
    </div>
  );
}
