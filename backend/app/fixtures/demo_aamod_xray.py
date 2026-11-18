"""The saved Creative X-Ray reading of the Aamod Maharashtra film and key visual (demo fixtures).

The film and the key visual were made for the demo: every word on screen was rendered in code from the creative's own
elements, and the scenes were written in `creative_mh_original.json`. So what a vision model would report per keyframe is
known: this module writes it down (frame observations from the elements and the scene descriptions) together with the
scene readings a model would propose. The demo seed feeds both through the real X-Ray verification (`build_scenes`), which
keeps only on-screen text found in the frame observations, claims that quote that text or the transcript, observations that
cite real frames or segments, and interpretations that rest on an observation. Nothing here is a live model result, and the
analysis says so (provider "fixture").

Cultural observations (what is seen or heard) stay apart from interpretations (a reading of them). The interpretations are
a demonstration model's reading, not facts. The author's notes in the fixture JSON are NOT used as findings.
"""

from typing import Any

TEXT_KINDS = ("headline", "body", "cta", "caption", "tagline")
# the keyframe of each scene: one frame per scene, taken from the film (see creative/mh_original/keyframes)
FRAME_MS = {"mh-s1": 2350, "mh-s2": 7450, "mh-s3": 12600, "mh-s4": 17400, "mh-s5": 24600}
TRANSCRIPT_OF = {"mh-s1": ["t1"], "mh-s2": ["t2"], "mh-s3": ["t3"], "mh-s4": ["t4"], "mh-s5": ["t5", "t6"]}

# scene -> what is visible, other than the text the elements already give
VISUALS: dict[str, dict[str, Any]] = {
    "mh-s1": {
        "frame": [("object", "A star-shaped paper lantern (an akash kandil) hangs from the balcony ceiling and glows", "top centre"),
                  ("object", "A row of small clay oil lamps burns along the balcony ledge", "centre"),
                  ("object", "A rangoli of dots and flower patterns decorates the floor near the doorway", "bottom"),
                  ("object", "A teal tin with a brass lid stands among the lamps", "centre right")],
        "people": [], "gestures": [], "setting": "A balcony of an apartment building at dusk, decorated for Diwali",
        "objects": ["Star-shaped paper lantern", "Clay oil lamps", "Rangoli", "Aamod tin"],
        "colours": ["Saffron", "Red", "Deep blue", "Peacock teal"],
    },
    "mh-s2": {
        "frame": [("person", "An older woman in a purple silk saree with a green and gold border and a young woman in a yellow kurta sit at a table", "centre"),
                  ("object", "Round yellow laddoos, spiral snacks and crescent-shaped pastries are arranged on a large brass plate", "bottom centre"),
                  ("object", "A closed teal tin stands on the table next to the plate", "bottom right"),
                  ("object", "Marigold garlands hang in the doorway behind them", "top")],
        "people": ["An older woman in a purple silk saree", "A young woman in a yellow kurta"],
        "gestures": ["They smile and talk while arranging snacks on a plate"], "setting": "A home dining table in the evening",
        "objects": ["Brass plate of snacks", "Teal tin", "Marigold garlands", "Clay lamps"], "colours": ["Purple", "Yellow", "Gold"],
    },
    "mh-s3": {
        "frame": [("object", "An open teal tin with its brass lid leaning against it is filled with snacks", "centre"),
                  ("object", "Small glowing clay lamps and marigold flowers surround the tin", "bottom"),
                  ("object", "A red and gold cloth lies under the tin", "bottom")],
        "people": [], "gestures": [], "setting": "A carved wooden table with lamps and marigolds",
        "objects": ["Open Aamod tin", "Assorted snacks", "Clay lamps", "Marigolds"], "colours": ["Teal", "Gold", "Warm orange"],
    },
    "mh-s4": {
        "frame": [("person", "A young woman in a green silk saree holds a brass plate with a small lit lamp, rice and red powder", "centre left"),
                  ("person", "A young man in a cream kurta sits cross-legged on a low wooden seat in front of a rangoli", "centre right"),
                  ("object", "He holds out the teal tin with both hands", "centre")],
        "people": ["A young woman in a green silk saree", "A young man in a cream kurta"],
        "gestures": ["She holds a lit lamp on a plate in front of him", "He offers her the tin with both hands", "Both are laughing"],
        "setting": "A home with marigold garlands and a rangoli",
        "objects": ["Brass plate with lamp", "Low wooden seat", "Teal tin", "Rangoli"], "colours": ["Green", "Cream", "Gold"],
    },
    "mh-s5": {
        "frame": [("symbol", "The Aamod logo: a lit lamp in a teal disc beside the word Aamod", "top centre"),
                  ("object", "A teal tin with a brass lid and a cream medallion stands in the centre", "centre"),
                  ("object", "A red button holds the call to action", "bottom centre")],
        "people": [], "gestures": [], "setting": "A peacock-teal end card with greeting, logo, pack, call to action and tagline",
        "objects": ["Aamod Festive Tin"], "colours": ["Peacock teal", "Marigold", "Cream", "Red"],
    },
    "kv": {
        "frame": [("object", "Brass plates and bowls hold round yellow laddoos, spiral snacks, crescent-shaped pastries and a bowl of flattened-rice mix", "centre"),
                  ("object", "Small clay lamps and marigold petals sit among the plates", "centre"),
                  ("object", "A glowing star-shaped paper lantern is softly blurred in the background", "top"),
                  ("object", "A teal tin with a brass lid stands in the lower right", "bottom right")],
        "people": [], "gestures": [], "setting": "A dark teal tabletop with a Diwali snack spread and lamps",
        "objects": ["Brass plates of snacks", "Clay lamps", "Marigolds", "Star-shaped paper lantern", "Aamod tin"],
        "colours": ["Peacock teal", "Gold", "Marigold"],
    },
}

