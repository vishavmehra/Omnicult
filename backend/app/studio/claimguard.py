"""Claim Guard rules (feature 27), version claim-guard-rules-v1. Pure, deterministic code: no model, no network, no database.

What it does. It reads the text of a creative, finds wording that makes a claim a person should review (superiority,
comparison, price, health, guarantee, financial), checks each claim against the Brand Kit claims policy, the evidence the
campaign holds, and the public ASCI ad-code index, and grades it. A finding is a warning for human review. It is never a
verdict that the wording breaks a rule, and never clearance: nothing here can say that a creative is compliant.

Wording rules come first and need no model. They cover English and the five languages of the demo markets (Hindi and
Marathi in Devanagari, Tamil, Malayalam, Bengali). A pattern is a stem: Indic words carry suffixes, so only the start of a
word is guarded. Matching is by wording, so a person decides whether a match is a claim; each rule states how certain it is.

Severity follows the same shape as Risk Check (`analytics.risk_rules`, which supplies the levels, the category table with
the ad-code topics that fit each category, the English hard-claim patterns and the applied-rule record). The steps here:

  G1 base       the claim kind's base level (KIND_RULES).
  G2 hard word  +1 when the wording is absolute ("best", "No. 1", "guaranteed"), by the pattern table or, for English,
                by `risk_rules.claim_features`.
  G3 policy     +1 when the Brand Kit claims policy, or the brand's prohibited terms, forbids this kind of claim.
  G4 basis      +1 when a basis is named ("according to customers") but no source, sample or date is shown near it.
  G5 price      +1 when a price in the copy differs from the product price in the Campaign Brief.
  G6 ceiling    never above high.
  G7 blocks Go  true at high severity: the claim would hold a Go verdict until a person reviews it.

Evidence never lowers a severity here. It is listed beside the claim, so the reviewer sees what the campaign holds and
decides whether it covers this exact wording.
"""

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.analytics.risk_rules import CATEGORY_RULES, LEVELS, AppliedRule, Severity, claim_features, scan_patterns, topics_fit
from app.reference.ad_codes import AdCodeEntry, entries_by_id

RULES_VERSION = "claim-guard-rules-v1"
ClaimKind = Literal["superiority", "comparative", "price", "health", "guarantee", "financial"]
KINDS: tuple[ClaimKind, ...] = ("superiority", "comparative", "price", "health", "guarantee", "financial")
Level = Literal["low", "moderate", "high"]
INDEX_NOTE = "The ad-code index is a partial set of public ASCI clauses. It has no clause written for financial claims."

# kind -> (Risk Check category whose ad-code topics fit it, base level, curated ad-code ids, what the wording is)
KIND_RULES: dict[str, tuple[str, Severity, tuple[str, ...], str]] = {
    "superiority": ("comparative_claim", "medium", ("asci-1-1", "asci-1-2", "asci-1-6"),
                    "Wording that says the product is the best, first or leading."),
    "comparative": ("comparative_claim", "medium", ("asci-4-1", "asci-disc-comparative", "asci-1-1"),
                    "Wording that compares the product with others."),
    "price": ("unsubstantiated_claim", "low", ("asci-1-5-a", "asci-1-5-c", "asci-1-1"),
              "A price, a discount or an offer."),
    "health": ("health_nutrition_claim", "medium", ("asci-1-5-d", "asci-fb-2", "asci-fb-5"),
               "Wording about health, nutrition or the body."),
    "guarantee": ("unsubstantiated_claim", "medium", ("asci-1-1", "asci-1-4", "asci-1-5"),
                  "A guarantee, a promise or an absolute assurance."),
    "financial": ("unsubstantiated_claim", "medium", ("asci-1-1", "asci-1-4"),
                  "Wording about returns, investment, interest or loans."),
}
POLICY_WORDS: dict[str, tuple[str, ...]] = {
    "superiority": ("superiority", "leadership", "no. 1", "no.1", "number one", "best", "leader"),
    "comparative": ("comparative", "comparison", "competitor", "better than", "superiority"),
    "price": ("price", "pricing", "discount", "offer", "free"),
    "health": ("health", "nutrition", "wellness", "medical", "diet"),
    "guarantee": ("guarantee", "warranty", "promise", "risk-free"),
    "financial": ("financial", "finance", "investment", "returns", "loan"),
}
RISK_PATTERN_KIND = {"absolute_guarantee": "guarantee", "medical_claim": "health", "superlative_comparison": "superiority"}

