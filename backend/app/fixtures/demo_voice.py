"""Demo-mode "model" outputs for the Voice Director: a handful of instructions about the fictional Aamod journey.

These are hand-written fixtures. Each responder
reads the same payload the live model is given (the elements, versions and chips of the selected version) and answers in the
live output schema, so the plan goes through the same code validation as a live plan: a locked tagline is still refused, an
unknown element is still dropped. Any other instruction gets "This instruction is not available in the demo." with the examples that
do work, instead of an invented plan. The Tamil line below was written by the demo author and has not been reviewed by a
native speaker.
"""

import re
from collections.abc import Mapping
from typing import Any

from app.fixtures import demo_aamod

Context = Mapping[str, Any]
NO_FIXTURE = "This instruction is not available in the demo."
EXAMPLES = (
    "Make the Tamil headline warmer, keep the brand name",
    "Lock the call to action",
    "Make the tagline shorter",
    "Suggest tweak chips for the delivery line",
    "Adapt this for West Bengal in Bengali",
    "Go back to the original",
    "Open the Launch Room",
)
# current Tamil headline -> warmer line: "Deepavali means palagaram!" -> "Deepavali means home-made palagaram!"
WARMER: dict[str, tuple[str, str]] = {
    "தீபாவளி என்றால் பலகாரம்!": (
        "தீபாவளி என்றாலே வீட்டுப் பலகாரம்!",
        "Adding 'வீட்டுப்' (of the home) and the emphatic 'என்றாலே' makes the line sound like a family speaking. "
        "The brand name Aamod is not in this line, so it stays exactly as it is."),
}
WORKSPACE_WORDS = {
    "campaign desk": "desk", "market lens": "lens", "creative studio": "studio", "audience lab": "lab", "launch room": "launch",
    "live pulse": "pulse", "proof vault": "proof",
}


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def _refusal(why: str = NO_FIXTURE) -> dict[str, Any]:
    return {"supported": False, "summary": "", "refusal": f"{why} Instructions that work: " + "; ".join(f"“{e}”" for e in EXAMPLES) + ".", "steps": []}


def _plan(summary: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"supported": True, "summary": summary, "refusal": None, "steps": steps}


def _elements(ctx: Context, *, kind: str, language: str | None = None) -> list[Mapping[str, Any]]:
    return [e for e in ctx["elements"] if e["kind"] == kind and (language is None or e["language"] == language)]


def direct_plan(ctx: Context) -> dict[str, Any]:
    """`voice-direct-v2` for the Aamod demo instructions; the no-fixture answer for anything else."""
    n = _plain(ctx["instruction"])
    if "warmer" in n and "headline" in n:
        for headline in _elements(ctx, kind="headline", language="ta"):
            if headline["text"] in WARMER:
                text, why = WARMER[headline["text"]]
                return _plan("Make the Tamil headline warmer and leave the brand name as it is.", [
                    {"kind": "edit_element", "element_id": headline["id"], "new_value": text, "rationale": why}])
        return _refusal("No Tamil headline with a demo rewrite in this version.")
    if n.startswith("lock") and "call to action" in n:
        free = [e for e in _elements(ctx, kind="cta") if not e["locked"]]
        if not free:
            return _refusal("The call to action is already locked in this version.")
        return _plan("Lock the call to action so nothing can change it.", [
            {"kind": "lock_element", "element_id": e["id"], "rationale": "Locked elements refuse every change from people and from AI."} for e in free])
    if "tagline" in n and "shorter" in n:
        taglines = _elements(ctx, kind="tagline")
        if not taglines:
            return _refusal("This version has no tagline.")
        return _plan("Shorten the tagline.", [
            {"kind": "edit_element", "element_id": taglines[0]["id"], "new_value": "Every bond, sweeter.",
             "rationale": "Drops 'a little' to shorten the line."}])
    if "bengal" in n and ("bengali" in n or "adapt" in n or "transcreate" in n):
        lines = [e["id"] for e in ctx["elements"] if e["kind"] in demo_aamod.TRANSCREATE_KINDS and not e["locked"]
                 and e["text"] in demo_aamod.PHRASEBOOK and e["id"] not in demo_aamod.SMALL_PRINT_IDS]
        if not lines:
            return _refusal("Only the Maharashtra (Marathi) original has demo lines for this. Select it first.")
        return _plan("Transcreate the copy into Bengali for West Bengal.", [
            {"kind": "transcreate", "region_code": "IN-WB", "language": "bn", "element_ids": lines,
             "rationale": "Bengali is the primary language of West Bengal in the reference list."}])
    if re.match(r"^(go back to|restore) the original$", n):
        originals = [v["handle"] for v in ctx["versions"] if v["label"].startswith("Original")]
        if not originals:
            return _refusal("You are already on the original version.")
        return _plan("Go back to the original version.", [
            {"kind": "restore_version", "version": originals[0],
             "rationale": "Restoring makes a new version that copies the original; nothing is overwritten."}])
    if "tweak chip" in n and ("delivery" in n or "call to action" in n):
        hooks = [e for e in _elements(ctx, kind="cta") if e["id"].endswith("cta-hook")]
        region = ctx["selected_version"]["region_code"]
        if not hooks or region is None:
            return _refusal("This version has no delivery line or no region.")
        return _plan("Ask for Tweak Chips for the delivery line.", [
            {"kind": "propose_chips", "element_id": hooks[0]["id"], "region_code": region,
             "rationale": "Tweak Chips are grounded in the region's claims."}])
    if re.match(r"^(open|go to|take me to|show me) (the )?[a-z ]+$", n):
        target = next((key for words, key in WORKSPACE_WORDS.items() if words in n), None)
        if target is not None:
            return _plan("Open a workspace.", [{"kind": "navigate", "workspace": target, "rationale": "Opens the page; nothing changes."}])
    return _refusal()


RESPONDERS = {"voice-direct-v2": direct_plan}
