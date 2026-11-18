"""Demo-mode "model" outputs for the Audience Lab sessions (Live Focus Group, Buzz Simulator, Message Check).

Deterministic and labelled like the rest of the Audience Lab fixtures: the gateway records provider "fixture" and the
workflows add a demo note. Each responder reads the agent's structured input (the speakers and the transcript, the accounts
and their feeds, the participants and the copy they read) and writes output in that agent's schema, so it passes the same
validation, handle checks and counting as a live model's. Nothing here is research. Sentiment follows the Aamod panel patterns
in `demo_aamod` where the creative is Aamod's, so a demo session agrees with the Quick Read stored beside it.
"""

from collections.abc import Mapping
from typing import Any

from app.analytics.lab_text import content_words
from app.fixtures import demo_aamod

Context = Mapping[str, Any]
SENTIMENTS = ("positive", "mixed", "positive", "neutral", "confused", "mixed", "negative")
OPPOSED = ("negative", "confused")


def _headline(ctx: Context) -> str:
    creative = ctx.get("creative") or {}
    return creative.get("headline") or creative.get("body") or "this ad"


def _short(text: str, n: int = 90) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _sentiment(ctx: Context, row: Mapping[str, Any]) -> str:
    return demo_aamod.sentiment_for(ctx, row) or SENTIMENTS[row["ordinal"] % len(SENTIMENTS)]


# --- Live Focus Group -----------------------------------------------------------------------------------------------

TOPICS = (  # (needle in the question, topic key)
    ("first impression", "impression"), ("in your own words", "message"), ("telling you", "message"), ("made for you", "fit"),
    ("out of place", "fit"), ("talk about it", "talk"), ("family", "talk"), ("change", "change"),
)
LINES: dict[str, dict[str, str]] = {
    "impression": {
        "positive": "It feels warm and easy to like, and it looks like something I would notice on my phone.",
        "mixed": "I like the look, but I am not fully sure what I am being asked to do.",
        "neutral": "It is fine. Nothing in it stops me and nothing makes me stay.",
        "negative": "It does not speak to me. It feels like it was made for someone else.",
        "confused": "I cannot tell if this is an announcement or an offer.",
    },
    "message": {
        "positive": "To me it says: here is a ready festive gift, and it will reach you before the festival.",
        "mixed": "It says something about festive sweets and gifting. The delivery part I only half caught.",
        "neutral": "It is selling festive sweets. I could not tell you more than that.",
        "negative": "It reads like a generic festival greeting, not something I can buy.",
        "confused": "Maybe it is a festival offer? I am not sure what I get or by when.",
    },
    "fit": {
        "positive": "The words and the festive feeling are close to how we celebrate here, so it feels made for people like me.",
        "mixed": "Parts feel local and parts feel borrowed from somewhere else, so it is hit and miss for me.",
        "neutral": "It neither feels local nor out of place. It could be anywhere.",
        "negative": "Some of it feels out of place for where I live, and I would skip it.",
        "confused": "I am not sure which festival day it means, so I cannot say if it fits here.",
    },
    "talk": {
        "positive": "I would send it to my family group and say this is a nice gift idea before the festival.",
        "mixed": "I might mention it to one person, but only if the delivery date were clear.",
        "neutral": "Probably not. I would only talk about it if someone asked.",
        "negative": "No, I would not share it. I would not know what to say about it.",
        "confused": "I would first ask someone else what it is offering before I said anything.",
    },
    "change": {
        "positive": "Keep it as it is. If anything, say the delivery day plainly.",
        "mixed": "Say exactly what is offered and by which day it arrives.",
        "neutral": "Give me one concrete reason to care, like a date or a price.",
        "negative": "Start again with something that sounds like people here talk.",
        "confused": "Name the product and the delivery day in the first line.",
    },
    "general": {
        "positive": "That works for me, and I would say so.",
        "mixed": "Partly. I agree with some of it and not with the rest.",
        "neutral": "I do not have a strong view either way.",
        "negative": "Not for me, and here is why: it does not answer what I asked.",
        "confused": "I am still not sure what it means, so I would hold my answer.",
    },
}
THEME = {
    "positive": "warm tone", "mixed": "unclear delivery promise", "neutral": "generic message", "negative": "does not fit here",
    "confused": "unclear offer",
}
REPLY = {"agrees": "I agree with Participant {n}. ", "disagrees": "I see it differently from Participant {n}. ",
         "builds_on": "Building on Participant {n}: "}


