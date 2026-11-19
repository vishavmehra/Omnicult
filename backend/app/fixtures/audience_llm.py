"""Demo-mode "model" outputs for the Audience Lab (Quick Read, Audience Study, Risk Check).

Deterministic: the gateway records provider "fixture". Each responder reads
the agent's structured input (the creative, the sampling dimensions, the supplied region claims) and writes output in that
agent's schema, so the output passes the same validation, quote verification and citation mapping as a live model's.
Nothing here is research: it shows the product working without a provider.
"""

import re
from collections.abc import Mapping
from typing import Any

from app.analytics.risk_rules import HARD_CLAIM
from app.fixtures import demo_aamod

Context = Mapping[str, Any]

SENTIMENTS = ("positive", "mixed", "positive", "neutral", "confused", "mixed", "negative")
RATINGS = {"positive": (4, 4, 2), "mixed": (3, 3, 3), "neutral": (3, 3, 2), "negative": (2, 2, 4), "confused": (2, 2, 3)}
SURVIVAL = {"positive": "understood", "neutral": "understood", "mixed": "partial", "negative": "partial", "confused": "misunderstood"}
OPENERS = {
    "positive": "feels welcoming and easy to like",
    "mixed": "has something I like and something I am unsure about",
    "neutral": "is fine but does not stand out",
    "negative": "does not speak to me",
    "confused": "leaves me unsure what is being offered",
}
MEDICAL = re.compile(r"cure|heal|reverse|clinically|doctor|miracle", re.IGNORECASE)
COMPARATIVE = re.compile(r"better than|no\.?\s?1|number one|#1|best in|world'?s|india'?s|compared|outperform|than any", re.IGNORECASE)


def _headline(ctx: Context) -> str:
    creative = ctx.get("creative") or {}
    return creative.get("headline") or creative.get("body") or "this creative"


def _short(text: str, n: int = 150) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def quick_read(ctx: Context) -> dict:
    headline, claims = _headline(ctx), ctx.get("claims") or []
    intended = ctx.get("intended_message")
    out = []
    for row in ctx["participants"]:
        s = demo_aamod.sentiment_for(ctx, row) or SENTIMENTS[row["ordinal"] % len(SENTIMENTS)]
        clarity, relevance, risk = RATINGS[s]
        where = f"{row['state']} ({row['language']}, {row['city_tier']}, age {row['age_band']})"
        concerns = []
        if claims:
            claim = claims[row["ordinal"] % len(claims)]
            concerns.append({"text": _short(f"Worth checking against regional context: {claim['statement']}"), "claims": [claim["handle"]]})
        if row["ordinal"] % 3 == 0:
            concerns.append({"text": "The tone may read differently across cities and villages in the region.", "claims": []})
        out.append({
            "participant": row["participant"],
            "first_reaction": f"Reading '{_short(headline, 80)}' from {where}, it {OPENERS[s]}.",
            "sentiment": s,
            "message_restated": (f"It is saying: {_short(intended or headline, 120)}" if s not in ("confused", "negative")
                                 else "I am not sure what exactly is on offer."),
            "message_survival": SURVIVAL[s],
            "positives": [{"text": "The wording is short and easy to read.", "claims": []}] if s in ("positive", "mixed", "neutral") else [],
            "negatives": [{"text": "Nothing here tells me why I should act now.", "claims": []}] if s in ("negative", "mixed") else [],
            "confusion": [{"text": "It is not clear who the offer is for.", "claims": []}] if s in ("confused", "mixed") else [],
            "regional_concerns": concerns if s != "positive" or row["ordinal"] % 2 == 0 else [],
            "ratings": {"clarity": clarity, "cultural_relevance": relevance, "cultural_risk": risk},
            "follow_up_question": f"What would make '{_short(headline, 60)}' clearer for people in {row['state']}?",
            "relevant_passage": headline if s in ("positive", "mixed") and headline != "this creative" else None,
        })
    return {"participants": out}


LINES = {
    "positive": ("feels warm and inviting.", "An offer made for people like me.", "Quite relevant to my life.", "The friendly tone.",
                 "Nothing is confusing.", "Mostly; it promises little it cannot keep.", "No real concerns.", "Show it in a real setting."),
    "mixed": ("has a good idea but is not quite there.", "Something about a seasonal offer.", "Partly relevant.", "The look and feel.",
              "Who is it for, exactly?", "Somewhat.", "It may not suit everyone in my area.", "Say plainly what is offered."),
    "neutral": ("is pleasant but generic.", "A brand inviting me to buy.", "Not especially relevant.", "Nothing stands out.",
                "Not really.", "Neutral; it makes no claim.", "None.", "Give me a concrete reason to care."),
    "negative": ("does not speak to me.", "A generic slogan.", "Not relevant to how I decide.", "Nothing.", "What is being sold?",
                 "I do not trust it yet.", "No useful information.", "Name the product and what it does."),
    "confused": ("is hard to place.", "Maybe a festival offer? I am not sure.", "Unclear.", "The festive mood.",
                 "Is this an ad or an announcement?", "I cannot tell yet.", "I might misread what is offered.", "Show the product."),
}
THEMES = {"positive": ["warm tone"], "mixed": ["unclear audience", "warm tone"], "neutral": ["generic message"],
          "negative": ["no product benefit"], "confused": ["unclear offer"]}
CONCERNS = {"mixed": ["may not suit everyone"], "negative": ["no useful information"], "confused": ["what is being offered"]}
QUESTIONS = ("first_impression", "comprehension", "relevance", "appeal", "confusion", "trust", "concerns", "improvement")
STUDY_POOL = ("positive", "mixed", "neutral", "positive", "confused", "negative", "mixed")