# --- the wording rules ------------------------------------------------------------------------------------------------

INDIC = "ऀ-ൿ"  # every Indic block the markets use
HEADS = {
    "latin": (r"(?<!\w)(?:", r")(?!\w)"),
    "indic": (rf"(?<![\w{INDIC}])(?:", ")"),
    "raw": ("(?:", ")"),
    "symbol": (rf"(?<![A-Za-z{INDIC}])(?:", ")"),
}


@dataclass(frozen=True)
class Rule:
    id: str
    kind: ClaimKind
    pattern: re.Pattern[str]
    strength: Literal["absolute", "soft"]
    certainty: Level


def _rule(rule_id: str, kind: ClaimKind, words: str, strength: Literal["absolute", "soft"], certainty: Level, *,
          mode: Literal["latin", "indic", "raw", "symbol"] = "indic") -> Rule:
    """`words` is a regex alternation. Latin words need a word edge on both sides; an Indic stem may take any suffix, so only
    its start is guarded; `raw` (a postposition that joins the word before it) and `symbol` (a currency sign) are guarded less."""
    head, tail = HEADS[mode]
    return Rule(rule_id, kind, re.compile(head + words + tail, re.IGNORECASE), strength, certainty)


RULES: tuple[Rule, ...] = (
    # superiority
    _rule("superiority.en", "superiority", r"best(?!\s+wishes)|no\.?\s?1|#1|number\s+one|finest|unbeatable|unmatched|unrival+ed|world[- ]class|"
          r"top[- ]rated|best[- ]selling|most\s+(?:loved|trusted|popular|preferred|recommended|awarded)|india'?s\s+(?:first|best|favou?rite)",
          "absolute", "high", mode="latin"),
    _rule("superiority.en.leading", "superiority", r"leading|leader|premier|number\s+1", "soft", "moderate", mode="latin"),
    _rule("superiority.deva", "superiority", r"सर्वोत्तम|सर्वश्रेष्ठ|सर्वोत्कृष्ट|बेस्ट|बेहतरीन|नंबर\s?(?:1|१|एक|वन)|क्रमांक\s?(?:1|१|एक)|नं\.?\s?(?:1|१)|"
          r"अव्वल|सबसे\s+(?:अच्छ|बेहतर|लोकप्रिय|भरोसेमंद|स्वादिष्ट|पसंदीदा)|सर्वात\s+(?:चांगल|उत्तम|उत्कृष्ट|लोकप्रिय|विश्वासार्ह|स्वादिष्ट|चविष्ट|आवडत)",
          "absolute", "high"),
    _rule("superiority.deva.leading", "superiority", r"अग्रगण्य|अग्रणी|नंबर\s?वन", "soft", "moderate"),
    _rule("superiority.taml", "superiority", r"மிகச்\s?சிறந்த|தலைசிறந்த|நம்பர்\s?(?:1|ஒன்|ஒன்று)|முதல்\s?தரம்|ஒப்பற்ற", "absolute", "high"),
    _rule("superiority.taml.generic", "superiority", r"சிறந்த|முன்னணி|முதன்மை", "soft", "moderate"),
    _rule("superiority.mlym", "superiority", r"ഏറ്റവും\s+(?:മികച്ച|നല്ല|മികവുറ്റ|ജനപ്രിയ)|നമ്പർ\s?(?:1|വൺ|ഒന്ന്)|ഒന്നാം\s?നമ്പർ", "absolute", "high"),
    _rule("superiority.mlym.generic", "superiority", r"മികച്ച|മികവുറ്റ|മുൻനിര", "soft", "moderate"),
    _rule("superiority.beng", "superiority", r"সেরা|সর্বশ্রেষ্ঠ|সর্বোত্তম|সবচেয়ে\s+(?:ভালো|ভাল|জনপ্রিয়|সুস্বাদু|বিশ্বস্ত)|এক\s?নম্বর|নম্বর\s?(?:1|১|ওয়ান)|নাম্বার\s?ওয়ান|অতুলনীয়",
          "absolute", "high"),
    _rule("superiority.beng.leading", "superiority", r"শীর্ষস্থানীয়", "soft", "moderate"),
    # comparative
    _rule("comparative.en", "comparative", r"better\s+than|than\s+(?:any|the\s+(?:others?|rest)|other|competitors?)|compared\s+(?:to|with)|unlike\s+(?:other|any)|"
          r"outperforms?|beats|vs\.?", "absolute", "high", mode="latin"),
    _rule("comparative.deva", "comparative", r"इतरांपेक्षा|बाकीच्यांपेक्षा|पेक्षा\s+(?:चांगल|उत्तम|जास्त|सरस)|दूसरों\s+से|अन्य\s+(?:ब्रांड|उत्पादों?)\s+से|से\s+(?:बेहतर|ज़्यादा|ज्यादा|बढ़िया)",
          "absolute", "moderate", mode="raw"),
    _rule("comparative.taml", "comparative", r"மற்ற(?:வற்றை|வர்களை)\s?விட|விட\s+(?:சிறந்த|சிறப்பான|சுவையான|மேலான)", "absolute", "moderate", mode="raw"),
    _rule("comparative.mlym", "comparative", r"മറ്റുള്ളവയെക്കാൾ|മറ്റെല്ലാറ്റിനേക്കാളും|നേക്കാൾ\s+(?:മികച്ച|നല്ല|രുചി)", "absolute", "moderate", mode="raw"),
    _rule("comparative.beng", "comparative", r"অন্যদের\s+(?:চেয়ে|থেকে)|(?:থেকে|চেয়ে)\s+(?:ভালো|ভাল|বেশি|সেরা|সুস্বাদু)", "absolute", "moderate", mode="raw"),
    # price
    _rule("price.symbol", "price", rf"(?:₹|rs\.?|inr|रु\.?|ரூ\.?|രൂപ|টাকা)\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:rupees|रुपये|रुपए|ரூபாய்|টাকা)|"
          r"\d+\s?%\s?(?:off|discount|cashback|सूट|सवलत)", "soft", "high", mode="symbol"),
    _rule("price.en", "price", r"free|discount|sale|offers?|deals?|cashback|coupon|lowest\s+price|cheapest|best\s+price|price\s+drop|no[- ]cost\s+emi|mrp",
          "soft", "moderate", mode="latin"),
    _rule("price.deva", "price", r"मोफत|मुफ्त|फ्री|सूट|सवलत|ऑफर|ऑफ़र|स्वस्त|सस्ता|कमी\s+किंमत|डिस्काउंट", "soft", "moderate"),
    _rule("price.taml", "price", r"இலவச|தள்ளுபடி|ஆஃபர்|ஆபர்|குறைந்த\s+விலை|விலை\s+குறைவு", "soft", "moderate"),
    _rule("price.mlym", "price", r"സൗജന്യ|കിഴിവ്|ഓഫർ|വിലക്കുറവ്|കുറഞ്ഞ\s+വില", "soft", "moderate"),
    _rule("price.beng", "price", r"বিনামূল্যে|ফ্রি|ছাড়|অফার|সস্তা|কম\s+দামে|মূল্যছাড়", "soft", "moderate"),
    # health
    _rule("health.en", "health", r"health(?:y|ier|ful)?|nutriti(?:ous|on)|immun(?:ity|e)|detox|sugar[- ]free|no\s+(?:added\s+)?sugar|zero\s+(?:sugar|fat|cholesterol)|"
          r"low[- ](?:fat|calorie|sugar|gi)|fat[- ]free|diabet(?:ic|es)|organic|preservative[- ]free|gluten[- ]free|antioxidants?|weight\s+(?:loss|management)|"
          r"cholesterol|protein[- ]rich|digestion|boosts?\s+\w+", "absolute", "high", mode="latin"),
    _rule("health.deva", "health", r"आरोग्य|स्वास्थ्य|सेहत|पौष्टिक|पोषक|पोषण|रोगप्रतिकार|इम्युनिटी|साखर\s?मुक्त|शुगर\s?फ्री|चरबी\s?मुक्त|मधुमेह|डायबिटीज|वजन\s?(?:कमी|घट)|औषधी",
          "absolute", "high"),
    _rule("health.taml", "health", r"ஆரோக்கிய|நோய்\s?எதிர்ப்பு|சத்தான|சர்க்கரை\s?இல்லாத|நீரிழிவு|எடை\s?குறைப்பு", "absolute", "high"),
    _rule("health.mlym", "health", r"ആരോഗ്യ|പ്രതിരോധശേഷി|പോഷക|പഞ്ചസാര\s?രഹിത|പ്രമേഹ|ഭാരം\s?കുറ", "absolute", "high"),
    _rule("health.beng", "health", r"স্বাস্থ্য|রোগ\s?প্রতিরোধ|পুষ্টি|চিনিমুক্ত|ডায়াবেটিস|ওজন\s?কমা", "absolute", "high"),
    # guarantee
    _rule("guarantee.en", "guarantee", r"guarantee[ds]?|risk[- ]free|money[- ]back|assured|100\s?%|lifetime|no\s+questions\s+asked|never\s+(?:fails?|disappoints?)|promise[ds]?",
          "absolute", "high", mode="latin"),
    _rule("guarantee.deva", "guarantee", r"गॅरंटी|गारंटी|ग्यारंटी|खात्रीशीर|खात्री|हमी|वचन", "absolute", "moderate"),
    _rule("guarantee.taml", "guarantee", r"உத்தரவாதம்|உறுதி", "absolute", "moderate"),
    _rule("guarantee.mlym", "guarantee", r"ഉറപ്പ്|ഗ്യാരണ്ടി|ഗ്യാരന്റി", "absolute", "moderate"),
    _rule("guarantee.beng", "guarantee", r"গ্যারান্টি|নিশ্চিত|নিশ্চয়তা|প্রতিশ্রুতি", "absolute", "moderate"),
    # financial
    _rule("financial.en", "financial", r"(?:guaranteed|high)\s+returns?|\d+\s?%\s+returns?|invest(?:ment|ing)?|interest[- ]free|loan|profit|earn\s+\S+|savings\s+of|save\s+up\s+to",
          "soft", "moderate", mode="latin"),
    _rule("financial.deva", "financial", r"गुंतवणूक|निवेश|परतावा|रिटर्न|कर्ज|व्याज|नफा|कमाई|बचत", "soft", "moderate"),
    _rule("financial.taml", "financial", r"முதலீடு|வட்டி|கடன்|லாபம்|சேமிப்பு", "soft", "moderate"),
    _rule("financial.mlym", "financial", r"നിക്ഷേപ|പലിശ|വായ്പ|ലാഭ|സമ്പാദ്യ", "soft", "moderate"),
    _rule("financial.beng", "financial", r"বিনিয়োগ|সুদ|ঋণ|মুনাফা|সঞ্চয়", "soft", "moderate"),
)

