"""Demo-mode fixtures for the fictional Aamod journey (festive sweets, Diwali 2027): the fixture files, the plan of the
adapted versions, and the deterministic "model" outputs that make a demo project work with no provider and no network.

Everything here is hand-written and labelled. Nothing is research and nothing was reviewed by a native speaker: the
Tamil, Malayalam and Bengali lines are drafted by the demo author, and the Tamil, Malayalam and Bengali phrasebook says
so wherever it is shown (the workflows add "Demo fixture output, not a live model response.").

The responders are plugged into the existing demo providers (`demo_studio`, `audience_llm`, `demo_llm`) and answer ONLY
for the Aamod copy; for any other input they return None, which the fixture provider reports as "No demo fixture for
this input" instead of inventing text. Back-translations are literal English renderings written by hand. Severity,
verdicts and confidence are never set here: code computes them from what these responders return.
"""

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent / "omnicult_demo"
DEMO_NOTE = "Demonstration fixture of a fictional brand. Not a live result."
BRIEF_PRIMARY_MESSAGE = "Home-style festive sweets, ready to gift and delivered before the festival day."
CLAIM_QUOTE = "महाराष्ट्रातील सर्वोत्तम फराळ टिन"  # the planted superiority claim, as written on the end card and key visual
LEGIBILITY_QUOTE = "ग्राहकांच्या पसंतीनुसार"
TAGLINE = "Every bond, a little sweeter."


@lru_cache
def load(name: str) -> dict[str, Any]:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def file_bytes(relative: str) -> bytes:
    """A fixture file by its path under `creative/mh_original/` or `brand/` (as the fixture JSON names it)."""
    return (ROOT / relative).read_bytes()


# --- the adapted versions ---------------------------------------------------------------------------------------


class Plan(NamedTuple):
    region: str
    name: str
    language: str
    language_name: str
    script: str
    tone: Mapping[str, int]
    small_print: str  # replaces the unsourced superiority claim: a true product fact (net weight), per the claims policy
    festival_term: str | None  # the sourced festival day the delivery promise names once a Tweak Chip is applied


ADAPTATIONS: tuple[Plan, ...] = (
    Plan("IN-TN", "Tamil Nadu", "ta", "Tamil", "Taml",
         {"formality": 55, "code_mixing": 35, "urban_rural": 65, "playfulness": 60, "energy": 65},
         "*நிகர எடை 750 கிராம்.", "தீபாவளி"),
    Plan("IN-KL", "Kerala", "ml", "Malayalam", "Mlym",
         {"formality": 55, "code_mixing": 30, "urban_rural": 60, "playfulness": 55, "energy": 60},
         "*മൊത്തം തൂക്കം 750 ഗ്രാം.", None),
    Plan("IN-WB", "West Bengal", "bn", "Bengali", "Beng",
         {"formality": 50, "code_mixing": 35, "urban_rural": 65, "playfulness": 60, "energy": 60},
         "*নিট ওজন 750 গ্রাম।", "কালীপুজো"),
)
ORIGINAL_FESTIVAL_TERM = "भाऊबीज"
VIDEO_ID = "demo-creative-aamod-mh-video"
KEYVISUAL_ID = "demo-creative-aamod-mh-key-visual"
SMALL_PRINT_IDS = ("mh-vid-small-print", "mh-kv-small-print")
CHIP_ELEMENT_IDS = ("mh-vid-cta-hook", "mh-kv-cta-hook")
# Product names and the brand label are transcreated too (to show the Brand Glossary spelling applied), the rest of the
# lines are the copy that is regional. The small print is excluded: a person rewrites it (the claim must not travel).
TRANSCREATE_KINDS = ("headline", "body", "cta", "caption")


# --- phrasebook: Marathi source -> language -> (copy, literal back-translation, why, claim statements it may cite) ----


class Line(NamedTuple):
    copy: str
    back: str
    why: str
    cites: tuple[str, ...] = ()


_BHAU = ("Bhau Beej is the Marathi name of the sibling day after Diwali; it is not carried over, and no day is assumed for the "
         "region. ")
_FARAL = "Faral is the Maharashtrian name for the Diwali snack assortment. "
_AAJI = "'Aaji' (grandmother) becomes the local word. "
_NAME = "The product name is transliterated with the Brand Glossary spelling and never translated."
_UNSOURCED = ("Carried over in meaning and moved to the region: the superiority claim still names no source, sample or date. "
              "Risk Check will flag it. Edit or remove it before launch.")
