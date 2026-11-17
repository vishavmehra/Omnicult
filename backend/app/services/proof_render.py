"""One document model for every export of a Proof Report.

`report_blocks` turns a stored report into simple blocks (headings, paragraphs, notes, bullets, tables). Markdown and
PDF both render those blocks, so the two exports cannot drift apart. A section a stream adds later renders through
`generic_blocks` until it gets its own layout here. Markdown is produced at request time and never stored in git.
"""

import re
from typing import Any

from app.schemas.proof import ProofReport
from app.services.reports import DEMO_BANNER, _cell

Block = tuple  # ("h1"|"h2"|"h3"|"p"|"note", text) | ("ul", [text]) | ("table", [header], [[cell]])

NOT_LEGAL = "Not legal clearance."


def _t(value: Any) -> str:
    """Plain text for a cell or line: the export reads em dashes as commas, like the app does."""
    text = "n/a" if value is None else str(value)
    return re.sub(r" *— *", ", ", text.replace("\n", " ")).strip()


def _date(value: Any) -> str:
    """The calendar day of an ISO timestamp string (section content is JSON) or a datetime."""
    return "n/a" if value is None else (value if isinstance(value, str) else value.isoformat())[:10]


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _brief(c: dict) -> list[Block]:
    version = c["current_version"]
    copy = version["content"]
    rows = [[label, _t(copy.get(key))] for label, key in (("Headline", "headline"), ("Body", "body"), ("Call to action", "call_to_action")) if copy.get(key)]
    brand = c["brand"]
    return [
        ("ul", [
            f"Campaign: {_t(c['name'])} ({c['campaign_type']})", f"Objective: {_t(c['objective'])}",
            "Markets: " + (", ".join(_t(m["display_name"]) + (f" ({m['region_code']})" if m.get("region_code") else "") for m in c["target_markets"]) or "none set"),
            f"Content version {version['version_number']} of {c['version_count']} (id {version['id']})",
            f"Brand: {_t(brand['name'])}; voice: {', '.join(brand['voice']) or 'n/a'}; protected terms: {', '.join(brand['protected_terms']) or 'none'}",
        ]),
        ("table", ["Copy", "Text"], rows),
    ]


def _regions(c: dict) -> list[Block]:
    blocks: list[Block] = [("table", ["Code", "Region", "Primary language", "Script", "Languages"], [
        [r["code"], _t(r["name"]), _t(r["primary_language"]), _t(r["primary_script"]), ", ".join(f"{l['name']} ({l['role']})" for l in r["languages"])]
        for r in c["regions"]])]
    if c["unknown_codes"]:
        blocks.append(("note", "Not reported, no such region: " + ", ".join(c["unknown_codes"]) + "."))
    return blocks


def _claims(c: dict) -> list[Block]:
    blocks: list[Block] = []
    for region in c["regions"]:
        rows, gaps = [], []
        for category in region["categories"]:
            if not category["claims"]:
                gaps.append(category["category"])
            for claim in category["claims"]:
                flags = [f for f, on in (("stale", claim["stale"]), ("in conflict", bool(claim["conflict_ids"]))) if on]
                sources = "; ".join(_t(s["title"] or s["source_type"]) for s in claim["sources"][:3]) or "none"
                rows.append([
                    category["category"], _t(claim["value_text"]), claim["kind"], claim["effective_confidence"],
                    f"{len(claim['sources'])}: {sources}", _date(claim["retrieved_at"]), ", ".join(flags) or "none"])
        blocks += [("h3", f"{region['region_name']} ({region['region_code']}): {_plural(region['claim_count'], 'claim')}"),
                   ("table", ["Category", "Statement", "Kind", "Confidence", "Sources", "Retrieved", "Flags"], rows)]
        if gaps:
            blocks.append(("p", "No claims yet: " + ", ".join(gaps) + "."))
    return blocks


def _meter(c: dict) -> list[Block]:
    return [("table", ["Region", "Strength", "Claims", "Supported", "Categories", "Sources", "Open conflicts", "Stale", "Why"], [
        [f"{m['region_name']} ({m['region_code']})", m["strength"], m["claims"], m["supported_claims"],
         f"{m['categories_covered']}/{m['categories_total']}", m["sources"], m["open_conflicts"], m["stale_claims"],
         _t(" ".join(m["strength_reasons"]) or "none")] for m in c["meters"]])]