def study_interviews(ctx: Context) -> dict:
    headline = _headline(ctx)
    follow_ups = {"brief": 0, "standard": 1}[ctx["depth"]]
    out = []
    for row in ctx["participants"]:
        reaction = STUDY_POOL[row["ordinal"] % len(STUDY_POOL)]
        lines = LINES[reaction]
        answers = dict(zip(QUESTIONS, [f"'{_short(headline, 60)}' {lines[0]}", *lines[1:]]))
        out.append({
            "participant": row["participant"], "answers": answers, "reaction": reaction,
            "comprehension": {"confused": "misunderstood", "mixed": "partial", "negative": "partial"}.get(reaction, "understood"),
            "themes": THEMES[reaction], "concerns": CONCERNS.get(reaction, []),
            "misunderstanding": "Reads as an announcement, not an offer." if reaction == "confused" else None,
            "follow_ups": [{"question": "What would make it clearer?", "answer": "Say what is offered and for whom."}][:follow_ups],
        })
    return {"interviews": out}


def study_analysis(ctx: Context) -> dict:
    tallies = ctx["tallies"]
    slices = [s for s in tallies["by_dimension"] if s["dimension"] == "states" and s["distribution"]["denominator"]]
    if len(slices) < 2:
        slices = [s for s in tallies["by_dimension"] if s["dimension"] == "city_tiers" and s["distribution"]["denominator"]]
    slices.sort(key=lambda s: -s["distribution"]["rates"]["positive"])
    differences = []
    if len(slices) > 1:
        top, bottom = slices[0], slices[-1]
        differences.append(
            f"{top['label']} has the highest positive rate ({top['distribution']['rates']['positive']:.0%}) and {bottom['label']} "
            f"the lowest ({bottom['distribution']['rates']['positive']:.0%}) among these participants.")
    if tallies["misunderstandings"]:
        differences.append(f"The most common misunderstanding was '{tallies['misunderstandings'][0]['label']}'.")
    return {"group_differences": differences,
            "next_actions": ["State the offer and who it is for in the first line.", "Test the creative with real people in each state."],
            "evidence_gaps": ["No observed outcomes from real people.", "Slices are small and are not market segments."]}


def risk_check(ctx: Context) -> dict:
    aamod = demo_aamod.risk_findings(ctx)
    if aamod is not None:
        return {"findings": aamod}
    ad_by_id = {row["id"]: row["handle"] for row in ctx.get("ad_codes", [])}
    claims = ctx.get("claims") or []
    sensitive = next((c for c in claims if c["category"] in ("sensitivity", "symbol", "colour")), None)

    def refs(*ids: str) -> list[str]:
        return [ad_by_id[i] for i in ids if i in ad_by_id]

    findings, flagged_region = [], False
    for el in ctx["elements"]:
        text = el.get("text") or ""
        if el["kind"] in ("headline", "body", "cta", "tagline", "caption", "voiceover"):
            match = HARD_CLAIM.search(text)
            if match:
                quote = match.group(0)
                if MEDICAL.search(quote):
                    category, ids = "health_nutrition_claim", ("asci-1-1", "asci-1-5-d")
                    obs, why = "The text makes a health claim.", "A health claim may need scientific evidence before it runs."
                elif COMPARATIVE.search(quote):
                    category, ids = "comparative_claim", ("asci-4-1",)
                    obs, why = "The text makes a comparison.", "A comparison may need a stated basis and substantiation."
                else:
                    category, ids = "unsubstantiated_claim", ("asci-1-1", "asci-1-4")
                    obs, why = "The text makes an absolute or numeric claim.", "An absolute claim may need substantiation before it runs."
                findings.append({
                    "element": el["handle"], "quote": quote, "category": category, "observation": obs, "interpretation": why,
                    "suggested_fix": "Qualify the claim or remove it unless it can be substantiated.", "ad_codes": refs(*ids), "claims": [],
                })
        elif text and re.search(r"\b(child|children|kid|kids|boy|girl)\b", text, re.IGNORECASE):
            findings.append({
                "element": el["handle"], "quote": None, "category": "children_safety",
                "observation": "The element shows or describes children.",
                "interpretation": "Content with children may need a check for safety and for how it is addressed to them.",
                "suggested_fix": None, "ad_codes": refs("asci-3-2"), "claims": [],
            })
        elif text and sensitive and not flagged_region:
            flagged_region = True
            findings.append({
                "element": el["handle"], "quote": None, "category": "regional_sensitivity",
                "observation": "The element carries a visual that a region claim marks as sensitive.",
                "interpretation": "This may read differently in the region; a native reviewer should look at it.",
                "suggested_fix": None, "ad_codes": [], "claims": [sensitive["handle"]],
            })
    return {"findings": findings}


AUDIENCE_RESPONDERS = {
    "quick-read-v1": quick_read,
    "audience-study-interviews-v1": study_interviews,
    "audience-study-analysis-v1": study_analysis,
    "risk-check-v1": risk_check,
}


def _with_sessions() -> None:
    """The Live Focus Group, Buzz Simulator and Message Check responders (lab-t3) join the Audience Lab ones."""
    from app.fixtures.lab_t3_llm import RESPONDERS as SESSIONS

    AUDIENCE_RESPONDERS.update(SESSIONS)


def fixture_provider() -> Any:
    """The demo provider with the Audience Lab responders added to the existing ones."""
    from app.fixtures.demo_llm import RESPONDERS
    from app.llm.fixture import FixtureLLMProvider

    _with_sessions()
    return FixtureLLMProvider({**RESPONDERS, **AUDIENCE_RESPONDERS})