def _topic(question: str) -> str:
    low = question.casefold()
    return next((key for needle, key in TOPICS if needle in low), "general")


def _stance_in_round(base: str, row: Mapping[str, Any], round_index: int) -> str:
    """A speaker keeps their stored stance; a mixed speaker who hears a clear case later in the session may come round."""
    if round_index >= 2 and base == "mixed" and row["ordinal"] % 2 == 0:
        return "positive"
    if round_index >= 2 and base == "confused":
        return "mixed"
    return base


def focus_round(ctx: Context) -> dict:
    topic, rounds = _topic(ctx["question"]), ctx["round_index"]
    rows, first, claims = ctx["speakers"], ctx["first_turn"], ctx.get("claims") or []
    before: dict[str, str] = {}
    out = []
    for j, row in enumerate(rows):
        stance = _stance_in_round(row.get("said_before", {}).get("stance") or "neutral", row, rounds)
        reply_to, relation = None, "new_point"
        if j > 0:  # answer the speaker just before, as people do in a room
            prev = rows[j - 1]
            reply_to = f"T{first + j - 1}"
            prev_stance = before[prev["participant"]]
            relation = ("disagrees" if (stance == "positive") != (prev_stance == "positive") and
                        (stance in OPPOSED or prev_stance in OPPOSED) else "agrees" if stance == prev_stance else "builds_on")
            opener = REPLY[relation].format(n=prev["ordinal"] + 1)
        else:
            opener = ""
        line = LINES[topic][stance]
        if relation == "builds_on" and not line.startswith("I "):
            line = line[0].lower() + line[1:]  # "Building on Participant 2: it feels ..."
        text = opener + ("On that question: " if ctx["kind"] == "interjection" and not opener else "") + line
        before[row["participant"]] = stance
        cite = [claims[row["ordinal"] % len(claims)]["handle"]] if claims and topic == "fit" and stance != "positive" else []
        out.append({"participant": row["participant"], "text": text, "reply_to": reply_to, "relation": relation, "stance": stance,
                    "themes": [THEME[stance]], "claims": cite})
    return {"turns": out}


# --- Buzz Simulator -------------------------------------------------------------------------------------------------

BUZZ_LINE = {  # three voices per stance, chosen by the account's number
    "positive": ("This is the kind of gift I would actually send. Sharing it with the family group.",
                 "Love the tin and the idea of a ready gift. Tagging my sister.",
                 "Sending this to the whole family before the festival. Good find."),
    "mixed": ("Nice idea, but when does it reach? Asking before I share.",
              "Looks good. I would want to know the delivery day first.",
              "Pretty, but is it really home-style? Not sure yet."),
    "neutral": ("Saw this. Fine, nothing special.", "Another festive ad. It is okay.", "Noted. Not for me right now."),
    "negative": ("Not sure this is for us. Does not feel like our festival.", "This does not sound like how we celebrate.",
                 "Skipping this one. It feels made for somewhere else."),
    "confused": ("What is this exactly, an offer or just a greeting?", "Is this selling something or just wishing us?",
                 "Can someone explain what is on offer here?"),
}
BUZZ_TOPICS = {
    "positive": ["gifting", "festival"], "mixed": ["delivery date"], "neutral": ["festive sweets"], "negative": ["does not fit"],
    "confused": ["unclear offer"],
}
BUZZ_GLOSS = {  # what an account says it is passing on: faithful, thinner, or off
    "positive": None, "mixed": "Festive sweets as a gift, maybe delivered on time.", "neutral": "An ad for festive sweets.",
    "negative": "A festival greeting from a sweets brand.", "confused": "Some festival announcement, not clear what for.",
}