_LABEL = "A label, rendered in the target script; the English brand words stay in Latin."

PHRASEBOOK: dict[str, dict[str, Line]] = {
    "दिवाळी म्हणजे फराळ!": {
        "ta": Line("தீபாவளி என்றால் பலகாரம்!", "Deepavali means palagaram (festive snacks)!",
                   _FARAL + "'பலகாரம்' is the everyday Tamil word for festive snacks, and the festival is Deepavali in Tamil Nadu.",
                   ("Diwali is celebrated between",)),
        "ml": Line("ദീപാവലി എന്നാൽ പലഹാരം!", "Deepavali means palaharam (festive snacks)!",
                   _FARAL + "'പലഹാരം' is the everyday Malayalam word for snacks and sweets. The evidence names no Kerala Diwali snack, so the line stays general."),
        "bn": Line("দীপাবলি মানেই মিষ্টিমুখ!", "Deepabali means sweets all around!",
                   _FARAL + "'মিষ্টিমুখ' is the Bengali idiom for sharing sweets at a festival. West Bengal marks the Diwali days with Kali Puja.",
                   ("Kali Puja is celebrated during Diwali",)),
    },
    "आजीच्या हातची चव": {
        "ta": Line("பாட்டியின் கைப்பக்குவம்", "Grandma's cooking touch",
                   _AAJI + "'கைப்பக்குவம்' is the Tamil idiom for the flavour of someone's own cooking."),
        "ml": Line("അമ്മൂമ്മയുടെ കൈപ്പുണ്യം", "Grandma's cooking touch",
                   _AAJI + "'കൈപ്പുണ്യം' is the Malayalam idiom for the good taste that comes from a person's own hands."),
        "bn": Line("ঠাকুমার হাতের স্বাদ", "The taste of Grandma's hands",
                   _AAJI + "'হাতের স্বাদ' is the Bengali idiom for the taste of someone's own cooking."),
    },
    "घरच्या चवीचा फराळ, आता एकाच टिनमध्ये": {
        "ta": Line("வீட்டுச் சுவையில் பலகாரம், இப்போது ஒரே டின்னில்", "Palagaram with the taste of home, now in one tin",
                   "Faral becomes 'பலகாரம்'. The tin is unchanged; only what is inside follows the region."),
        "ml": Line("വീട്ടുരുചിയുള്ള പലഹാരങ്ങൾ, ഇനി ഒരൊറ്റ ടിന്നിൽ", "Snacks with the taste of home, now in a single tin",
                   "Faral becomes 'പലഹാരങ്ങൾ' (snacks). The tin is unchanged; only what is inside follows the region."),
        "bn": Line("ঘরোয়া স্বাদের মিষ্টি, এখন এক টিনেই", "Sweets with the taste of home, now in just one tin",
                   "Faral becomes 'মিষ্টি' (sweets). The tin is unchanged; only what is inside follows the region."),
    },
    "भाऊबीजेला द्या गोड भेट": {
        "ta": Line("இந்தப் பண்டிகைக்கு இனிய பரிசைக் கொடுங்கள்", "Give a sweet gift this festival", _BHAU + "The line speaks of the festival."),
        "ml": Line("ഈ ഉത്സവത്തിന് മധുരമുള്ള സമ്മാനം നൽകൂ", "Give a sweet gift this festival", _BHAU + "The line speaks of the festival."),
        "bn": Line("এই উৎসবে মিষ্টি উপহার দিন", "Give a sweet gift this festival", _BHAU + "The line speaks of the festival."),
    },
    "दिवाळी आली की घरभर फराळाचा सुगंध दरवळतो.": {
        "ta": Line("தீபாவளி வந்தால் வீடு முழுக்க பலகார மணம் வீசும்.", "When Deepavali comes, the aroma of palagaram fills the whole house.",
                   _FARAL + "The festival is Deepavali in Tamil Nadu.", ("Diwali is celebrated between",)),
        "ml": Line("ദീപാവലി വന്നാൽ വീടു നിറയെ പലഹാരത്തിന്റെ മണം പരക്കും.", "When Deepavali comes, the aroma of snacks spreads through the house.",
                   _FARAL + "The line stays general."),
        "bn": Line("দীপাবলি এলেই সারা বাড়ি মিষ্টির গন্ধে ভরে ওঠে।", "As soon as Deepabali comes, the whole house fills with the smell of sweets.",
                   _FARAL + "Sweets are the word that fits Bengali festivals.", ("Kali Puja is celebrated during Diwali",)),
    },
    "आजीच्या हातची चकली, करंजी, बेसनाचे लाडू…": {
        "ta": Line("பாட்டி கையால் செய்த அதிரசம், உக்காரை, லட்டு…", "Adhirasam, ukkarai and laddu made by Grandma's own hands…",
                   "Chakli, karanji and besan laddoo are Maharashtrian. Adhirasam is a Tamil Nadu Deepavali sweet in the evidence; ukkarai and laddu are the model's choice, to be confirmed by a Tamil reviewer.",
                   ("adirasam",)),
        "ml": Line("അമ്മൂമ്മയുടെ സ്വന്തം പലഹാരങ്ങൾ, ഒന്നിനൊന്ന് മധുരം…", "Grandma's own snacks, each sweeter than the last…",
                   "Chakli, karanji and besan laddoo are Maharashtrian. The Kerala evidence names no Diwali snack, so the line stays general instead of inventing one."),
        "bn": Line("ঠাকুমার নিজের হাতের রসগোল্লা, সন্দেশ, মিষ্টি দই…", "Grandma's own rosogolla, sandesh, mishti doi…",
                   "Chakli, karanji and besan laddoo are Maharashtrian. Rosogolla, sandesh and mishti doi are well-known Bengali sweets; a Bengali reviewer should confirm the selection."),
    },
    "तीच घरची चव, आता आमोद फेस्टिव्ह टिनमध्ये.": {
        "ta": Line("அதே வீட்டுச் சுவை, இப்போது ஆமோத் ஃபெஸ்டிவ் டின்னில்.", "That same taste of home, now in the Aamod Festive Tin.", _NAME),
        "ml": Line("അതേ വീട്ടുരുചി, ഇപ്പോൾ ആമോദ് ഫെസ്റ്റിവ് ടിന്നിൽ.", "That same taste of home, now in the Aamod Festive Tin.", _NAME),
        "bn": Line("সেই একই ঘরোয়া স্বাদ, এখন আমোদ ফেস্টিভ টিনে।", "That same taste of home, now in the Aamod Festive Tin.", _NAME),
    },
    "या भाऊबीजेला, आपल्या माणसांना द्या गोड भेट.": {
        "ta": Line("இந்தப் பண்டிகையில் உங்கள் அன்பானவர்களுக்கு இனிய பரிசைக் கொடுங்கள்.", "This festival, give your loved ones a sweet gift.",
                   "'आपल्या माणसांना' (to our own people) is an idiom; 'அன்பானவர்கள்' (loved ones) carries the same warmth. " + _BHAU),
        "ml": Line("ഈ ഉത്സവത്തിന് പ്രിയപ്പെട്ടവർക്ക് മധുരമുള്ള സമ്മാനം നൽകൂ.", "This festival, give your dear ones a sweet gift.",
                   "'आपल्या माणसांना' (to our own people) is an idiom; 'പ്രിയപ്പെട്ടവർ' (dear ones) carries the same warmth. " + _BHAU),
        "bn": Line("এই উৎসবে আপনজনদের হাতে তুলে দিন মিষ্টি উপহার।", "This festival, place a sweet gift in the hands of your own people.",
                   "'আপনজন' is the Bengali word for one's own people, the closest match to 'आपल्या माणसांना'. " + _BHAU),
    },
    "दिवाळीच्या हार्दिक शुभेच्छा!": {
        "ta": Line("தீபாவளி நல்வாழ்த்துகள்!", "Deepavali good wishes!", "The standard Deepavali greeting from the Brand Glossary.",
                   ("Diwali is celebrated between",)),
        "ml": Line("ദീപാവലി ആശംസകൾ!", "Deepavali greetings!", "The greeting from the Brand Glossary. Whether a Diwali greeting is the right one in Kerala is a Market Lens question."),
        "bn": Line("শুভ দীপাবলি!", "Happy Deepabali!", "The greeting from the Brand Glossary. In West Bengal the main festival of these days is Kali Puja.",
                   ("Kali Puja is celebrated during Diwali",)),
    },
    "भाऊबीजेपूर्वी घरपोच": {
        "ta": Line("பண்டிகைக்கு முன் வீடு தேடி வரும்", "Comes to your home before the festival",
                   _BHAU + "The delivery promise is made festival-neutral; a Tweak Chip can name the Tamil Nadu festival day from the evidence."),
        "ml": Line("ഉത്സവത്തിനു മുമ്പ് വീട്ടിലെത്തും", "Reaches home before the festival",
                   _BHAU + "The Kerala evidence names Onam, which falls outside this campaign's dates, so no specific day is proposed."),
        "bn": Line("উৎসবের আগেই বাড়ি পৌঁছে যাবে", "Will reach home before the festival",
                   _BHAU + "The delivery promise is made festival-neutral; a Tweak Chip can name the West Bengal festival day from the evidence."),
    },
    "आजच ऑर्डर करा · Order now": {
        "ta": Line("இன்றே ஆர்டர் செய்யுங்கள் · Order now", "Order today · Order now", "A direct call to action; the English 'Order now' stays as in the original."),
        "ml": Line("ഇന്നുതന്നെ ഓർഡർ ചെയ്യൂ · Order now", "Order today · Order now", "A direct call to action; the English 'Order now' stays as in the original."),
        "bn": Line("আজই অর্ডার করুন · Order now", "Order today · Order now", "A direct call to action; the English 'Order now' stays as in the original."),
    },
    "Aamod Festive Tin": {
        "ta": Line("ஆமோத் ஃபெஸ்டிவ் டின்", "Aamod Festive Tin", _NAME),
        "ml": Line("ആമോദ് ഫെസ്റ്റിവ് ടിൻ", "Aamod Festive Tin", _NAME),
        "bn": Line("আমোদ ফেস্টিভ টিন", "Aamod Festive Tin", _NAME),
    },
    "Aamod Festive Tin*": {
        "ta": Line("ஆமோத் ஃபெஸ்டிவ் டின்*", "Aamod Festive Tin*", _NAME),
        "ml": Line("ആമോദ് ഫെസ്റ്റിവ് ടിൻ*", "Aamod Festive Tin*", _NAME),
        "bn": Line("আমোদ ফেস্টিভ টিন*", "Aamod Festive Tin*", _NAME),
    },
    "*ग्राहकांच्या पसंतीनुसार महाराष्ट्रातील सर्वोत्तम फराळ टिन.": {
        "ta": Line("*வாடிக்கையாளர் விருப்பத்தின்படி தமிழ்நாட்டின் சிறந்த பலகார டின்.", "*Tamil Nadu's best palagaram tin, per customer preference.", _UNSOURCED),
        "ml": Line("*ഉപഭോക്താക്കളുടെ ഇഷ്ടപ്രകാരം കേരളത്തിലെ ഏറ്റവും മികച്ച പലഹാര ടിൻ.", "*Kerala's best snack tin, by customers' preference.", _UNSOURCED),
        "bn": Line("*গ্রাহকদের পছন্দ অনুযায়ী পশ্চিমবঙ্গের সেরা মিষ্টির টিন।", "*West Bengal's best sweets tin, according to customers' preference.", _UNSOURCED),
    },
    "Fictional brand · Omnicult demo creative": {
        "ta": Line("கற்பனை பிராண்ட் · Omnicult டெமோ படைப்பு", "Fictional brand · Omnicult demo creative", _LABEL),
        "ml": Line("സാങ്കൽപ്പിക ബ്രാൻഡ് · Omnicult ഡെമോ ക്രിയേറ്റീവ്", "Fictional brand · Omnicult demo creative", _LABEL),
        "bn": Line("কাল্পনিক ব্র্যান্ড · Omnicult ডেমো ক্রিয়েটিভ", "Fictional brand · Omnicult demo creative", _LABEL),
    },
}
HEADLINES = frozenset({"दिवाळी म्हणजे फराळ!", *(v.copy for v in PHRASEBOOK["दिवाळी म्हणजे फराळ!"].values())})


