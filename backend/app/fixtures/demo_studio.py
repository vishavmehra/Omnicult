"""Demo-mode "model" outputs for Creative Studio: a small hand-written phrasebook for Transcreate and Tweak Chips.

These are fixtures, labelled as such by the workflows ("Demo fixture output, not a live model response."). They cover a
few generic festive lines in Marathi and Tamil, with a formal and a casual rendering each (so the Tone Dials visibly
change the output); any other input returns None, which the fixture provider reports as "No demo fixture for this input"
instead of inventing text. Back-translations are literal English renderings of the regional copy written here by hand.
"""

from collections.abc import Mapping
from typing import Any

Context = Mapping[str, Any]
FORMAL_FROM = 70  # a formality dial at or above this picks the formal rendering

# source text (casefolded) -> language -> (casual copy, casual back, formal copy, formal back, explanation)
LINES: dict[str, dict[str, tuple[str, str, str, str, str]]] = {
    "happy diwali": {
        "mr": ("शुभ दिवाळी!", "Happy Diwali!",
               "आपणा सर्वांना दिवाळीच्या हार्दिक शुभेच्छा", "Heartfelt Diwali wishes to all of you",
               "Marathi greetings use 'शुभेच्छा' (good wishes), not a word-for-word 'happy'; the formal form addresses everyone with 'आपणा'."),
        "ta": ("இனிய தீபாவளி!", "Sweet Deepavali!",
               "அனைவருக்கும் தீபாவளி நல்வாழ்த்துகள்", "Deepavali good wishes to everyone",
               "In Tamil Nadu the festival is usually written and said as Deepavali (தீபாவளி), and greetings use 'வாழ்த்துகள்' (wishes)."),
    },
    "shop now": {
        "mr": ("आत्ताच खरेदी करा", "Shop right now", "कृपया आत्ताच खरेदी करा", "Please shop right now",
               "A direct call to action in everyday Marathi; the formal form adds 'कृपया' (please)."),
        "ta": ("இப்போதே வாங்குங்கள்", "Buy right now", "தயவுசெய்து இப்போதே வாங்குங்கள்", "Kindly buy right now",
               "A direct call to action in everyday Tamil; the formal form adds 'தயவுசெய்து' (kindly)."),
    },
    "brighten your home this festive season": {
        "mr": ("या सणासुदीत तुमचं घर उजळवा", "Make your home glow this festive season",
               "या सणासुदीच्या काळात आपले घर उजळवा", "In this festive period make your home glow",
               "'सणासुदी' is the everyday Marathi word for the stretch of festivals, so the line sounds local rather than translated."),
        "ta": ("இந்த பண்டிகை நாட்களில் உங்கள் வீட்டை ஒளிரச் செய்யுங்கள்", "Make your home glow in these festival days",
               "இந்த பண்டிகைக் காலத்தில் தங்கள் இல்லத்தை ஒளிரச் செய்யுங்கள்", "In this festival season make your home glow",
               "'தங்கள் இல்லம்' is the respectful form of 'your home' used in formal Tamil."),
    },
}


def _festival_handles(claims: list[Mapping[str, Any]]) -> list[str]:
    festival = [c["handle"] for c in claims if c["category"] == "festival"]
    return festival[:1] or [c["handle"] for c in claims][:1]


def transcreate_lines(ctx: Context) -> dict[str, Any] | None:
    language = ctx["language"]
    formal = ctx["tone"]["formality"] >= FORMAL_FROM
    out = []
    for handle, line in ctx["lines"].items():
        row = LINES.get(line["text"].strip().casefold(), {}).get(language)
        if row is None:
            return None
        copy, back = (row[2], row[3]) if formal else (row[0], row[1])
        out.append({"line": handle, "regional_copy": copy, "back_translation": back, "explanation": row[4],
                    "claims": _festival_handles(ctx["claims"]) if "diwali" in line["text"].casefold() or "festive" in line["text"].casefold() else [],
                    "preserved_terms": []})
    return {"lines": out}


# element text -> (title, new text, reason, expected effect)
CHIPS: dict[str, tuple[str, str, str, str]] = {
    "shop now": ("Make the call to action festive", "Shop the festive range",
                 "The region's festival claim suggests tying the call to action to the festive season.",
                 "Links the action to the occasion; slightly longer."),
    "शुभ दिवाळी!": ("Make it warmer", "दिवाळीच्या हार्दिक शुभेच्छा!",
                   "A fuller greeting with 'हार्दिक' (heartfelt) is the more traditional Marathi festive wish.",
                   "Warmer and more traditional; two words longer."),
}


def tweak_chips(ctx: Context) -> dict[str, Any] | None:
    element = ctx["element"]
    entry = CHIPS.get(str(element["value"]).strip().casefold())
    if entry is None:
        return None
    handles = _festival_handles(ctx["claims"])
    if not handles:
        return {"chips": []}  # no claim to cite, so no chip: the fixture never invents evidence
    title, text, reason, effect = entry
    return {"chips": [{"title": title, "operation_type": "replace_text", "new_value": text, "reason": reason,
                       "claims": handles, "expected_effect": effect}][: ctx["count"]]}


RESPONDERS = {"transcreate-lines-v1": transcreate_lines, "tweak-chips-v1": tweak_chips}
