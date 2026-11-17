"""PDF export: Indic transliteration, Latin-1 folding, and a smoke test that the PDF is real, titled, and deterministic."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.schemas.proof import SECTION_MODELS, AssemblyInfo, MissingSection, ProofReport
from app.services.proof_pdf import latinize, to_pdf, transliterate
from app.services.proof_render import report_blocks, to_markdown
from app.services.proof_sections import KIND_LEGEND, LEGAL_NOTICE, NOT_IN_BUILD, ordered_specs


def minimal_report(title: str = "Pongal launch proof", *, mode: str = "live") -> ProofReport:
    sections = [
        SECTION_MODELS[spec.id](id=spec.id, title=spec.title, status="missing", missing_reason=NOT_IN_BUILD, kind_labels=[], content=None)  # type: ignore[call-arg]
        for spec in ordered_specs()
    ]
    return ProofReport(
        id=uuid4(), project_id=uuid4(), campaign_id=uuid4(), workspace_id=uuid4(), campaign_version_id=uuid4(), version_number=3,
        title=title, status="partial", mode=mode, content_sha256="0" * 64,  # type: ignore[arg-type]
        created_at=datetime(2026, 11, 17, 12, 0, tzinfo=UTC), schema_version="proof-report-v2", generated_by=None,
        target_region_codes=["IN-TN"], sections=sections,  # type: ignore[arg-type]
        missing_sections=[MissingSection(id=s.id, title=s.title, reason=NOT_IN_BUILD) for s in sections],  # type: ignore[arg-type]
        referenced_claim_ids=[], referenced_conflict_ids=[], kind_legend=KIND_LEGEND, legal_notice=LEGAL_NOTICE,
        assembly=AssemblyInfo(method="deterministic", model_called=False, registry_version="proof-sections-v1", section_ids=[s.id for s in sections]),
    )


@pytest.mark.parametrize(("text", "expected", "script"), [
    ("नमस्ते", "namaste", "Devanagari"),
    ("पोंगल", "pomgala", "Devanagari"),  # anusvara is written m; a final consonant keeps its inherent a
    ("தமிழ்", "tamizh", "Tamil"),
    ("മലയാളം", "malayaalam", "Malayalam"),
    ("বাংলা", "baamlaa", "Bengali"),
    ("१२३", "123", "Devanagari"),
])
def test_indic_text_is_transliterated_from_unicode_character_names(text: str, expected: str, script: str) -> None:
    out, scripts = transliterate(text)
    assert (out, scripts) == (expected, {script})


def test_text_outside_the_indic_blocks_passes_through_and_mixed_text_keeps_its_latin() -> None:
    assert transliterate("Pongal 2026: harvest") == ("Pongal 2026: harvest", set())
    out, scripts = transliterate("Festival பொங்கல் starts")
    assert out.startswith("Festival ") and out.endswith(" starts") and scripts == {"Tamil"} and "ப" not in out


def test_latinize_keeps_what_the_standard_font_draws_and_folds_the_rest() -> None:
    assert latinize("Café, — “quoted” €5 •")[0] == "Café, — “quoted” €5 •"  # all in Windows-1252
    assert latinize("Pūrṇa")[0] == "Purna"  # a base letter with its mark dropped
    assert latinize("Ωmega 日本")[0] == "?mega ??"
    assert latinize("பொங்கல்")[1] == {"Tamil"} and not any(ord(c) > 0x7F for c in latinize("பொங்கல் नमस्ते")[0])
    assert latinize("tab\there\nnewline\x00\x07")[0] == "tab\there\nnewline"  # control characters are dropped


def test_the_pdf_is_a_real_titled_deterministic_document() -> None:
    report = minimal_report()
    pdf, notices = to_pdf(report, report_blocks(report), compress=False)
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF") and len(pdf) > 3000 and notices == []
    assert b"Pongal launch proof" in pdf  # the title, in the content and in the document info
    assert b"Not included: not available in this build." in pdf and b"Not legal clearance." in pdf
    again, _ = to_pdf(report, report_blocks(report), compress=False)
    assert again == pdf  # equal reports give equal bytes
    compressed, _ = to_pdf(report, report_blocks(report))
    assert compressed.startswith(b"%PDF-") and len(compressed) < len(pdf)


def test_indic_text_in_a_report_is_replaced_in_the_pdf_and_the_pdf_says_so() -> None:
    report = minimal_report("பொங்கல் launch")
    pdf, notices = to_pdf(report, report_blocks(report), compress=False)
    assert len(notices) == 1 and "Tamil" in notices[0] and "transliteration" in notices[0] and "JSON and Markdown" in notices[0]
    assert "பொங்கல்".encode() not in pdf and b"pongkal launch" in pdf and b"approximate Latin transliteration" in pdf
    assert "பொங்கல்" in to_markdown(report_blocks(report))  # Markdown keeps the original text


def test_a_demo_report_carries_the_demo_banner_in_every_format() -> None:
    report = minimal_report(mode="demo")
    markdown = to_markdown(report_blocks(report))
    assert "DEMO DATA: fixture results, not live research." in markdown and "not legal clearance" in markdown.lower()
    assert b"DEMO DATA: fixture results, not live research." in to_pdf(report, report_blocks(report), compress=False)[0]
