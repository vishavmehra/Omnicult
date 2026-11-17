"""The operation engine: apply one operation to a version snapshot and return a NEW snapshot.

Pure and deterministic. The source snapshot is never mutated. Locks are enforced here, in code, for every actor (a
person, a chip, the transcreate run): an operation that targets a locked element is refused whole, so nothing a model
says can change a locked logo or tagline. A person who wants to edit a locked element unlocks it first (a recorded
change). Restore is a new node copying an ancestor; it is refused if it would change a locked element.
"""

import copy
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from app.schemas.versions import MAX_VALUE_CHARS, TEXT_KINDS

EDITABLE_FIELDS = frozenset({"value", "language", "script", "bbox", "scene_id"})
COMPARED_FIELDS = ("kind", "value", "language", "script", "bbox", "scene_id")  # `locked` is not content
TONE_DIALS = ("formality", "code_mixing", "urban_rural", "playfulness", "energy")
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_SCRIPT = re.compile(r"^[A-Z][a-z]{3}$")

# kind -> (fields it may set, whether it may only target text elements). Every kind except manual_edit must set `value`
# to a non-empty string.
EDIT_RULES: dict[str, tuple[frozenset[str], bool]] = {
    "manual_edit": (EDITABLE_FIELDS, False),
    "replace_text": (frozenset({"value", "language", "script"}), True),
    "transcreate": (frozenset({"value", "language", "script"}), True),
    "apply_chip": (frozenset({"value"}), False),
    "swap_reference": (frozenset({"value"}), False),
}


class OperationRejected(Exception):
    """The operation was refused. `code` is LOCKED (a locked element) or INVALID (it cannot be applied as asked)."""

    def __init__(self, code: str, message: str, element_ids: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.element_ids = sorted(set(element_ids))


@dataclass(frozen=True)
class Edit:
    element_id: str
    set: Mapping[str, Any]


@dataclass
class Snapshot:
    """What a version node holds: its elements and its settings. Copies are made before any change."""

    elements: list[dict[str, Any]]
    region_code: str | None = None
    language: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)  # {"tone": {...} | None, "generation": {...} | None}

    def clone(self) -> "Snapshot":
        return Snapshot(copy.deepcopy(self.elements), self.region_code, self.language, copy.deepcopy(self.settings))


@dataclass(frozen=True)
class OpSpec:
    kind: str
    edits: Sequence[Edit] = ()
    swap: tuple[str, str, str] | None = None  # swap_reference, or an apply_chip swap: (element_id, from_text, to_text)
    region_code: str | None = None  # change_setting; also recorded by an edit made under these settings
    language: str | None = None  # change_setting; likewise
    tone: Mapping[str, int] | None = None  # tone_shift; likewise
    restore_to: Snapshot | None = None  # restore: the ancestor to copy
    generation: Mapping[str, Any] | None = None  # model metadata recorded on the new node (transcreate)


@dataclass
class Applied:
    snapshot: Snapshot
    target_ids: list[str]


def _by_id(elements: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {e["id"]: e for e in elements}


def _content(element: Mapping[str, Any]) -> dict[str, Any]:
    return {name: element.get(name) for name in COMPARED_FIELDS}


# --- diff -----------------------------------------------------------------------------------


def diff_elements(
    before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]]
) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """(added, removed, changed, preserved). `changed` is [{element_id, kind, fields: [{field, before, after}]}]."""
    old, new = _by_id(before), _by_id(after)
    added = [dict(e) for e in after if e["id"] not in old]
    removed = [dict(e) for e in before if e["id"] not in new]
    changed, preserved = [], []
    for element in after:
        previous = old.get(element["id"])
        if previous is None:
            continue
        fields = [
            {"field": name, "before": previous.get(name), "after": element.get(name)}
            for name in COMPARED_FIELDS
            if previous.get(name) != element.get(name)
        ]
        if fields:
            changed.append({"element_id": element["id"], "kind": element["kind"], "fields": fields})
        else:
            preserved.append(element["id"])
    return added, removed, changed, preserved


def diff_settings(before: Snapshot, after: Snapshot) -> list[dict[str, Any]]:
    """Changes to region, language and tone dials (the model metadata of a node is not a creative setting)."""
    changes = []
    for name in ("region_code", "language"):
        if getattr(before, name) != getattr(after, name):
            changes.append({"field": name, "before": getattr(before, name), "after": getattr(after, name)})
    old, new = before.settings.get("tone") or {}, after.settings.get("tone") or {}
    for dial in TONE_DIALS:
        if old.get(dial) != new.get(dial):
            changes.append({"field": f"tone.{dial}", "before": old.get(dial), "after": new.get(dial)})
    return changes


def touched_by(source: Snapshot, target: Snapshot) -> list[str]:
    """Ids of elements that differ between two snapshots (added, removed or changed)."""
    added, removed, changed, _ = diff_elements(source.elements, target.elements)
    return [e["id"] for e in added] + [e["id"] for e in removed] + [c["element_id"] for c in changed]


# --- planning helpers (turn a request into edits) ---------------------------------------------


def swap_edit(elements: Sequence[Mapping[str, Any]], element_id: str, from_text: str, to_text: str) -> Edit:
    """Replace every occurrence of `from_text` in one element's text with `to_text`."""
    element = _by_id(elements).get(element_id)
    if element is None:
        raise OperationRejected("INVALID", f"Element {element_id} does not exist in this version.", [element_id])
    value = element.get("value")
    if not isinstance(value, str) or from_text not in value:
        raise OperationRejected("INVALID", f"'{from_text}' does not appear in element {element_id}.", [element_id])
    return Edit(element_id, {"value": value.replace(from_text, to_text)})