def _claim(claims: list[Mapping[str, Any]], needles: tuple[str, ...]) -> list[str]:
    """Handles of the supplied claims whose statement contains a needle. Only supplied handles are ever cited."""
    found: list[str] = []
    for needle in needles:
        hit = next((c["handle"] for c in claims if needle.casefold() in c["statement"].casefold()), None)
        if hit and hit not in found:
            found.append(hit)
    return found


def transcreate_lines(ctx: Mapping[str, Any]) -> dict[str, Any] | None:
    """`transcreate-lines-v1` for the Aamod copy; None when any requested line is not in the phrasebook."""
    out = []
    for handle, line in ctx["lines"].items():
        row = PHRASEBOOK.get(line["text"].strip(), {}).get(ctx["language"])
        if row is None:
            return None
        out.append({"line": handle, "regional_copy": row.copy, "back_translation": row.back, "explanation": row.why,
                    "claims": _claim(ctx["claims"], row.cites), "preserved_terms": []})
    return {"lines": out}


# --- Tweak Chips --------------------------------------------------------------------------------------------------

# region code -> (current festival-neutral line, word to replace, festival word, claim it rests on, title, reason, effect)
CHIPS: dict[str, tuple[str, str, str, str, str, str, str]] = {
    "IN-TN": ("பண்டிகைக்கு முன் வீடு தேடி வரும்", "பண்டிகைக்கு", "தீபாவளிக்கு", "Diwali is celebrated between",
              "Name Deepavali in the delivery promise",
              "The Tamil Nadu evidence has Diwali (Deepavali) celebrated between mid-October and mid-November, inside this campaign's "
              "dates (4 October to 1 November 2027), so the promise can name it. Bhau Beej is the Marathi sibling day and is not used.",
              "Ties the delivery promise to a festival day the evidence supports in Tamil Nadu; one word longer."),
    "IN-WB": ("উৎসবের আগেই বাড়ি পৌঁছে যাবে", "উৎসবের", "কালীপুজোর", "Kali Puja is celebrated during Diwali",
              "Name Kali Puja in the delivery promise",
              "The West Bengal evidence says Kali Puja is celebrated during Diwali and is a major festival there. Naming it replaces "
              "Bhau Beej, which is the Marathi name for the sibling day.",
              "Ties the delivery promise to the festival the evidence supports in West Bengal; one word longer."),
}


