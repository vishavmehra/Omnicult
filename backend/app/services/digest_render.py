"""Weekly Digest export: the digest as Proof Vault blocks, rendered by the Proof Report exporters.

`digest_blocks` turns a stored digest into the same simple blocks the Proof Report uses (headings, paragraphs, bullets,
tables), so Markdown comes from `proof_render.to_markdown` and PDF from `proof_pdf.to_pdf` and the two cannot drift apart.
The PDF keeps the Proof exporter's behaviour for Indic scripts (approximate Latin transliteration, with a notice); the
Markdown keeps the original text. Nothing here is sent anywhere: an export is a download.
"""

from dataclasses import dataclass
from types import SimpleNamespace

from app.schemas import digest as d
from app.services.digest_build import fmt, fmt_pct
from app.services.proof_pdf import to_pdf
from app.services.proof_render import Block, to_markdown

MIME = {"md": "text/markdown; charset=utf-8", "pdf": "application/pdf"}


@dataclass(frozen=True)
class Exported:
    data: bytes
    media_type: str
    filename: str
    notices: list[str]


def _day(value) -> str:  # noqa: ANN001
    return value.isoformat()[:10]


def _move(unit: str, move: d.DigestMetricMove) -> str:
    return f"{fmt(unit, move.current)} ({fmt_pct(move.delta_pct)})" if move.previous is not None else fmt(unit, move.current)


def digest_blocks(dg: d.Digest) -> list[Block]:
    c, w = dg.content, dg.content.week
    ch = c.what_changed.counts
    out: list[Block] = [
        ("h1", f"Weekly digest: {c.campaign_name}"),
        ("p", f"Week {w.label}, {w.start} to {w.end} (India Standard Time). Revision {dg.revision}, generated {dg.generated_at:%Y-%m-%d %H:%M} UTC. "
              "Computed from stored records."),
    ]
    if dg.narrative is not None:
        n = dg.narrative
        out += [("h2", "Summary (Model interpretation)"), ("p", n.text),
                ("p", f"Written by {n.model_id or n.provider} from the figures in this digest. A hypothesis to judge, not a record.")]

    out += [("h2", "What changed"), ("ul", [
        f"Creative versions created: {ch.creative_versions}; campaign content versions: {ch.content_versions}",
        f"Readiness verdicts computed: {ch.verdicts}; approvals recorded: {ch.approvals}",
        f"Runs: {ch.agent_runs} agent, {ch.audience_runs} audience; Risk Check findings recorded: {ch.risk_findings}",
        f"Evidence conflicts opened: {ch.conflicts_opened}; resolved: {ch.conflicts_resolved}",
    ])]
    if c.what_changed.versions:
        out.append(("table", ["Version", "Region", "By", "Created"], [
            [v.label, v.region_code or "n/a", "AI operation" if v.actor == "ai" else "Person", _day(v.created_at)] for v in c.what_changed.versions]))
    if c.what_changed.verdicts:
        out.append(("table", ["Region", "Version", "Verdict", "Main reason", "Computed"], [
            [f"{v.region_name} ({v.region_code})", v.version_label, v.verdict, v.main_reason, _day(v.computed_at)] for v in c.what_changed.verdicts]))
    if c.what_changed.runs:
        out.append(("table", ["Run", "Status", "Count"], [[r.kind, r.status, r.count] for r in c.what_changed.runs]))
    if c.what_changed.truncated:
        out.append(("p", "Showing the newest records of the week only."))

    p = c.pulse
    out.append(("h2", "Pulse movement and alerts"))
    if not p.available:
        out.append(("p", p.reason or "No Live Pulse movement is available."))
    else:
        compared = f", against {p.previous_from} to {p.previous_to}" if p.previous_from else ", with no earlier period to compare"
        out.append(("p", f"The 7 settled days {p.window_from} to {p.window_to}{compared}. "
                         f"{p.provisional_days_excluded} provisional day(s) left out. Change is shown against the earlier period."))
        header = ["Region", "Version"] + [x.label for x in p.slices[0].metrics] if p.slices else []
        if p.slices:
            out.append(("table", header, [
                [sl.region_name, sl.version_label] + [_move(x.unit, x) for x in sl.metrics] for sl in p.slices]))
        out.append(("ul", [f"{a.region_name}, {a.version_label}: {a.headline}. {a.suggested_action}" for a in p.alerts] or ["No Pulse alert fired."]))
    out.append(("p", p.source))

    cm = c.comments
    out.append(("h2", "Comments"))
    if not cm.available:
        out.append(("p", cm.reason or "No comments are available."))
    else:
        out.append(("p", f"{cm.comments_in_window} comments posted {cm.window_from} to {cm.window_to}: "
                         f"{cm.claim_mentions_in_window} mention the unsourced claim and {cm.cultural_mentions_in_window} name a different festival."))
        if cm.sentiment is not None:
            s = cm.sentiment
            out.append(("p", f"Model reading of those comments (Model interpretation): {s.positive} positive, {s.neutral} neutral, "
                             f"{s.negative} negative, {s.mixed} mixed, {s.unread} unread."))
        if cm.themes:
            out.append(("table", ["Theme (Model interpretation)", "Comments", "Example comment"], [
                [f"{t.label}: {t.summary}", t.comments, t.quote.text if t.quote else "n/a"] for t in cm.themes]))
        if cm.flagged:
            out.append(("table", ["Comment", "Region", "Version", "Matches", "Likes"], [
                [f.text, f.region_code, f.version_label, f.label, f.likes] for f in cm.flagged]))
    out.append(("p", cm.source))

    oi = c.open_items
    out += [("h2", "Open conflicts and issues"),
            ("ul", [f"Evidence conflict{' in ' + x.region_name if x.region_name else ''}: {x.reason}" for x in oi.conflicts]
             + [f"Risk Check ({x.severity}{', blocks Go' if x.blocks_go else ''}) on {x.element_id}: {x.observation}" for x in oi.risk_findings]
             + [f"{x.region_name} is {x.verdict} on {x.version_label}: {x.main_reason}" for x in oi.not_ready] or ["Nothing is open."])]
    if oi.conflicts_total > len(oi.conflicts) or oi.risk_findings_total > len(oi.risk_findings):
        out.append(("p", f"Showing the first records of {oi.conflicts_total} conflicts and {oi.risk_findings_total} findings."))

    out += [("h2", "Next actions"),
            ("ul", [f"P{a.priority}: {a.text} Why: {a.why}" for a in c.next_actions] or ["No action is suggested this week."]),
            ("h2", "Limitations"), ("ul", list(c.limitations))]
    return out


def export_digest(dg: d.Digest, fmt_: str) -> Exported:
    blocks = digest_blocks(dg)
    name = f"omnicult-digest-{dg.content.week.label}.{fmt_}"
    if fmt_ == "md":
        return Exported(to_markdown(blocks).encode("utf-8"), MIME["md"], name, [])
    header = SimpleNamespace(title=f"Weekly digest {dg.content.week.label}: {dg.content.campaign_name}", version_number=dg.revision)
    data, notices = to_pdf(header, blocks)  # type: ignore[arg-type]  (only .title and .version_number are read)
    return Exported(data, MIME["pdf"], name, notices)
