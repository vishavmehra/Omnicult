"""Voice Director: the code that validates a model's plan, and the demo fixture that stands in for the model.

Pure tests: no database, no model. The plan is whatever the "model" says; what these tests pin down is what code lets
through (element ids, locks, glossary terms, script, regions and languages, step order) and that the demo fixture answers
only for its own instructions."""

from typing import Any
from uuid import uuid4

import pytest

from app.agents.direct import MAX_STEPS, ChipRef, DirectOut, PlanContext, StepOut, VersionRef, model_view, validate_steps
from app.fixtures import demo_aamod
from app.fixtures.demo_voice import EXAMPLES, NO_FIXTURE, RESPONDERS

ROOT, NEWER = uuid4(), uuid4()
TAMIL = "தீபாவளி என்றால் பலகாரம்!"


def el(id: str, kind: str, value: Any, language: str | None = "ta", script: str | None = "Taml") -> dict[str, Any]:
    return {"id": id, "kind": kind, "value": value, "language": language, "script": script}


ELEMENTS = [
    el("logo", "logo", "brand/logo.svg", None, None),
    el("headline", "headline", TAMIL),
    el("tagline", "tagline", "Every bond, a little sweeter.", "en", "Latn"),
    el("cta", "cta", "இன்றே ஆர்டர் செய்யுங்கள்"),
    el("small", "body", "*நிகர எடை 750 கிராம்."),
]


def context(locked: set[str] | None = None, **over: Any) -> PlanContext:
    fields: dict[str, Any] = {
        "version_id": NEWER, "elements": {e["id"]: e for e in ELEMENTS}, "locked": locked or set(),
        "versions": {"V1": VersionRef(ROOT, 1, "Original", [dict(e, value="x") if e["id"] == "headline" else e for e in ELEMENTS])},
        "chips": {"K1": ChipRef(uuid4(), "cta", "Say it warmer", "replace_text", {"value": "இன்றே ஆர்டர் செய்யுங்கள்!"})},
        "regions": {"IN-TN": ("Tamil Nadu", frozenset({"ta", "en"})), "IN-MH": ("Maharashtra", frozenset({"mr", "en"}))},
        "languages": {"ta": "Tamil", "en": "English", "mr": "Marathi"}, "base_region": "IN-TN",
        "glossary": [{"term": "Aamod", "language": "*", "script": None, "approved_spelling": None, "preferred_translation": None,
                      "pronunciation": None, "protected": True, "never_translate": True, "prohibited_alternatives": [], "notes": None}],
        "protected": ["Aamod"], "prohibited": ["No. 1"],
    }
    return PlanContext(**(fields | over))


def run(*steps: dict[str, Any], ctx: PlanContext | None = None) -> tuple[list[Any], list[str]]:
    return validate_steps([StepOut(rationale="Because.", **s) for s in steps], ctx or context())


def edit(**fields: Any) -> dict[str, Any]:
    return {"kind": "edit_element", **fields}


def test_a_valid_edit_keeps_its_before_and_after_and_a_locked_one_is_refused_with_its_reason() -> None:
    (ok,), _ = run(edit(element_id="headline", new_value="தீபாவளி என்றாலே வீட்டுப் பலகாரம்!"))
    assert ok.status == "proposed" and ok.before == TAMIL and ok.after.startswith("தீபாவளி என்றாலே") and ok.changes_data and ok.needs_confirmation
    (locked,), _ = run(edit(element_id="headline", new_value="வேறு வரி"), ctx=context({"headline"}))
    assert locked.status == "blocked" and locked.blocked.code == "LOCKED" and locked.after is None and locked.before == TAMIL


def test_an_edit_must_keep_protected_terms_avoid_prohibited_ones_and_stay_in_the_script() -> None:
    steps, _ = run(
        edit(element_id="headline", new_value="தீபாவளி என்றாலே பலகாரம்!"),
        edit(element_id="small", new_value="*No. 1 பலகார டின்."),
        edit(element_id="cta", new_value="Order today"),
    )
    assert [s.status for s in steps] == ["proposed", "blocked", "blocked"]
    assert steps[1].blocked.code == "CHECKS_FAILED" and "No. 1" in steps[1].blocked.message
    assert steps[2].blocked.code == "CHECKS_FAILED" and "script" in steps[2].blocked.message.lower()
    kept = context(elements={**{e["id"]: e for e in ELEMENTS}, "headline": el("headline", "headline", "Aamod தீபாவளி பலகாரம்!")})
    (dropped,), _ = run(edit(element_id="headline", new_value="தீபாவளி பலகாரம்!"), ctx=kept)  # the brand name was in the line and may not go
    assert dropped.blocked.code == "CHECKS_FAILED" and "Aamod" in dropped.blocked.message