@lru_cache
def _known_texts() -> frozenset[str]:
    """Every Aamod line a user can select: the Marathi source lines, their regional copies and the chip results."""
    copies = {line.copy for row in PHRASEBOOK.values() for line in row.values()}
    chipped = {c[0].replace(c[1], c[2]) for c in CHIPS.values()}
    return frozenset({*PHRASEBOOK, *copies, *chipped, *(p.small_print for p in ADAPTATIONS)})


def tweak_chips(ctx: Mapping[str, Any]) -> dict[str, Any] | None:
    """`tweak-chips-v1` for the festival-neutral delivery promise of an adapted Aamod version; None for any other text."""
    value = str(ctx["element"]["value"]).strip()
    code = next((c for c in CHIPS if f"({c})" in str(ctx.get("region", ""))), None)
    if code is not None and CHIPS[code][0] == value:
        _, old, new, needle, title, reason, effect = CHIPS[code]
        handles = _claim(ctx["claims"], (needle,))
        if not handles:
            return {"chips": []}  # no supplied claim to cite, so no chip: the fixture never invents evidence
        return {"chips": [{"title": title, "operation_type": "swap_reference", "from_text": old, "to_text": new,
                           "reason": reason, "claims": handles, "expected_effect": effect}][: ctx["count"]]}
    if value in _known_texts():
        return {"chips": []}  # a line of the Aamod journey with nothing evidence-backed to propose: an honest empty answer
    return None


