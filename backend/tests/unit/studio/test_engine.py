"""The operation engine: new snapshots, never-mutated sources, lock enforcement for every actor, restore, and diffs."""

import copy

import pytest

from app.studio import engine
from app.studio.engine import Edit, OperationRejected, OpSpec, Snapshot

TONE = {"formality": 80, "code_mixing": 10, "urban_rural": 50, "playfulness": 50, "energy": 50}


def elements() -> list[dict]:
    return [
        {"id": "logo", "kind": "logo", "value": "asset:logo-1", "language": None, "script": None, "bbox": [0.1, 0.1, 0.2, 0.1], "scene_id": None, "locked": False},
        {"id": "tagline", "kind": "tagline", "value": "Light up Diwali", "language": "en", "script": "Latn", "bbox": None, "scene_id": None, "locked": False},
        {"id": "headline", "kind": "headline", "value": "Happy Diwali from Acme", "language": "en", "script": "Latn", "bbox": None, "scene_id": None, "locked": False},
        {"id": "music", "kind": "music", "value": "upbeat", "language": None, "script": None, "bbox": None, "scene_id": "s1", "locked": False},
    ]


def source() -> Snapshot:
    return Snapshot(elements(), "IN-MH", "en", {"tone": None, "generation": None})


def value_of(snap: Snapshot, element_id: str) -> object:
    return next(e["value"] for e in snap.elements if e["id"] == element_id)


@pytest.mark.parametrize("kind", ["manual_edit", "replace_text", "transcreate"])
def test_an_operation_returns_a_new_snapshot_and_never_changes_its_source(kind: str) -> None:
    snap = source()
    before = copy.deepcopy(snap)
    fields = {"value": "नमस्कार", "language": "mr", "script": "Deva"} if kind != "manual_edit" else {"value": "Edited"}
    result = engine.apply_operation(snap, OpSpec(kind, edits=[Edit("headline", fields)]), locked=set())
    assert snap == before  # the source snapshot is untouched
    assert value_of(result.snapshot, "headline") == fields["value"]
    assert result.snapshot.elements is not snap.elements and result.target_ids == ["headline"]
    assert value_of(result.snapshot, "tagline") == "Light up Diwali"  # everything else is carried over


@pytest.mark.parametrize("kind", ["manual_edit", "replace_text", "transcreate", "apply_chip"])
@pytest.mark.parametrize("locked_id", ["tagline", "logo"])
def test_a_locked_element_is_refused_for_every_kind_of_operation(kind: str, locked_id: str) -> None:
    snap = source()
    before = copy.deepcopy(snap)
    edits = [Edit("headline", {"value": "ok"}), Edit(locked_id, {"value": "changed"})]
    with pytest.raises(OperationRejected) as refused:
        engine.apply_operation(snap, OpSpec(kind, edits=edits), locked={locked_id})
    assert refused.value.code == "LOCKED" and refused.value.element_ids == [locked_id]
    assert snap == before  # nothing was applied, not even the unlocked half of the operation


def test_a_locked_element_is_refused_before_its_edit_is_validated() -> None:
    # An invalid value for a locked element is still LOCKED, so no model output can learn anything past a lock.
    with pytest.raises(OperationRejected) as refused:
        engine.apply_operation(source(), OpSpec("replace_text", edits=[Edit("tagline", {"value": ""})]), locked={"tagline"})
    assert refused.value.code == "LOCKED"


def test_a_swap_on_a_locked_element_is_refused_even_when_the_text_is_absent() -> None:
    with pytest.raises(OperationRejected) as refused:
        engine.apply_operation(source(), OpSpec("apply_chip", swap=("tagline", "no such text", "x")), locked={"tagline"})
    assert refused.value.code == "LOCKED"


def test_an_unlocked_element_is_edited_while_the_locked_one_keeps_its_value() -> None:
    snap = source()
    result = engine.apply_operation(snap, OpSpec("replace_text", edits=[Edit("headline", {"value": "Shubh Diwali"})]), locked={"tagline", "logo"})
    assert value_of(result.snapshot, "headline") == "Shubh Diwali"
    assert value_of(result.snapshot, "tagline") == "Light up Diwali" and value_of(result.snapshot, "logo") == "asset:logo-1"


def test_swap_reference_replaces_every_occurrence_and_rejects_absent_text() -> None:
    snap = Snapshot([{**elements()[2], "value": "Diwali sale, Diwali joy"}], None, None, {})
    result = engine.apply_operation(snap, OpSpec("swap_reference", swap=("headline", "Diwali", "Pongal")), locked=set())
    assert value_of(result.snapshot, "headline") == "Pongal sale, Pongal joy"
    with pytest.raises(OperationRejected) as refused:
        engine.apply_operation(snap, OpSpec("swap_reference", swap=("headline", "Holi", "Pongal")), locked=set())
    assert refused.value.code == "INVALID"


@pytest.mark.parametrize("edit", [
    Edit("nope", {"value": "x"}), Edit("headline", {"value": "   "}), Edit("headline", {"kind": "logo"}),
    Edit("music", {"value": "calm"}),  # replace_text applies to text elements only
    Edit("headline", {"value": "Happy Diwali from Acme"}),  # no change at all
])
def test_invalid_replace_text_edits_are_rejected(edit: Edit) -> None:
    with pytest.raises(OperationRejected) as refused:
        engine.apply_operation(source(), OpSpec("replace_text", edits=[edit]), locked=set())
    assert refused.value.code == "INVALID"