CLAIM = "महाराष्ट्रातील सर्वोत्तम फराळ टिन"

# scene -> (observations [(text, category, evidence)], interpretations [(text, category, based_on)], claims [quote])
NOTES: dict[str, tuple[list, list, list]] = {
    "mh-s1": (
        [("A star-shaped paper lantern hangs from the balcony ceiling and glows.", "symbol", ["f{n}"]),
         ("The voice-over says the aroma of faral fills the whole house when Diwali arrives.", "food", ["t1"]),
         ("The headline reads that Diwali means faral.", "language", ["f{n}"])],
        [("The star-shaped lantern reads as a Maharashtrian Diwali decoration; the lamps and decorations that read as local differ by state.", "custom", ["o1"]),
         ("'Faral' is a Marathi word for the Diwali snack assortment, so the headline ties the festival to one regional tradition.", "language", ["o2", "o3"])],
        [],
    ),
    "mh-s2": (
        [("An older woman in a purple silk saree and a young woman arrange snacks on a brass plate at home.", "family", ["f{n}"]),
         ("The voice-over names chakli, karanji and besan laddoos made by a grandmother.", "food", ["t2"])],
        [("The silk saree and the home setting mark the family as Maharashtrian; the grandmother-and-granddaughter scene is a family moment that other regions can echo with their own dress and dishes.", "family", ["o1"]),
         ("The items named are the Maharashtrian faral set; other regions' Diwali snacks differ.", "food", ["o2"])],
        [],
    ),
    "mh-s3": (
        [("An open teal tin filled with snacks stands among lamps and marigolds.", "food", ["f{n}"]),
         ("The voice-over names the Aamod Festive Tin in Devanagari script.", "language", ["t3"])],
        [("The tin is the brand's constant; what is inside is the part that follows the region.", "custom", ["o1", "o2"])],
        [],
    ),
    "mh-s4": (
        [("A young woman holds a lit lamp on a plate in front of a young man, who offers her the tin.", "family", ["f{n}"]),
         ("The voice-over invites the viewer to give a sweet gift to 'our own people' this Bhau Beej.", "festival", ["t4"])],
        [("Bhau Beej, the sibling day after Diwali, is the Marathi name and framing; other states use other names and customs for the day.", "festival", ["o1", "o2"]),
         ("'आपल्या माणसांना' (to our own people) is an idiom that needs transcreation, not a word-for-word translation.", "language", ["o2"])],
        [],
    ),
    "mh-s5": (
        [("The end card shows the Aamod logo, the tin, the call to action and the English tagline.", "symbol", ["f{n}"]),
         ("The call to action promises delivery home before Bhau Beej.", "festival", ["f{n}", "t5"]),
         ("The small print says this is the best faral tin in Maharashtra, per customer preference.", None, ["f{n}"])],
        [("The delivery promise is tied to Bhau Beej, which not every state observes under that name or on the same day.", "festival", ["o2"]),
         ("The small print makes a superiority claim that names no source, sample or date; Risk Check reviews it.", None, ["o3"])],
        [CLAIM],
    ),
    "kv": (
        [("A spread of Diwali snacks on brass plates sits among clay lamps and marigolds.", "food", ["f1"]),
         ("The headline reads that Diwali means faral.", "language", ["f1"]),
         ("The small print says this is the best faral tin in Maharashtra, per customer preference.", None, ["f1"])],
        [("The snack spread is the Maharashtrian faral set, so the image is regional as well as the text.", "food", ["o1", "o2"]),
         ("The same superiority claim as on the end card, with no source, sample or date.", None, ["o3"])],
        [CLAIM],
    ),
}