# --- Quick Read -----------------------------------------------------------------------------------------------------

# Sentiment by panel ordinal, per state: the Marathi original and its Tamil Nadu and West Bengal adaptations read well; the
# Kerala version is festival-neutral because the Kerala evidence names no day inside the campaign dates, and reads weaker.
PATTERNS: dict[str, tuple[str, ...]] = {
    "Maharashtra": ("positive", "positive", "positive", "mixed", "positive", "neutral", "positive", "positive", "mixed", "positive", "neutral", "positive"),
    "Tamil Nadu": ("positive", "positive", "mixed", "positive", "positive", "neutral", "positive", "mixed", "positive", "positive", "neutral", "positive"),
    "Kerala": ("mixed", "positive", "neutral", "mixed", "positive", "neutral", "confused", "positive", "mixed", "neutral", "positive", "mixed"),
    "West Bengal": ("positive", "positive", "mixed", "positive", "neutral", "positive", "positive", "mixed", "positive", "neutral", "positive", "mixed"),
}


def sentiment_for(ctx: Mapping[str, Any], row: Mapping[str, Any]) -> str | None:
    """The sentiment of one synthetic participant for an Aamod creative, or None (use the generic fixture)."""
    headline = (ctx.get("creative") or {}).get("headline")
    pattern = PATTERNS.get(row["state"])
    if headline not in HEADLINES or pattern is None:
        return None
    return pattern[row["ordinal"] % len(pattern)]


# --- Risk Check -----------------------------------------------------------------------------------------------------


