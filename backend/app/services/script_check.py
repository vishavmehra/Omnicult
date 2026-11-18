"""Script Check (feature 28): every text element of a version, checked for script and language correctness in code.

Nothing is stored and no model is called: the report is computed on each read from the version, the Brand Glossary, the
brand's term lists and the transcreations in the version's lineage. The checks themselves are `app.studio.scriptcheck`,
which reuses the transcreate checks; this module only gathers what they need and shapes the answer.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db import models as m
from app.db.session import read_session
from app.media import textrender
from app.reference.india import SCRIPT_OF
from app.schemas import studio_t3 as t
from app.schemas.versions import TEXT_KINDS
from app.services import studio_context as ctx
from app.services.runs import brand_of, merge_terms
from app.services.studio_t3_common import anchor_of, scene_timings, text_of
from app.services.versions import campaign_for, node_in
from app.studio import scriptcheck as sc

LIMITATIONS = [
    "Script Check finds spelling and script problems that code can see. It cannot tell whether a word is the right word: that needs a native reader.",
    "Glossary checks use the Brand Glossary as it is now. Its spellings were drafted by the brand team and should be confirmed by native speakers.",
]


async def _lineage(s: Any, campaign_id: UUID, version_id: UUID) -> list[UUID]:
    """The version, its parent, and so on up to the original."""
    rows = (await s.execute(select(m.VersionNode.id, m.VersionNode.parent_id).where(m.VersionNode.campaign_id == campaign_id))).all()
    parent = {row.id: row.parent_id for row in rows}
    chain: list[UUID] = []
    cursor: UUID | None = version_id
    while cursor is not None and cursor not in chain:
        chain.append(cursor)
        cursor = parent.get(cursor)
    return chain


def _back_translation(
    ops: list[m.Operation], chain: list[UUID], element_id: str, value: str
) -> tuple[dict[str, Any], m.Operation, str] | None:
    """The stored line behind an element's wording, walking from the version back to the original: ("current", line, op) when
    the text is still what the line says, ("edited", ...) when it was changed after the transcreation."""
    earlier = None
    for version in chain:
        op = next((o for o in ops if o.result_version_id == version), None)
        line = next((x for x in (op.params.get("lines") or []) if x.get("element_id") == element_id and x.get("passed")), None) if op else None
        if op is None or line is None:
            continue
        if line.get("regional_copy") == value:
            return line, op, "current"
        earlier = earlier or (line, op, "edited")
    return earlier


async def script_report(user_id: UUID, campaign_id: UUID, version_id: UUID) -> t.ScriptReport:
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id)
        node = await node_in(s, campaign, version_id, "version_id")
        elements = list(node.elements)
        languages = {node.language, *(e.get("language") for e in elements)} - {None}
        entries: list[dict[str, Any]] = []
        for language in sorted(languages):
            entries += [e for e in await ctx.glossary_entries(s, project.id, language) if e not in entries]
        if not languages:
            entries = await ctx.glossary_entries(s, project.id, None)
        brand = await brand_of(s, project.id)
        timings = await scene_timings(s, campaign.id, elements)
        chain = await _lineage(s, campaign.id, node.id)
        ops = list((await s.execute(select(m.Operation).where(
            m.Operation.campaign_id == campaign.id, m.Operation.kind == "transcreate", m.Operation.status == "applied",
            m.Operation.result_version_id.in_(chain)))).scalars())
    tone = (node.settings or {}).get("tone") or {}
    context = sc.ScriptContext(
        version_language=node.language, script_of_language=SCRIPT_OF, entries=entries, protected=merge_terms(brand.protected_terms),
        prohibited=list(brand.prohibited_terms), code_mixing=int(tone.get("code_mixing", 50)),
        shaping_scripts=frozenset(textrender.available_scripts()),
    )
    results: list[t.ScriptReportElement] = []
    skipped: list[t.ScriptReportSkipped] = []
    for element in elements:
        if element["kind"] not in TEXT_KINDS:
            continue
        text = text_of(element)
        if text is None:
            skipped.append(t.ScriptReportSkipped(element_id=element["id"], kind=element["kind"], reason=(
                "Audio: its words are checked through the captions and the transcript." if element["kind"] == "voiceover"
                else "No text to check.")))
            continue
        result = sc.check_element(sc.ScriptElement(element["id"], element["kind"], text, element.get("language"), element.get("script")), context)
        anchor = anchor_of(element, timings)
        found = _back_translation(ops, chain, element["id"], text)
        back = None
        if found:
            line, op, state = found
            clean: bool | None = None
            if state == "current":
                bt_issues, clean = sc.back_translation_issues(line["source_text"], text, line["back_translation"], context, result.expected_language)
                result.issues += bt_issues
            back = t.ScriptReportBack(state=state, text=line["back_translation"], clean=clean, operation_id=op.id)  # type: ignore[arg-type]
        issues = [t.ScriptReportIssue(code=i.code, severity=i.severity, message=i.message, start=i.start, end=i.end, excerpt=i.excerpt, anchor=anchor)
                  for i in result.issues]
        status = result.status
        native = status != "ok" or (back is not None and back.state == "edited")
        results.append(t.ScriptReportElement(
            element_id=element["id"], kind=element["kind"], text=text, language=result.expected_language, declared_script=element.get("script"),
            expected_script=result.expected_script, dominant_script=result.dominant_script, shares=result.shares, status=status,  # type: ignore[arg-type]
            native_review_recommended=native, issues=issues,
            terms=[t.ScriptReportTerm(term=f["term"], form=f["form"], pronunciation=f["pronunciation"], protected=f["protected"], start=f["start"], end=f["end"])
                   for f in result.terms_found],
            back_translation=back, anchor=anchor))
    counts = t.ScriptReportCounts(
        ok=sum(r.status == "ok" for r in results), review=sum(r.status == "review" for r in results),
        problem=sum(r.status == "problem" for r in results), issues=sum(len(r.issues) for r in results))
    return t.ScriptReport(
        version_id=node.id, campaign_id=campaign.id, region_code=node.region_code, language=node.language, check_version=sc.CHECK_VERSION,
        shaping_engine=textrender.shaping_engine(), glossary_terms=len({(e["term"], e["language"]) for e in entries}), counts=counts,
        elements=results, skipped=skipped, limitations=LIMITATIONS)