def buzz_round(ctx: Context) -> dict:
    headline, intended, rounds = _headline(ctx), ctx.get("intended_message"), ctx["round_index"]
    out = []
    for row in ctx["accounts"]:
        s = _sentiment(ctx, row)
        n = row["ordinal"]
        if s == "positive":  # a few reshare or post, most only reply: spread in the demo stays partial
            action = ("share" if n % 4 == 0 else "post" if n % 4 == 1 else "reply") if rounds == 1 else ("share" if n % 4 == 0 else "reply")
        elif s == "neutral":
            action = "ignore" if n % 2 == 0 else "reply"
        elif s == "confused":  # a confused account sometimes forwards it with a question, passing on a different message
            action = "share" if n % 2 == 0 else "reply"
        else:
            action = "reply"
        feed = row["feed"]
        target = feed[0]["handle"] if feed else None
        line = BUZZ_LINE[s][n % 3]
        if action == "ignore":
            out.append({"participant": row["participant"], "action": "ignore", "reply_to": None, "text": None, "text_en": None,
                        "message_gloss": None, "stance": s, "topics": []})
            continue
        quoted = f"\"{_short(headline, 60)}\" "
        gloss = (intended if s == "positive" and intended else BUZZ_GLOSS[s] or "Festive sweets as a gift, delivered before the festival day.") \
            if action in ("post", "share") else None
        out.append({
            "participant": row["participant"], "action": action, "reply_to": target if action in ("reply", "share") else None,
            "text": quoted + line, "text_en": "[quotes the ad's headline] " + line, "message_gloss": gloss, "stance": s, "topics": BUZZ_TOPICS[s]})
    return {"acts": out}


# --- Message Check --------------------------------------------------------------------------------------------------


def _restatement(s: str, points: list[str]) -> tuple[str, list[str]]:
    """(English restatement, recall) for a sentiment, written from the key point texts so the comparison can be checked."""
    lower = [p[0].lower() + p[1:] if p else p for p in points] or ["something to do with the festival"]
    if s == "positive":
        return "It says: " + ", ".join(lower) + ".", [points[0]] if points else []
    if s == "mixed":
        return "It says: " + ", ".join(lower[:-1] or lower) + ". I did not catch much else.", [points[0]] if points else []
    if s == "neutral":
        return "It is some festive sweets for the festival.", ["festive sweets"]
    if s == "negative":
        return "It looks like a general festival greeting, not something I can buy.", ["a festival greeting"]
    return "I am not sure what is on offer; maybe an announcement of some kind.", ["something for the festival"]


def message_check_read(ctx: Context) -> dict:
    points = [str(p) for p in ctx.get("key_points") or []]
    out = []
    for row in ctx["participants"]:
        restated, recall = _restatement(_sentiment(ctx, row), points)
        out.append({"participant": row["participant"], "restated": restated, "restated_en": restated, "recall": recall})
    return {"participants": out}


MISREAD = (  # marker in the restatement -> (label, why)
    ("greeting", ("Reads as a greeting, not an offer", "The restatement calls it a festival greeting and says it is not something to buy.")),
    ("announcement", ("Reads as an announcement", "The restatement is unsure what is offered and takes it for an announcement.")),
)


def _coverage(point: str, text: str) -> str:
    wanted = content_words(point)
    ratio = len(wanted & content_words(text)) / len(wanted) if wanted else 0.0
    return "yes" if ratio >= 0.75 else "partly" if ratio >= 0.25 else "no"


def message_check_compare(ctx: Context) -> dict:
    points = ctx["key_points"]
    out = []
    for row in ctx["participants"]:
        text = row["restated_en"]
        recall = " ".join(row.get("recall") or [])
        judged = [{"point": k, "restated": _coverage(p, text), "recalled": _coverage(p, recall) == "yes"} for k, p in points.items()]
        misread = next((m for marker, m in MISREAD if marker in text.casefold()), None)
        out.append({"participant": row["participant"], "points": judged,
                    "misreading": {"label": misread[0], "why": misread[1]} if misread else None})
    return {"participants": out}


RESPONDERS = {
    "focus-round-v1": focus_round,
    "buzz-round-v1": buzz_round,
    "message-check-read-v1": message_check_read,
    "message-check-compare-v1": message_check_compare,
}