def risk_findings(ctx: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """`risk-check-v1` findings for an Aamod creative: the planted superiority claim (anchored where it appears), its
    legibility, and the Tamil spelling of the brand name. None when the elements are not Aamod's (use the generic fixture).
    Severity and "blocks Go" are decided by code (risk-rules-v1) from the ad-code clauses cited here, not by this file."""
    rows = [(r["handle"], r.get("text") or "") for r in ctx["elements"]]
    if not any(TAGLINE in text for _, text in rows):
        return None
    ad = {a["id"]: a["handle"] for a in ctx.get("ad_codes", [])}
    findings: list[dict[str, Any]] = []
    first_claim = first_name = True
    for handle, text in rows:
        if CLAIM_QUOTE in text:
            findings.append({
                "element": handle, "quote": CLAIM_QUOTE, "category": "comparative_claim",
                "observation": "The small print says this is the best faral tin in Maharashtra, according to customer preference.",
                "interpretation": "A 'best in the state' claim may need a stated basis: who was asked, how many, and when. No source, sample "
                                  "or date is shown, and the Brand Kit's claims policy forbids superiority claims without independent substantiation.",
                "suggested_fix": "Remove the claim, or substantiate it and show the source and date next to it.",
                # the first occurrence (the end card) cites the ASCI clauses; the repeat on the key visual rests on it
                "ad_codes": [ad[i] for i in ("asci-1-1", "asci-1-2") if i in ad] if first_claim else [], "claims": []})
            if first_claim:
                findings.append({
                    "element": handle, "quote": LEGIBILITY_QUOTE, "category": "disclaimer_issue",
                    "observation": "The qualifying line is set very small, about 1.6% of the frame height, in the lower fifth of the end card.",
                    "interpretation": "Small print that carries the basis of a claim may be hard to read on a phone, and platform overlays can "
                                      "cover the lower part of a vertical frame.",
                    "suggested_fix": "Enlarge the line or move the basis next to the claim.", "ad_codes": [], "claims": []})
            first_claim = False
        elif "ஆமோத்" in text and first_name:
            first_name = False
            findings.append({
                "element": handle, "quote": "ஆமோத்", "category": "language_ambiguity",
                "observation": "The brand name is written ஆமோத் in Tamil script.",
                "interpretation": "ஆமோத் is close to the Tamil word ஆமோதம் (approval). The Brand Glossary treats this as a neutral word, but a Tamil "
                                  "reviewer may want to confirm how the name reads aloud.",
                "suggested_fix": None, "ad_codes": [], "claims": []})
    return findings


# --- Creative X-Ray (re-run in a demo project) ------------------------------------------------------------------------

_XRAY_NOTES = {  # a word in a transcript segment -> (observation, category, interpretation)
    "फराळ": ("The voice-over speaks of faral, the snack assortment of Diwali.", "food",
             "'Faral' is a Marathi word for the Diwali snack assortment; it ties the creative to Maharashtra."),
    "आजीच्या": ("The voice-over names chakli, karanji and besan laddoos made by a grandmother.", "food",
               "The items named are the Maharashtrian faral set; other regions' Diwali snacks differ."),
    "भाऊबीज": ("The voice-over names Bhau Beej, the sibling day after Diwali.", "festival",
              "Bhau Beej is the Marathi name and framing of the day; other states use other names and customs."),
}


def xray_scenes(ctx: Mapping[str, Any]) -> dict[str, Any] | None:
    """`xray-scenes-v1` for the Aamod film: timing from the fixture, and only observations that rest on a transcript segment
    (a demo project has no vision model, so visual fields would be discarded by the workflow)."""
    creative = ctx.get("creative") or {}
    transcript = ctx.get("transcript") or []
    if creative.get("kind") != "video" or not transcript or not any("आमोद" in t["text"] or "फराळ" in t["text"] for t in transcript):
        return None
    scenes = []
    for scene in load("creative_mh_original.json")["creatives"][0]["scenes"]:
        inside = [t for t in transcript if t.get("start_ms") is not None and scene["start_ms"] <= t["start_ms"] < scene["end_ms"]]
        observations, readings = [], []
        for segment in inside:
            for word, (text, category, reading) in _XRAY_NOTES.items():
                if word in segment["text"]:
                    ref = f"o{len(observations) + 1}"
                    observations.append({"ref": ref, "text": text, "category": category, "evidence": [segment["id"]]})
                    readings.append({"text": reading, "based_on": [ref], "category": category})
        scenes.append({"start_ms": scene["start_ms"], "end_ms": scene["end_ms"], "observations": observations,
                       "interpretations": readings})
    return {"scenes": scenes}