# A basis is named; a source, sample or date makes it checkable (ASCI 1.2 asks for source and date of research claims).
BASIS = re.compile(
    r"according\s+to|based\s+on|as\s+per|rated\s+by|survey|study|poll|testimonial|customers?\s+(?:say|voted|prefer|rate)|per\s+customer|"
    r"नुसार|पसंतीनुसार|सर्वेक्षण|सर्वे|अध्ययन|படி|கருத்துக்கணிப்பு|ഇഷ്ടപ്രകാരം|അനുസരിച്ച്|অনুযায়ী|সমীক্ষা",
    re.IGNORECASE,
)
SOURCED = re.compile(r"\b(?:19|20)\d\d\b|https?://|\bsource\b|\bn\s?=\s?\d+|\bsample\b|\d[\d,]*\s+(?:customers|respondents|people|ग्राहक)", re.IGNORECASE)
BOUNDARY = ".।!?\n|·;"


@dataclass(frozen=True)
class TextElement:
    id: str
    kind: str
    text: str
    language: str | None = None


@dataclass(frozen=True)
class PolicyInput:
    """What the Brand Kit says about claims: its policy lists and the brand's flat prohibited terms."""

    forbidden: Sequence[str] = ()
    allowed: Sequence[str] = ()
    prohibited_terms: Sequence[str] = ()


