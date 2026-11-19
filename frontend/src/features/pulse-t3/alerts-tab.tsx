"use client";

import { Bell, CircleDollarSign, Repeat, Scale, TrendingDown, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCapabilities } from "@/features/launch/api";
import { alertEvidence, alertHeadline, formatSpan, regionLabel, shortVersion, type PulseAlert } from "@/features/pulse/logic";
import { Section, Segmented } from "@/features/pulse/ui";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useAlertInbox, useEvaluateAlerts, useTransitionAlert } from "./api";
import { AlertRules } from "./alert-rules";
import {
  ALERT_TYPES, alertFigures, EVENT_LABEL, evaluationLine, eventActor, RESOLUTION_LABEL, STATUS_LABEL, TRIGGER_LABEL, type AlertRecord, type AlertRuleType,
} from "./logic";
import { PulseTabPage } from "./ui";

type NotRead = components["schemas"]["AlertNotRead"];
type Filter = "open" | "acknowledged" | "resolved" | "all";

const TYPE_ICON: Record<AlertRuleType, LucideIcon> = { ctr_drop: TrendingDown, frequency_fatigue: Repeat, cost_spike: CircleDollarSign, prediction_miss: Scale };

function StatusTag({ status }: { status: AlertRecord["status"] }) {
  const tone =
    status === "open" ? "border-warning/30 bg-warning-soft text-warning" : status === "acknowledged" ? "border-info/25 bg-info-soft text-info" : "border-border bg-surface-muted text-ink-secondary";
  return <Tag className={tone}>{STATUS_LABEL[status]}</Tag>;
}

function headline(a: AlertRecord): { head: string; evidence: string } {
  const region = a.region_name;
  if (a.alert_type === "prediction_miss") {
    return { head: `This version's result is ${a.observed_value} ranks from what was predicted for ${region}`, evidence: a.comparison };
  }
  const asPulse = a as unknown as PulseAlert;
  return { head: alertHeadline(asPulse, region), evidence: alertEvidence(asPulse) };
}

function Transition({ campaignId, alert, onClose, action }: { campaignId: string; alert: AlertRecord; action: "acknowledge" | "resolve" | "reopen"; onClose: () => void }) {
  const move = useTransitionAlert(campaignId);
  const [note, setNote] = useState("");
  const verb = { acknowledge: "Acknowledge", resolve: "Resolve", reopen: "Reopen" }[action];
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        move.mutate(
          { alertId: alert.id, action, note: note.trim() || null },
          {
            onSuccess: () => {
              toast.success(`${verb === "Acknowledge" ? "Acknowledged" : verb === "Resolve" ? "Resolved" : "Reopened"}.`);
              onClose();
            },
            onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not change the alert."),
          },
        );
      }}
    >
      <div className="min-w-56 flex-1 space-y-1">
        <label htmlFor={`note-${alert.id}`} className="block text-[12px] font-medium text-ink-secondary">
          Note (optional)
        </label>
        <Input id={`note-${alert.id}`} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="What you did or decided" />
      </div>
      <Button type="submit" size="sm" disabled={move.isPending}>
        {verb}
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={onClose}>
        Cancel
      </Button>
    </form>
  );
}

function AlertRow({ campaignId, alert, canAct }: { campaignId: string; alert: AlertRecord; canAct: boolean }) {
  const [action, setAction] = useState<"acknowledge" | "resolve" | "reopen" | null>(null);
  const Icon = TYPE_ICON[alert.alert_type];
  const { head, evidence } = headline(alert);
  return (
    <li className="space-y-2 px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Tag className="border-border bg-surface-muted text-ink" title={ALERT_TYPES[alert.alert_type].rule}>
          <Icon aria-hidden />
          {ALERT_TYPES[alert.alert_type].label}
        </Tag>
        <p className="text-[13px] text-ink-body">
          <span className="font-medium text-ink">{alert.region_name}</span> · <span title={alert.version_label}>{shortVersion(alert.version_label)}</span>
        </p>
        <StatusTag status={alert.status} />
        <p className="type-meta sm:ml-auto" title={formatDateTime(alert.opened_at)}>
          Opened {formatRelative(alert.opened_at)}
        </p>
      </div>
      <div className="space-y-0.5">
        <p className="text-[14px] font-semibold text-ink">{head}</p>
        <p className="text-[13px] text-ink-secondary">{evidence}</p>
      </div>
      <p className="type-meta">
        Rule: {alert.rule_name} · Window {formatSpan(alert.window_from, alert.window_to)} · {alertFigures(alert)}
      </p>
      <p className="text-[13px] text-ink-body">
        <span className="font-medium text-ink">Suggested action: </span>
        {alert.suggested_action}
      </p>
      {alert.status === "resolved" && alert.resolution && <p className="text-[12.5px] text-ink-secondary">{RESOLUTION_LABEL[alert.resolution] ?? alert.resolution}.</p>}
      {action ? (
        <Transition campaignId={campaignId} alert={alert} action={action} onClose={() => setAction(null)} />
      ) : (
        canAct && (
          <div className="flex flex-wrap gap-2">
            {alert.status === "open" && (
              <Button variant="outline" size="sm" onClick={() => setAction("acknowledge")}>
                Acknowledge
              </Button>
            )}
            {alert.status !== "resolved" && (
              <Button variant="outline" size="sm" onClick={() => setAction("resolve")}>
                Resolve
              </Button>
            )}
            {alert.status === "resolved" && (
              <Button variant="outline" size="sm" onClick={() => setAction("reopen")}>
                Reopen
              </Button>
            )}
          </div>
        )
      )}
      <details className="text-[12.5px]">
        <summary className="cursor-pointer text-ink-secondary hover:text-ink">History ({alert.events.length})</summary>
        <ol className="mt-1.5 space-y-1 border-l border-border pl-3">
          {alert.events.map((e, i) => (
            <li key={i} className="text-ink-body">
              <span className="font-medium text-ink">{EVENT_LABEL[e.kind]}</span> by {eventActor(e)}, {formatDateTime(e.at)}
              {e.note ? <span className="block text-ink-secondary">{e.note}</span> : null}
            </li>
          ))}
        </ol>
      </details>
    </li>
  );
}

