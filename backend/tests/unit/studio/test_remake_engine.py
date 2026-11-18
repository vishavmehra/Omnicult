"""The `remake` operation in the operation engine: a generated asset replaces an element's value or is added as a new
element, locks refuse it, and the source snapshot is never touched."""

import copy

import pytest

from app.studio.engine import Edit, OperationRejected, OpSpec, Snapshot, apply_operation


def snapshot() -> Snapshot:
    return Snapshot(elements=[
        {"id": "plate", "kind": "scene", "value": "old.jpg", "language": None, "script": None, "bbox": [0, 0, 1, 1], "scene_id": None, "locked": False},
        {"id": "vo", "kind": "voiceover", "value": {"path": "old.wav"}, "language": "mr", "script": "Deva", "bbox": None, "scene_id": None, "locked": False},
        {"id": "logo", "kind": "logo", "value": "logo.svg", "language": None, "script": None, "bbox": [0, 0, .2, .1], "scene_id": None, "locked": True},
    ], region_code="IN-MH", language="mr")


def test_remake_replaces_a_scene_with_an_asset_reference_and_a_voiceover_with_a_descriptor():
    source = snapshot()
    before = copy.deepcopy(source.elements)
    spec = OpSpec("remake", edits=[Edit("plate", {"value": "asset:1"}), Edit("vo", {"value": {"asset_id": "2"}, "language": "ta", "script": "Taml"})],
                  region_code="IN-TN", language="ta", generation={"run_id": "r"})
    applied = apply_operation(source, spec, locked={"logo"})
    values = {e["id"]: e for e in applied.snapshot.elements}
    assert values["plate"]["value"] == "asset:1" and values["vo"]["value"] == {"asset_id": "2"} and values["vo"]["language"] == "ta"
    assert (applied.snapshot.region_code, applied.snapshot.language) == ("IN-TN", "ta") and applied.snapshot.settings["generation"] == {"run_id": "r"}
    assert applied.target_ids == ["plate", "vo"] and source.elements == before


def test_remake_can_add_new_elements_and_reports_them_as_touched():
    spec = OpSpec("remake", adds=[{"id": "remake-music", "kind": "music", "value": {"asset_id": "3"}}], language="ta")
    applied = apply_operation(snapshot(), spec, locked=set())
    added = applied.snapshot.elements[-1]
    assert added["id"] == "remake-music" and added["locked"] is False and applied.target_ids == ["remake-music"]


def test_a_locked_element_refuses_the_whole_remake():
    spec = OpSpec("remake", edits=[Edit("plate", {"value": "asset:1"}), Edit("logo", {"value": "asset:9"})])
    with pytest.raises(OperationRejected) as refused:
        apply_operation(snapshot(), spec, locked={"logo"})
    assert refused.value.code == "LOCKED" and refused.value.element_ids == ["logo"]


@pytest.mark.parametrize("add", [
    {"id": "plate", "kind": "scene", "value": "x"},  # id already used
    {"id": "bad id!", "kind": "scene", "value": "x"},
    {"id": "new", "kind": "banner", "value": "x"},  # unknown kind
])
def test_added_elements_must_be_valid_and_new(add):
    with pytest.raises(OperationRejected) as refused:
        apply_operation(snapshot(), OpSpec("remake", adds=[add]), locked=set())
    assert refused.value.code == "INVALID"


def test_only_a_remake_or_a_manual_edit_may_add_elements_and_an_unchanged_remake_is_refused():
    for kind in ("replace_text", "apply_chip", "swap_reference"):
        with pytest.raises(OperationRejected):
            apply_operation(snapshot(), OpSpec(kind, edits=[Edit("plate", {"value": "n"})], adds=[{"id": "n", "kind": "scene", "value": "x"}]), set())
    # Generate adds a generated asset to a version as a manual edit; the public manual_edit request still has no way to add
    added = apply_operation(snapshot(), OpSpec("manual_edit", adds=[{"id": "n", "kind": "scene", "value": "x"}]), set())
    assert added.target_ids == ["n"] and any(e["id"] == "n" for e in added.snapshot.elements)
    with pytest.raises(OperationRejected) as same:
        apply_operation(snapshot(), OpSpec("remake", edits=[Edit("plate", {"value": "old.jpg"})]), set())
    assert same.value.code == "INVALID"