@dataclass
class Draft:
    """One finding before it is stored. `source` is `rule` (a wording pattern) or `model` (a verified model reading)."""

    element_id: str
    kind: str
    source: Literal["rule", "model"]
    rule_id: str | None
    quote: str
    start: int
    end: int
    phrase: str
    severity: Severity
    blocks_go: bool
    confidence: Level
    rules: list[AppliedRule]
    policy: dict[str, Any]
    evidence: dict[str, Any]
    basis: dict[str, Any]
    ad_code_ids: list[str]
    explanation: str
    limitations: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Stable identity of a finding in a version: reviews are kept against it, so a new check never loses one."""
        raw = "\x1f".join((self.source, self.element_id, self.kind, str(self.start), str(self.end), self.quote))
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


# --- digits and tokens ----------------------------------------------------------------------------------------------


def ascii_digits(text: str) -> str:
    """Digits of any Indic numbering system as ASCII digits, so ₹८९९ reads as 899."""
    return "".join(str(unicodedata.digit(c)) if unicodedata.category(c) == "Nd" else c for c in text)


def numbers_in(text: str) -> list[float]:
    found = re.findall(r"\d[\d,]*(?:\.\d+)?", ascii_digits(text))
    out = []
    for raw in found:
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def tokens(text: str) -> set[str]:
    """Lower-cased words of three or more characters, split on spaces and edge punctuation (marks stay in their word)."""
    words = (w.strip(".,;:!?()[]{}'\"*·|।—-–“”‘’").casefold() for w in text.split())
    return {w for w in words if len(w) >= 3}


# --- policy, evidence, basis --------------------------------------------------------------------------------------------


def policy_match(kind: str, phrase: str, policy: PolicyInput) -> dict[str, Any]:
    """Whether the Brand Kit forbids this kind of claim. `status` is forbidden, not_listed or no_policy."""
    words = POLICY_WORDS[kind]
    for item in policy.forbidden:
        if any(w in item.casefold() for w in words):
            return {"status": "forbidden", "rule": item, "source": "Brand Kit claims policy"}
    for term in policy.prohibited_terms:
        if term and term.casefold() in phrase.casefold():
            return {"status": "forbidden", "rule": f"Prohibited term: {term}", "source": "Brand prohibited terms"}
    if policy.forbidden or policy.allowed:
        return {"status": "not_listed", "rule": None, "source": "Brand Kit claims policy"}
    return {"status": "no_policy", "rule": None, "source": None}


def evidence_for(
    kind: str, phrase: str, quote: str, *, region_claims: Sequence[Mapping[str, Any]], brief_price: float | None, brief_currency: str | None,
    brief_sample: bool,
) -> dict[str, Any]:
    """What the campaign holds that bears on the claim. `status`: found (related evidence on file), mismatch (a price that
    differs from the brief) or none. Related is not the same as substantiating: a person decides whether it covers the wording."""
    items: list[dict[str, Any]] = []
    status = "none"
    if kind == "price" and brief_price is not None:
        wanted = [n for n in numbers_in(phrase) if n >= 1]
        label = f"{brief_currency or 'INR'} {brief_price:g}"
        note = " (a sample price)" if brief_sample else ""
        if wanted and any(abs(n - brief_price) < 0.005 for n in wanted):
            items.append({"source": "campaign_brief", "claim_id": None, "statement": f"The product price in the Campaign Brief is {label}{note}.",
                          "kind": None, "confidence": None, "note": "The price in the copy matches the brief. The brief is the team's own record, not independent evidence."})
            status = "found"
        elif wanted:
            items.append({"source": "campaign_brief", "claim_id": None, "statement": f"The product price in the Campaign Brief is {label}{note}.",
                          "kind": None, "confidence": None, "note": f"The copy states {', '.join(f'{n:g}' for n in wanted)}, which differs from the brief."})
            status = "mismatch"
    cue = tokens(quote)
    own = tokens(phrase) - cue
    for claim in region_claims:
        overlap = own & tokens(claim["statement"])
        if len(overlap) >= 2:
            items.append({"source": "region_claim", "claim_id": claim["id"], "statement": claim["statement"], "kind": claim["kind"],
                          "confidence": claim["confidence"], "note": f"Shares the words {', '.join(sorted(overlap)[:4])}. Related, not proof of this wording."})
            if status == "none":
                status = "found"
    return {"status": status, "items": items[:6]}


def basis_of(phrase: str, context: str) -> dict[str, Any]:
    """A named basis ("according to customers") and whether a source, sample or date is shown near it."""
    where = phrase if BASIS.search(phrase) else context
    named = BASIS.search(where)
    if named is None:
        return {"stated": False, "wording": None, "sourced": False}
    word = next((w for w in where.split() if named.group(0).casefold() in w.casefold()), named.group(0)).strip(".,;:!?*")
    return {"stated": True, "wording": word, "sourced": bool(SOURCED.search(ascii_digits(phrase)) or SOURCED.search(ascii_digits(context)))}


# --- grading -----------------------------------------------------------------------------------------------------


def grade(kind: str, *, absolute: bool, policy: dict[str, Any], basis: dict[str, Any], evidence: dict[str, Any]) -> tuple[Severity, bool, list[AppliedRule]]:
    category, base, _, _ = KIND_RULES[kind]
    level = LEVELS.index(base)
    rules = [AppliedRule("G1_base", "base", f"Base level for a {kind} claim: {base}.")]
    if absolute:
        level += 1
        rules.append(AppliedRule("G2_hard_wording", "+1", "The wording is absolute (it names no limit or condition)."))
    if policy["status"] == "forbidden":
        level += 1
        rules.append(AppliedRule("G3_policy", "+1", f"{policy['source']} forbids this kind of claim: {policy['rule']}"))
    if basis["stated"] and not basis["sourced"]:
        level += 1
        rules.append(AppliedRule("G4_basis", "+1", f"A basis is named ('{basis['wording']}') but no source, sample or date is shown near it."))
    if evidence["status"] == "mismatch":
        level += 1
        rules.append(AppliedRule("G5_price", "+1", "A price in the copy differs from the product price in the Campaign Brief."))
    level = min(level, 2)
    severity = LEVELS[level]
    blocks = severity == "high" and CATEGORY_RULES[category][1]
    if blocks:
        rules.append(AppliedRule("G7_blocks_go", "block", "High severity: the claim holds a Go verdict until a person reviews it."))
    return severity, blocks, rules


def ad_codes_for(kind: str) -> list[AdCodeEntry]:
    """The curated ad-code entries for a kind that exist in the index and fit the kind's Risk Check category."""
    category, _, ids, _ = KIND_RULES[kind]
    index = entries_by_id()
    return [index[i] for i in ids if i in index and topics_fit(category, index[i].topics)]