/** Alerts (feature 45): the campaign's saved rules, run in code over the Pulse series; alerts stay in the app with a status and a history. */
export function AlertsTab({ campaignId }: { campaignId: string }) {
  const inbox = useAlertInbox(campaignId);
  const evaluate = useEvaluateAlerts(campaignId);
  const caps = useCapabilities();
  const [filter, setFilter] = useState<Filter>("open");
  const [notRead, setNotRead] = useState<NotRead[]>([]);
  const data = inbox.data;
  const shown = (data?.items ?? []).filter((a) => filter === "all" || a.status === filter);
  const last = data?.evaluations[0];

  const run = () =>
    evaluate.mutate(undefined, {
      onSuccess: (r) => {
        setNotRead(r.not_read);
        toast.success(`Rules evaluated: ${evaluationLine(r.evaluation)}.`);
      },
      onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not evaluate the rules."),
    });

  return (
    <PulseTabPage>
      <Section id="alerts-inbox" title="Alerts" meta={last ? <span>Last evaluated {formatRelative(last.evaluated_at)}</span> : undefined}>
        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <div className="space-y-1">
            <p className="text-[12px] font-medium text-ink-secondary">Show</p>
            <Segmented
              label="Alert status"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "open", label: `Open${data ? ` ${data.open}` : ""}` },
                { value: "acknowledged", label: `Acknowledged${data ? ` ${data.acknowledged}` : ""}` },
                { value: "resolved", label: `Resolved${data ? ` ${data.resolved}` : ""}` },
                { value: "all", label: "All" },
              ]}
            />
          </div>
          <Button variant="outline" size="sm" disabled={!caps.canCompute || evaluate.isPending} onClick={run} title={caps.reason ?? undefined}>
            <Bell aria-hidden />
            {evaluate.isPending ? "Evaluating…" : "Evaluate the rules now"}
          </Button>
        </div>
        {last && (
          <p className="type-ledger text-[12.5px] text-ink-secondary" aria-live="polite">
            Last run, {TRIGGER_LABEL[last.trigger]}: {evaluationLine(last)}.
          </p>
        )}
        {inbox.error && !data ? (
          <ErrorState error={inbox.error} onRetry={() => void inbox.refetch()} />
        ) : !data ? (
          <LoadingState label="Reading the alerts…" />
        ) : shown.length === 0 ? (
          <EmptyState
            title={filter === "open" ? "No open alerts" : filter === "all" ? "No alerts yet" : `No ${filter} alerts`}
            description={
              data.evaluations.length === 0
                ? "No rule has run yet. Add rules below, then evaluate them; they also run on every data refresh and on the schedule."
                : "Every rule was evaluated and none is firing in this view. A rule that cannot read a version and region says so below instead of staying silent."
            }
          />
        ) : (
          <ul className={cn("ledger-rules rounded-card border border-border bg-surface transition-opacity", inbox.isFetching && "opacity-80")}>
            {shown.map((a) => (
              <AlertRow key={a.id} campaignId={campaignId} alert={a} canAct={caps.canCompute} />
            ))}
          </ul>
        )}
        {notRead.length > 0 && (
          <div className="rounded-lg border border-border bg-surface-muted px-3.5 py-2.5">
            <p className="text-[12.5px] font-semibold text-ink">Not evaluated</p>
            <p className="text-[12.5px] text-ink-secondary">A rule that cannot read a version and region is listed here with its reason. It is not read as &quot;no alert&quot;, and an alert already open there stays open.</p>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-body marker:text-ink-secondary">
              {notRead.map((n, i) => (
                <li key={i}>
                  {n.rule_name}: {regionLabel(n.region_code)}, {shortVersion(n.version_label)}. {n.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
        {data && data.evaluations.length > 0 && (
          <details className="text-[12.5px]">
            <summary className="cursor-pointer text-ink-secondary hover:text-ink">Evaluation history ({data.evaluations.length})</summary>
            <ul className="mt-1.5 space-y-1">
              {data.evaluations.map((e) => (
                <li key={e.id} className="type-ledger text-ink-body">
                  <span className="font-medium text-ink">{formatDateTime(e.evaluated_at)}</span>, {TRIGGER_LABEL[e.trigger]}
                  {e.period_key ? ` (period ${e.period_key})` : ""}: {evaluationLine(e)}.
                </li>
              ))}
            </ul>
          </details>
        )}
      </Section>

      <Section id="alert-rules" title="Alert rules" meta={<span>Saved with the campaign. Nothing is emailed or sent.</span>}>
        <AlertRules campaignId={campaignId} />
      </Section>
    </PulseTabPage>
  );
}