def test_unknown_references_never_reach_the_plan_as_proposed_steps() -> None:
    steps, _ = run(
        edit(element_id="ghost", new_value="x"), edit(element_id="logo", new_value="x"), {"kind": "apply_chip", "chip": "K7"},
        {"kind": "restore_version", "version": "V4"}, {"kind": "navigate", "workspace": "admin"},
        {"kind": "propose_chips", "element_id": "headline", "region_code": "IN-ZZ"},
    )
    assert [s.blocked.code for s in steps] == ["UNKNOWN", "INVALID", "UNKNOWN", "UNKNOWN", "INVALID", "INVALID"]
    assert all(s.status == "blocked" for s in steps)


def test_a_chip_step_shows_the_text_it_would_write_and_follows_the_lock() -> None:
    swap = ChipRef(uuid4(), "cta", "Name the festival", "swap_reference", {"from_text": "இன்றே", "to_text": "தீபாவளிக்கு முன்"})
    (ok,), _ = run({"kind": "apply_chip", "chip": " k2 "}, ctx=context(chips={"K2": swap}))
    assert ok.status == "proposed" and ok.after == "தீபாவளிக்கு முன் ஆர்டர் செய்யுங்கள்" and ok.chip_id == swap.id and ok.before == "இன்றே ஆர்டர் செய்யுங்கள்"
    gone = ChipRef(swap.id, "cta", "x", "swap_reference", {"from_text": "இல்லை", "to_text": "y"})
    (stale,), _ = run({"kind": "apply_chip", "chip": "K2"}, ctx=context(chips={"K2": gone}))
    assert stale.blocked.code == "INVALID"
    (held,), _ = run({"kind": "apply_chip", "chip": "K1"}, ctx=context({"cta"}))
    assert held.blocked.code == "LOCKED"


def test_locks_in_one_plan_are_seen_by_the_steps_after_them() -> None:
    steps, _ = run(
        {"kind": "unlock_element", "element_id": "headline"}, edit(element_id="headline", new_value="தீபாவளி வாழ்த்துகள்!"),
        {"kind": "lock_element", "element_id": "headline"}, edit(element_id="cta", new_value="இப்போதே வாங்குங்கள்"), ctx=context({"headline"}),
    )
    assert [s.status for s in steps] == ["proposed"] * 4
    steps, _ = run({"kind": "lock_element", "element_id": "headline"}, edit(element_id="headline", new_value="வேறு வரி"))
    assert [s.status for s in steps] == ["proposed", "blocked"] and steps[1].blocked.code == "LOCKED"
    steps, _ = run({"kind": "unlock_element", "element_id": "headline"}, {"kind": "lock_element", "element_id": "headline"},
                   {"kind": "lock_element", "element_id": "headline"})
    assert [s.status for s in steps] == ["blocked", "proposed", "blocked"]  # not locked / lock it / already locked


def test_restoring_would_not_change_a_locked_element_or_the_version_the_plan_starts_from() -> None:
    (ok,), _ = run({"kind": "restore_version", "version": "V1"})
    assert ok.status == "proposed" and ok.version_id == ROOT and "v1" in ok.title
    (held,), _ = run({"kind": "restore_version", "version": "V1"}, ctx=context({"headline"}))  # V1 differs in the headline
    assert held.blocked.code == "LOCKED" and "headline" in held.blocked.message
    (same,), _ = run({"kind": "restore_version", "version": "V1"}, ctx=context(version_id=ROOT))
    assert same.blocked.code == "INVALID"