def _where(bbox: list[float] | None) -> str | None:
    if not bbox:
        return None
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    vertical = "top" if cy < 0.34 else "centre" if cy < 0.67 else "bottom"
    horizontal = "left" if cx < 0.34 else "centre" if cx < 0.67 else "right"
    return vertical if vertical == horizontal == "centre" else f"{vertical} {horizontal}".replace("centre centre", "centre")


def _texts(creative: dict[str, Any], scene_id: str | None) -> list[dict[str, Any]]:
    return [e for e in creative["elements"] if e["kind"] in TEXT_KINDS and isinstance(e["value"], str) and e.get("scene_id") == scene_id]


def scene_keys(creative: dict[str, Any]) -> list[str]:
    """Fixture scene ids of a creative, in order; the key visual is one scene, `kv`."""
    return [s["id"] for s in creative["scenes"]] if "scenes" in creative else ["kv"]


def frame_lines(creative: dict[str, Any], key: str) -> list[tuple[str, str, str | None]]:
    """What a vision model would report for the frame of a scene: its visible things, then the text on screen."""
    texts = _texts(creative, None if key == "kv" else key)
    return [*VISUALS[key]["frame"], *(("text_in_image", f'Text reads: "{e["value"]}"', _where(e.get("bbox"))) for e in texts)]


def scene_draft(creative: dict[str, Any], key: str, frame: str) -> dict[str, Any]:
    """One scene as the structuring model would propose it (a `SceneOut` as a dict). `frame` is the frame id (f1, ...)."""
    visuals, (observations, readings, claims) = VISUALS[key], NOTES[key]
    times = {} if key == "kv" else {"start_ms": next(s["start_ms"] for s in creative["scenes"] if s["id"] == key),
                                    "end_ms": next(s["end_ms"] for s in creative["scenes"] if s["id"] == key)}
    return {
        **({"start_ms": 0} if key == "kv" else times),
        "on_screen_text": [e["value"] for e in _texts(creative, None if key == "kv" else key)],
        "people": visuals["people"], "gestures": visuals["gestures"], "setting": visuals["setting"], "objects": visuals["objects"],
        "colours": visuals["colours"], "claims": [{"quote": q, "source": "on_screen_text"} for q in claims],
        "observations": [{"ref": f"o{n}", "text": t, "category": c, "evidence": [e.format(n=frame[1:]) for e in ev]}
                         for n, (t, c, ev) in enumerate(observations, 1)],
        "interpretations": [{"text": t, "based_on": b, "category": c} for t, c, b in readings],
    }