# --- applying -----------------------------------------------------------------------------------


def apply_operation(source: Snapshot, spec: OpSpec, locked: Iterable[str]) -> Applied:
    """The new snapshot for `spec` applied to `source`, or OperationRejected. `source` is never modified."""
    locked_ids = set(locked)
    result = source.clone()
    kind = spec.kind
    if kind == "restore":
        if spec.restore_to is None:
            raise OperationRejected("INVALID", "A restore needs the version to restore.")
        targets = touched_by(source, spec.restore_to)
        _refuse_locked(targets, locked_ids)
        result = spec.restore_to.clone()
        result.settings = {"tone": result.settings.get("tone")}  # the generation metadata belongs to its own node
        if not targets and not diff_settings(source, result):
            raise OperationRejected("INVALID", "The restored version is identical to the version it continues from.")
        return Applied(result, sorted(set(targets)))
    if kind in ("change_setting", "tone_shift"):
        if kind == "change_setting":
            result.region_code = spec.region_code or result.region_code
            result.language = spec.language or result.language
        else:
            result.settings["tone"] = {dial: int((spec.tone or {})[dial]) for dial in TONE_DIALS}
        if not diff_settings(source, result):
            raise OperationRejected("INVALID", "The setting already has this value; nothing would change.")
        return Applied(result, [])
    if kind not in EDIT_RULES:
        raise OperationRejected("INVALID", f"Operation kind '{kind}' cannot be applied directly.")
    if spec.swap is not None:
        _refuse_locked([spec.swap[0]], locked_ids)  # a locked element is refused before its text is looked at
        spec = replace(spec, edits=[swap_edit(result.elements, *spec.swap)])
    return _apply_edits(source, result, spec, locked_ids)


def _apply_edits(source: Snapshot, result: Snapshot, spec: OpSpec, locked_ids: set[str]) -> Applied:
    if not spec.edits:
        raise OperationRejected("INVALID", "The operation has no edits.")
    elements = _by_id(result.elements)
    ids = [edit.element_id for edit in spec.edits]
    unknown = [i for i in ids if i not in elements]
    if unknown:
        raise OperationRejected("INVALID", f"Unknown element(s) in this version: {', '.join(sorted(set(unknown)))}.", unknown)
    if len(ids) != len(set(ids)):
        raise OperationRejected("INVALID", "An element can be edited once per operation.", ids)
    _refuse_locked(ids, locked_ids)  # before any value is looked at: a locked element is refused whatever the edit says
    allowed, text_only = EDIT_RULES[spec.kind]
    for edit in spec.edits:
        element = elements[edit.element_id]
        _validate_edit(spec.kind, element, dict(edit.set), allowed, text_only)
        element.update(edit.set)  # `element` is the clone's dict, so the source is untouched
    if not touched_by(source, result):
        raise OperationRejected("INVALID", "The edit leaves every element unchanged.", ids)
    # An edit may carry the settings it was made under (a transcreation records its region, language and tone dials).
    result.region_code = spec.region_code or result.region_code
    result.language = spec.language or result.language
    if spec.tone is not None:
        result.settings["tone"] = {dial: int(spec.tone[dial]) for dial in TONE_DIALS}
    if spec.generation is not None:
        result.settings["generation"] = dict(spec.generation)
    return Applied(result, ids)


def _refuse_locked(target_ids: Iterable[str], locked_ids: set[str]) -> None:
    blocked = sorted({i for i in target_ids if i in locked_ids})
    if blocked:
        raise OperationRejected(
            "LOCKED", f"Locked element(s) cannot be changed: {', '.join(blocked)}. Unlock them first.", blocked
        )


def _validate_edit(kind: str, element: Mapping[str, Any], changes: dict[str, Any], allowed: frozenset[str], text_only: bool) -> None:
    eid = element["id"]
    bad = sorted(set(changes) - allowed)
    if bad:
        raise OperationRejected("INVALID", f"{kind} cannot set {', '.join(bad)} on {eid}.", [eid])
    if "value" in changes and len(json.dumps(changes["value"], default=str)) > MAX_VALUE_CHARS:
        raise OperationRejected("INVALID", f"The value for {eid} is larger than {MAX_VALUE_CHARS} characters.", [eid])
    if text_only and element["kind"] not in TEXT_KINDS:
        raise OperationRejected("INVALID", f"{kind} applies to text elements; {eid} is a {element['kind']}.", [eid])
    if kind != "manual_edit" or ("value" in changes and element["kind"] in TEXT_KINDS):
        value = changes.get("value")
        if not isinstance(value, str) or not value.strip():
            raise OperationRejected("INVALID", f"{kind} needs a non-empty text value for {eid}.", [eid])
    if "language" in changes and not (changes["language"] is None or _LANGUAGE.match(str(changes["language"]))):
        raise OperationRejected("INVALID", f"language of {eid} must be an ISO 639 code.", [eid])
    if "script" in changes and not (changes["script"] is None or _SCRIPT.match(str(changes["script"]))):
        raise OperationRejected("INVALID", f"script of {eid} must be an ISO 15924 code.", [eid])
    box = changes.get("bbox")
    if "bbox" in changes and box is not None and not (
        isinstance(box, list) and len(box) == 4 and all(isinstance(n, int | float) and 0 <= n <= 1 for n in box)
    ):
        raise OperationRejected("INVALID", f"bbox of {eid} must be [x, y, w, h], each between 0 and 1.", [eid])