def test_a_transcreation_takes_the_listed_languages_and_unlocked_text_and_must_come_last() -> None:
    (ok,), _ = run({"kind": "transcreate", "region_code": "IN-MH", "language": "mr"}, ctx=context({"headline"}))
    assert ok.status == "proposed" and ok.element_ids == ["tagline", "cta", "small"] and ok.uses_model and ok.changes_data  # default: every unlocked text line
    bad, _ = run(
        {"kind": "transcreate", "region_code": "IN-MH", "language": "ta"}, {"kind": "transcreate", "region_code": "IN-ZZ", "language": "mr"},
        {"kind": "transcreate", "region_code": "IN-MH", "language": "xx"}, {"kind": "transcreate", "region_code": "IN-MH", "language": "mr", "element_ids": ["logo"]},
        {"kind": "transcreate", "region_code": "IN-MH", "language": "mr", "element_ids": ["headline"]},
    )
    assert [s.blocked.code for s in bad[:4]] == ["INVALID"] * 4 and bad[4].status == "proposed"
    (nothing,), _ = run({"kind": "transcreate", "region_code": "IN-MH", "language": "mr"}, ctx=context(locked={"headline", "tagline", "cta", "small"}))
    assert nothing.blocked.code == "INVALID"
    after, _ = run({"kind": "transcreate", "region_code": "IN-MH", "language": "mr", "element_ids": ["headline"]},
                   {"kind": "lock_element", "element_id": "cta"}, {"kind": "navigate", "workspace": "lab"})
    assert [s.status for s in after] == ["proposed", "blocked", "proposed"] and not after[2].needs_confirmation


def test_repeats_and_surplus_steps_are_dropped_with_a_note() -> None:
    steps, notes = run({"kind": "navigate", "workspace": "lab"}, {"kind": "navigate", "workspace": "lab"})
    assert len(steps) == 1 and "repeated" in notes[0]
    nav = StepOut(kind="navigate", rationale="r", workspace="lab")
    assert len(DirectOut(supported=True, steps=[nav] * MAX_STEPS).steps) == MAX_STEPS
    with pytest.raises(ValueError):
        DirectOut(supported=True, steps=[nav] * (MAX_STEPS + 1))
    with pytest.raises(ValueError):
        StepOut(kind="delete_everything", rationale="r")  # type: ignore[arg-type]  # a tool that does not exist cannot be named
    with pytest.raises(ValueError):
        StepOut(kind="navigate", rationale="r", sudo=True)  # type: ignore[call-arg]  # unknown keys are invalid output


def test_the_schema_shown_to_the_model_requires_every_key_but_validation_stays_lenient() -> None:
    schema = DirectOut.model_json_schema()
    assert schema["required"] == ["supported", "summary", "refusal", "steps"]
    assert schema["$defs"]["StepOut"]["required"] == list(schema["$defs"]["StepOut"]["properties"])  # element_id, new_value, ... too
    from app.llm.google import to_gemini_schema

    sent = to_gemini_schema(schema)
    assert sent["required"] == ["supported", "summary", "refusal", "steps"] and "maxItems" not in repr(sent)  # the API gets the requirement
    assert DirectOut.model_validate({"supported": False}).steps == []  # a refusal may leave keys out
    assert StepOut(kind="navigate", rationale="r").element_id is None  # as may a step


def test_a_supported_plan_without_steps_is_invalid_output_so_the_gateway_repairs_it() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="steps must list at least one step"):
        DirectOut(supported=True, summary="Warm up the headline.", steps=[])
    assert DirectOut(supported=False, refusal="Publishing is not possible.").steps == []


async def test_the_plan_call_carries_the_required_schema_a_bounded_budget_and_its_prompt_version() -> None:
    import json

    from app.agents.direct import MAX_PLAN_TOKENS, PROMPT_VERSION, propose_plan
    from app.llm.gateway import Completion, LLMGateway
    from app.llm.registry import spec_for
    from tests.unit.llm.genai_fakes import settings

    seen = []

    class Provider:
        name = "capture"

        async def complete(self, request):
            seen.append(request)
            return Completion(text=json.dumps({"supported": True, "summary": "Warm it.", "refusal": None,
                                               "steps": [{"kind": "lock_element", "rationale": "Asked.", "element_id": "cta"}]}))

    result = await propose_plan(LLMGateway(settings(), provider=Provider()), stage="planning", view=model_view(context(), "lock the button", "Tamil", 1))
    (request,) = seen
    assert [s.kind for s in result.value.steps] == ["lock_element"] and result.trace.prompt_version == PROMPT_VERSION == "voice-direct-v2"
    assert request.max_tokens == MAX_PLAN_TOKENS + spec_for(request.model).thinking_headroom
    assert '"required":["supported","summary","refusal","steps"]' in request.messages[0]["content"]


def test_the_model_sees_handles_and_text_but_not_the_value_of_non_text_elements() -> None:
    view = model_view(context({"logo"}), "Make it warmer", "Tamil Nadu final", 4)
    assert view["selected_version"] == {"handle": "V4", "label": "Tamil Nadu final", "region_code": "IN-TN"}
    logo = next(e for e in view["elements"] if e["id"] == "logo")
    assert logo["text"] is None and logo["locked"] and next(e for e in view["elements"] if e["id"] == "headline")["text"] == TAMIL
    assert view["existing_chips"][0]["handle"] == "K1" and view["versions"] == [{"handle": "V1", "label": "Original"}]
    assert {r["code"] for r in view["regions"]} == {"IN-TN", "IN-MH"} and "workspaces" in view