def test_an_oversized_value_is_rejected() -> None:
    huge = "x" * (engine.MAX_VALUE_CHARS + 1)
    with pytest.raises(OperationRejected) as refused:
        engine.apply_operation(source(), OpSpec("replace_text", edits=[Edit("headline", {"value": huge})]), locked=set())
    assert refused.value.code == "INVALID"


def test_manual_edit_validates_bbox_and_language() -> None:
    ok = engine.apply_operation(source(), OpSpec("manual_edit", edits=[Edit("logo", {"bbox": [0.2, 0.2, 0.3, 0.1]})]), locked=set())
    assert next(e for e in ok.snapshot.elements if e["id"] == "logo")["bbox"] == [0.2, 0.2, 0.3, 0.1]
    for bad in ({"bbox": [0, 0, 2, 1]}, {"bbox": [0.1]}, {"language": "English"}, {"script": "latin"}):
        with pytest.raises(OperationRejected):
            engine.apply_operation(source(), OpSpec("manual_edit", edits=[Edit("logo", bad)]), locked=set())


def test_settings_operations_change_the_node_settings_not_the_elements() -> None:
    snap = source()
    result = engine.apply_operation(snap, OpSpec("change_setting", region_code="IN-TN", language="ta"), locked={"tagline"})
    assert (result.snapshot.region_code, result.snapshot.language) == ("IN-TN", "ta") and result.snapshot.elements == snap.elements
    shifted = engine.apply_operation(snap, OpSpec("tone_shift", tone=TONE), locked=set())
    assert shifted.snapshot.settings["tone"] == TONE and snap.settings["tone"] is None
    with pytest.raises(OperationRejected):  # the same setting again changes nothing
        engine.apply_operation(shifted.snapshot, OpSpec("tone_shift", tone=TONE), locked=set())


def test_a_transcreate_edit_records_the_region_language_tone_and_model_on_the_new_snapshot() -> None:
    spec = OpSpec("transcreate", edits=[Edit("headline", {"value": "शुभ दिवाळी", "language": "mr", "script": "Deva"})],
                  region_code="IN-MH", language="mr", tone=TONE, generation={"model_id": "m"})
    result = engine.apply_operation(source(), spec, locked=set())
    assert result.snapshot.language == "mr" and result.snapshot.settings["tone"] == TONE
    assert result.snapshot.settings["generation"] == {"model_id": "m"}


def test_restore_copies_an_ancestor_and_is_refused_when_it_would_change_a_locked_element() -> None:
    root = source()
    edited = engine.apply_operation(root, OpSpec("replace_text", edits=[Edit("tagline", {"value": "Lights, joy, Diwali"})]), locked=set()).snapshot
    restored = engine.apply_operation(edited, OpSpec("restore", restore_to=root), locked=set())
    assert value_of(restored.snapshot, "tagline") == "Light up Diwali" and restored.target_ids == ["tagline"]
    with pytest.raises(OperationRejected) as refused:  # the tagline was locked after the edit: restoring would change it
        engine.apply_operation(edited, OpSpec("restore", restore_to=root), locked={"tagline"})
    assert refused.value.code == "LOCKED" and refused.value.element_ids == ["tagline"]
    ok = engine.apply_operation(edited, OpSpec("restore", restore_to=root), locked={"logo"})  # a lock elsewhere does not block it
    assert value_of(ok.snapshot, "tagline") == "Light up Diwali"
    with pytest.raises(OperationRejected):  # restoring what is already current is a no-op
        engine.apply_operation(root, OpSpec("restore", restore_to=root), locked=set())


def test_diff_reports_changed_preserved_added_and_removed_elements() -> None:
    before = elements()
    after = copy.deepcopy(before)
    after[1]["value"] = "Lights of Diwali"  # tagline changed
    after[2]["language"], after[2]["script"] = "mr", "Deva"  # headline: two fields changed
    after[3]["locked"] = True  # locked is not content
    removed = after.pop(0)  # logo removed
    after.append({"id": "cta", "kind": "cta", "value": "Shop now", "language": "en", "script": "Latn", "bbox": None, "scene_id": None, "locked": False})
    added, gone, changed, preserved = engine.diff_elements(before, after)
    assert [e["id"] for e in added] == ["cta"] and [e["id"] for e in gone] == [removed["id"]]
    by_id = {c["element_id"]: c for c in changed}
    assert set(by_id) == {"tagline", "headline"}
    assert by_id["tagline"]["fields"] == [{"field": "value", "before": "Light up Diwali", "after": "Lights of Diwali"}]
    assert {f["field"] for f in by_id["headline"]["fields"]} == {"language", "script"}
    assert preserved == ["music"]  # unchanged apart from `locked`


def test_diff_settings_lists_region_language_and_tone_dials() -> None:
    a = Snapshot([], "IN-MH", "en", {"tone": None})
    b = Snapshot([], "IN-TN", "ta", {"tone": TONE})
    fields = {c["field"]: (c["before"], c["after"]) for c in engine.diff_settings(a, b)}
    assert fields["region_code"] == ("IN-MH", "IN-TN") and fields["language"] == ("en", "ta")
    assert fields["tone.formality"] == (None, 80) and len(fields) == 2 + 5
    assert engine.diff_settings(b, b) == []