# --- extraction ---------------------------------------------------------------------------------------------------


def phrase_around(text: str, start: int, end: int, limit: int = 140) -> str:
    """The clause the match sits in: from the nearest sentence break before it to the nearest after it."""
    left = max((text.rfind(b, 0, start) for b in BOUNDARY), default=-1) + 1
    rights = [i for i in (text.find(b, end) for b in BOUNDARY) if i >= 0]
    right = min(rights) if rights else len(text)
    phrase = text[left:right].strip(" *\t\r\n")
    if len(phrase) > limit:
        lo = max(0, start - left - limit // 2)
        phrase = phrase[lo : lo + limit].strip()
    return phrase or text[start:end]


@dataclass(frozen=True)
class Hit:
    kind: str
    rule_id: str
    start: int
    end: int
    strength: str
    certainty: Level
    risk_ids: tuple[str, ...] = ()


def find_hits(text: str) -> list[Hit]:
    """Every wording match in `text`, longest first within a kind, with overlapping matches of one kind merged."""
    hits: list[Hit] = []
    for rule in RULES:
        for match in rule.pattern.finditer(text):
            if match.end() > match.start():
                hits.append(Hit(rule.kind, rule.id, match.start(), match.end(), rule.strength, rule.certainty))
    for pattern in scan_patterns(text):  # Risk Check's own English patterns: same wording, with the clauses they cite
        kind = RISK_PATTERN_KIND.get(pattern.pattern)
        if kind == "superiority" and "better" in text[pattern.start : pattern.end].casefold():
            kind = "comparative"
        if kind:
            hits.append(Hit(kind, f"risk-rules.{pattern.pattern}", pattern.start, pattern.end, "absolute", "high", pattern.ad_code_ids))
    kept: list[Hit] = []
    for hit in sorted(hits, key=lambda h: (h.kind, -(h.end - h.start), h.start)):
        clash = next((k for k in kept if k.kind == hit.kind and hit.start < k.end and k.start < hit.end), None)
        if clash is None:
            kept.append(hit)
        elif hit.strength == "absolute" and clash.strength == "soft" and hit.end - hit.start >= clash.end - clash.start:
            kept[kept.index(clash)] = hit
    return sorted(kept, key=lambda h: (h.start, h.end, h.kind))


def extract(
    elements: Iterable[TextElement], *, policy: PolicyInput, region_claims: Sequence[Mapping[str, Any]] = (), brief_price: float | None = None,
    brief_currency: str | None = None, brief_sample: bool = False,
) -> list[Draft]:
    """The rule pass over every text element: wording hits, graded in code."""
    drafts: list[Draft] = []
    for element in elements:
        text = element.text
        if not text.strip() or element.kind in ("logo", "packshot", "product", "image_region", "scene", "music"):
            continue
        for hit in find_hits(text):
            quote = text[hit.start : hit.end]
            phrase = phrase_around(text, hit.start, hit.end)
            drafts.append(build(element, hit.kind, "rule", hit.rule_id, quote, hit.start, hit.end, phrase, absolute=hit.strength == "absolute" or bool(claim_features(quote)),
                                certainty=hit.certainty, policy=policy, region_claims=region_claims, brief_price=brief_price,
                                brief_currency=brief_currency, brief_sample=brief_sample, context=text, extra_ids=hit.risk_ids))
    return drafts


def build(
    element: TextElement, kind: str, source: Literal["rule", "model"], rule_id: str | None, quote: str, start: int, end: int, phrase: str, *,
    absolute: bool, certainty: Level, policy: PolicyInput, region_claims: Sequence[Mapping[str, Any]], brief_price: float | None,
    brief_currency: str | None, brief_sample: bool, context: str, extra_ids: Sequence[str] = (), explanation: str | None = None,
) -> Draft:
    """Grade one claim: policy, evidence, basis, then the severity rules."""
    pol = policy_match(kind, phrase, policy)
    evidence = evidence_for(kind, phrase, quote, region_claims=region_claims, brief_price=brief_price, brief_currency=brief_currency, brief_sample=brief_sample)
    basis = basis_of(phrase, context)
    severity, blocks, rules = grade(kind, absolute=absolute, policy=pol, basis=basis, evidence=evidence)
    ids = list(dict.fromkeys([*extra_ids, *(e.id for e in ad_codes_for(kind))]))
    limitations = [INDEX_NOTE] if kind == "financial" else []
    return Draft(element.id, kind, source, rule_id, quote, start, end, phrase, severity, blocks, certainty, rules, pol, evidence, basis, ids,
                 explanation or KIND_RULES[kind][3], limitations)


def summarize(drafts: Sequence[Draft]) -> dict[str, Any]:
    by_severity = {level: sum(d.severity == level for d in drafts) for level in LEVELS}
    return {"total": len(drafts), "by_severity": by_severity, "by_kind": {k: sum(d.kind == k for d in drafts) for k in KINDS if any(d.kind == k for d in drafts)},
            "blocks_go": sum(d.blocks_go for d in drafts)}


def order(drafts: list[Draft], element_order: Mapping[str, int]) -> list[Draft]:
    """Highest severity first, then the creative's own element order, then position in the text."""
    return sorted(drafts, key=lambda d: (-LEVELS.index(d.severity), element_order.get(d.element_id, 0), d.start, d.kind))