# --- the demo fixture --------------------------------------------------------------------------------------------------------


def demo_view(
    instruction: str, *, locked: tuple[str, ...] = ("tagline",), elements: list[dict[str, Any]] | None = None,
    versions: tuple[dict[str, str], ...] = ({"handle": "V1", "label": "Original · Maharashtra (Marathi)"},), region: str | None = "IN-TN",
) -> dict[str, Any]:
    ctx = context(set(locked), elements={e["id"]: e for e in (elements or ELEMENTS)})
    view = model_view(ctx, instruction, "Tamil Nadu", 5)
    view["versions"], view["selected_version"]["region_code"] = list(versions), region
    return view


def ask(instruction: str, **kwargs: Any) -> DirectOut:
    return DirectOut.model_validate(RESPONDERS["voice-direct-v2"](demo_view(instruction, **kwargs)))


def test_every_demo_example_gets_a_plan_that_survives_the_real_validation() -> None:
    (step,), _ = validate_steps(ask("Make the Tamil headline warmer, keep the brand name").steps, context())
    assert step.status == "proposed" and step.after == "தீபாவளி என்றாலே வீட்டுப் பலகாரம்!" and "Aamod" in step.rationale
    assert [s.status for s in validate_steps(ask("Lock the call to action").steps, context())[0]] == ["proposed"]
    (refused,), _ = validate_steps(ask("make the tagline SHORTER!").steps, context({"tagline"}))
    assert refused.status == "blocked" and refused.blocked.code == "LOCKED"  # the locked tagline is refused by code, not by the fixture
    chips = ask("Suggest tweak chips for the delivery line", elements=[el("mh-vid-cta-hook", "cta", "பண்டிகைக்கு முன் வீடு தேடி வரும்")])
    assert chips.steps[0].kind == "propose_chips" and chips.steps[0].region_code == "IN-TN"
    (restore,), _ = validate_steps(ask("Go back to the original").steps, context())
    assert restore.status == "proposed" and restore.version_id == ROOT
    (nav,), _ = validate_steps(ask("Open the Launch Room").steps, context())
    assert nav.workspace == "launch" and not nav.needs_confirmation


def test_the_bengali_example_lists_only_lines_the_phrasebook_can_answer() -> None:
    sources = list(demo_aamod.PHRASEBOOK)[:3]
    lines = [el(f"l{i}", "headline", source, "mr", "Deva") for i, source in enumerate(sources)] + [el("l9", "headline", "an unrelated line", "mr", "Deva")]
    step = ask("Adapt this for West Bengal in Bengali", elements=lines, locked=()).steps[0]
    assert (step.kind, step.region_code, step.language, step.element_ids) == ("transcreate", "IN-WB", "bn", ["l0", "l1", "l2"])
    assert ask("Adapt this for West Bengal in Bengali").supported is False  # the Tamil version has no Marathi source lines


def test_anything_else_gets_no_fixture_and_the_examples_that_work_instead_of_an_invented_plan() -> None:
    for instruction in ("Translate everything into Klingon", "open the secret admin page", "Delete the logo"):
        plan = ask(instruction)
        assert not plan.supported and plan.steps == [] and plan.refusal.startswith(NO_FIXTURE)
    assert "demo rewrite" in ask("Make the Kerala headline warmer", elements=[el("h", "headline", "ഒരു വരി", "ml", "Mlym")]).refusal
    refusal = ask("Anything at all").refusal
    assert refusal is not None and len(refusal) <= 400 and all(example in refusal for example in EXAMPLES)
    already = ask("Go back to the original", versions=())
    assert not already.supported and "already on the original" in already.refusal


def test_a_reason_longer_than_asked_is_cut_but_edited_text_is_never_cut() -> None:
    out = DirectOut.model_validate({"supported": True, "summary": "s " * 400, "steps": [{"kind": "navigate", "workspace": "lab", "rationale": "word " * 200}]})
    assert len(out.summary) <= 300 and len(out.steps[0].rationale) <= 300
    with pytest.raises(ValueError):
        StepOut(kind="edit_element", element_id="headline", new_value="x" * 1001, rationale="r")