def _conflicts(c: dict) -> list[Block]:
    def line(x: dict) -> str:
        used = x["side_a"] if x["current_selection"] == "a" else x["side_b"]
        decisions = "; ".join(f"{d['decision']} on {_date(d['decided_at'])}" + (f" ({_t(d['note'])})" if d["note"] else "") for d in x["decisions"])
        return (f"[{x['status']}] {_t(x['region_code'])}: {_t(x['reason'])} In use: {_t(used['value_text'])} ({x['selection_reason']}) "
                f"A: {_t(x['side_a']['value_text'])} ({x['side_a']['kind']}, {x['side_a']['confidence']}). "
                f"B: {_t(x['side_b']['value_text'])} ({x['side_b']['kind']}, {x['side_b']['confidence']}). "
                f"Decisions: {decisions or 'none yet'}.")

    note = [("note", "Some regions have more conflicts than this report carries.")] if c["truncated"] else []
    return [("h3", f"Open ({len(c['open'])})"), ("ul", [line(x) for x in c["open"]] or ["None."]),
            ("h3", f"Resolved ({len(c['resolved'])})"), ("ul", [line(x) for x in c["resolved"]] or ["None."])] + note


def _history(c: dict) -> list[Block]:
    t = c["totals"]
    rows = [[
        r["operation"], r["status"], ", ".join(r["models"]) or "n/a", ", ".join(r["prompt_versions"]) or "n/a",
        f"{r['input_tokens']}/{r['output_tokens']}", "n/a" if r["estimated_cost_usd"] is None else f"{r['estimated_cost_usd']:.4f}",
        "n/a" if r["duration_ms"] is None else f"{r['duration_ms']} ms", _t((r["error"] or {}).get("message", "none"))] for r in c["runs"]]
    return [
        ("p", f"{_plural(t['runs'], 'run')}. Tokens in/out: {t['input_tokens']}/{t['output_tokens']}. Estimated cost: {t['estimated_cost_usd']:.4f} USD "
              f"(an estimate, not an invoice; {_plural(t['runs_without_cost'], 'run')} with no recorded cost)."),
        ("table", ["Operation", "Status", "Models", "Prompt versions", "Tokens in/out", "Est. cost USD", "Duration", "Error"], rows),
    ] + ([("note", f"Showing the newest {len(c['runs'])} of {t['runs']} runs.")] if c["truncated"] else [])


def _limitations(c: dict) -> list[Block]:
    return [("ul", [_t(x) for x in c["items"]])]


LAYOUTS = {
    "campaign_brief": _brief, "target_regions": _regions, "region_claims": _claims, "evidence_meter": _meter,
    "conflicts": _conflicts, "run_history": _history, "limitations": _limitations,
}


def generic_blocks(content: Any, *, limit: int = 200) -> list[Block]:
    """Fallback layout for a section without its own: every leaf value as a `path: value` bullet."""
    lines: list[str] = []

    def walk(node: Any, path: str) -> None:
        if len(lines) >= limit:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        else:
            lines.append(f"{path}: {_t(node)}")

    walk(content, "")
    return [("ul", lines or ["Empty."])] + ([("note", f"Showing the first {limit} values.")] if len(lines) >= limit else [])


def report_blocks(report: ProofReport) -> list[Block]:
    out: list[Block] = [("h1", report.title)]
    if report.mode == "demo":
        out.append(("note", DEMO_BANNER))
    out += [
        ("note", report.legal_notice),
        ("p", f"Report version {report.version_number}, {report.status}, {report.mode} mode, generated {report.created_at.isoformat()}. "
              f"Campaign content version {report.campaign_version_id}. Regions: {', '.join(report.target_region_codes) or 'none'}. "
              "Assembled deterministically from stored records; no model was called."),
        ("h2", "How to read this report"),
        ("table", ["Kind", "Meaning"], [[k.kind, _t(k.applies_to)] for k in report.kind_legend]),
    ]
    for section in report.sections:
        out.append(("h2", section.title))
        if section.status == "missing":
            out.append(("note", f"Not included: {_t(section.missing_reason)}."))
            continue
        out.append(("ul", [f"{k.kind}: {_t(k.applies_to)}" for k in section.kind_labels]))
        content = section.content.model_dump(mode="json")  # type: ignore[union-attr]
        out += LAYOUTS.get(section.id, generic_blocks)(content)
    out += [("h2", "Missing sections"), ("ul", [f"{m.title}: {_t(m.reason)}" for m in report.missing_sections] or ["None."]),
            ("p", f"Content hash {report.content_sha256}. {NOT_LEGAL}")]
    return out


def to_markdown(blocks: list[Block]) -> str:
    lines: list[str] = []
    for block in blocks:
        kind = block[0]
        if kind in ("h1", "h2", "h3"):
            lines += [f"{'#' * int(kind[1])} {_t(block[1])}", ""]
        elif kind == "p":
            lines += [_t(block[1]), ""]
        elif kind == "note":
            lines += [f"> **{_t(block[1])}**", ""]
        elif kind == "ul":
            lines += [f"- {_t(item)}" for item in block[1]] + [""]
        elif kind == "table":
            header, rows = block[1], block[2]
            if not rows:
                lines += ["None.", ""]
                continue
            lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
            lines += ["| " + " | ".join(_cell(x) for x in row) + " |" for row in rows] + [""]
    return "\n".join(lines).rstrip() + "\n"
