"""The labelled SAMPLE comments dataset behind Comment Pulse (no database, no network, no model).

Everything here is written for the demo, not collected: no ad account or YouTube channel stands behind it. The comments
react to the fictional Aamod Festive Tin campaign (the Marathi original film and the Tamil, Malayalam and Bengali
adaptations) and are written in Marathi, Tamil, Malayalam, Bengali, English and code-mixed text (a regional language with
English, in its own script or in Latin letters). The regional lines were drafted by the demo author and were not reviewed
by a native speaker. Comment text is the only thing here that the app shows as a quote.

The generator is seeded, so the same constants always give the same rows (refs, days and likes included). The story is
deliberate and small, so that the code has something to find: viewers outside Maharashtra find the Marathi original hard
to follow; some question the end card's unsourced "best faral tin" claim; and in Kerala and West Bengal some commenters
name a festival (Onam, Kali Puja) where the festival-reference version names Diwali.

Sentiment and theme labels sit next to each comment here only to power the DEMO responder (`comment-read-v1`): in a live
project a model reads the comments without seeing them. The label is the demo's stand-in for a model reading and is
shown as a model interpretation everywhere. What counts as a mention of the claim or of a festival is decided by the
watch terms below, matched by code in the comment text.
"""

import random
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any, NamedTuple

from app.services.pulse_sample import ADAPTED_A, ADAPTED_B, ORIGINAL, START

DATASET_VERSION = "pulse-comments-sample-1"
SAMPLE_LABEL = "Sample comments, not from a connected channel"
PLATFORM = "youtube"
LAST_UPDATED_AT = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
WEEKS = 3

LANGUAGE_NAMES = {"mr": "Marathi", "ta": "Tamil", "ml": "Malayalam", "bn": "Bengali", "en": "English"}
SCRIPT_OF = {"mr": "Deva", "ta": "Taml", "ml": "Mlym", "bn": "Beng", "en": "Latn"}
SAMPLE_LIMITATIONS = (
    "Written for the demo, not collected from a channel. No real viewer wrote these comments.",
    "Comment counts describe this sample only. They say nothing about how many people saw the ads or how a real "
    "audience would react.",
)

POSITIVE, NEUTRAL, NEGATIVE, MIXED = "positive", "neutral", "negative", "mixed"

# Theme ids -> (label, summary). The summaries are the demo's stand-in for a model's one-line theme description.
THEMES: dict[str, tuple[str, str]] = {
    "language-fit": (
        "Language fit",
        "Viewers outside Maharashtra say the Marathi film is hard to follow and ask for their own language. Where the film "
        "is in their language they welcome it, and a few say the wording sounds formal.",
    ),
    "tin-packaging": ("The tin", "Viewers like how the tin looks and see it as a gift."),
    "superiority-claim": (
        "Doubt about the 'best' claim",
        "Viewers question the end card's 'best faral tin' claim and ask what it rests on.",
    ),
    "festival-reference": (
        "Festival reference",
        "Some viewers say the festival the ad names is not the one they celebrate; others welcome it when it matches.",
    ),
    "delivery": ("Delivery before the festival", "Viewers ask whether the tin can reach their city in time."),
    "price-gifting": ("Price and gifting", "Viewers ask about the price and weigh it against the gift."),
    "taste-authenticity": (
        "Taste and authenticity",
        "Comments on whether the sweets look homemade or regional, and what is inside the tin.",
    ),
    "film-emotion": ("The film itself", "Viewers react to the song, the visuals and the closing scene."),
}

# --- what the code watches for ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WatchItem:
    id: str
    kind: str  # planted_claim | cultural_misstep
    label: str
    terms: tuple[str, ...]  # matched case-insensitively as substrings of the NFC-normalised comment text
    note: str


WATCH: tuple[WatchItem, ...] = (
    WatchItem(
        "claim-best-faral", "planted_claim", "Claim: 'best faral tin'",
        ("सर्वोत्तम", "best faral", "best farāl", "best in maharashtra", "maharashtra's best",
         "சிறந்த பராள்", "ഏറ്റവും മികച്ച ഫറാൾ", "সেরা ফরাল"),
        "The end card states that this is Maharashtra's best faral tin. Creative X-Ray found no source for it.",
    ),
    WatchItem(
        "festival-onam", "cultural_misstep", "Festival named: Onam",
        ("onam", "ഓണം", "ഓണമ", "ഓണത്"),
        "Commenters in Kerala name Onam where the ad names Diwali.",
    ),
    WatchItem(
        "festival-kali-puja", "cultural_misstep", "Festival named: Kali Puja",
        ("kali puja", "kalipuja", "কালীপুজো", "কালী পূজা", "কালীপূজা"),
        "Commenters in West Bengal name Kali Puja where the ad names Diwali.",
    ),
)

# --- the authored comments ----------------------------------------------------------------------------------------


class Authored(NamedTuple):
    text: str
    sentiment: str
    themes: tuple[str, ...]
    language: str
    script: str
    code_mixed: bool
    week: int  # 1 to 3: which week of the run the comment was posted in


def _c(language: str, text: str, sentiment: str, *themes: str, week: int, script: str | None = None, mixed: bool = False) -> Authored:
    return Authored(text, sentiment, themes, language, script or SCRIPT_OF[language], mixed, week)


SLICES: dict[tuple[str, str], list[Authored]] = {
    ("IN-MH", ORIGINAL): [
        _c("mr", "गाणं आणि दृश्य दोन्ही मनाला भिडलं. दिवाळीची आठवण आली.", POSITIVE, "film-emotion", week=1),
        _c("mr", "फराळ अगदी घरच्यासारखा दिसतोय, आईची आठवण आली.", POSITIVE, "taste-authenticity", week=1),
        _c("mr", "डबा खूपच सुंदर आहे, भेट द्यायला एकदम छान.", POSITIVE, "tin-packaging", week=1),
        _c("mr", "आपल्या मराठीत जाहिरात बघून खूप छान वाटलं.", POSITIVE, "language-fit", week=1),
        _c("mr", "सर्वोत्तम फराळ टिन? हे कोणी ठरवलं? पुरावा कुठे आहे?", NEGATIVE, "superiority-claim", week=2),
        _c("mr", "प्रत्येक जाहिरातीत सर्वोत्तम म्हणतात, पण चव घेतल्याशिवाय कसं कळणार?", NEGATIVE, "superiority-claim", week=3),
        _c("mr", "दिवाळीच्या आधी पुण्यात डिलिव्हरी मिळेल का?", NEUTRAL, "delivery", week=1),
        _c("mr", "या टिनची किंमत किती आहे?", NEUTRAL, "price-gifting", week=2),
        _c("mr", "चव छान असेल, पण थोडा महाग वाटतो.", MIXED, "price-gifting", week=2),
        _c("mr", "आम्ही मागच्या वर्षी घेतला होता, चकल्या खरंच कुरकुरीत होत्या.", POSITIVE, "taste-authenticity", week=3),
        _c("mr", "Packaging खूपच premium वाटतंय, gift साठी perfect!", POSITIVE, "tin-packaging", week=1, mixed=True),
        _c("mr", "Best faral tin असं का लिहिलंय? proof दाखवा ना.", NEGATIVE, "superiority-claim", week=2, mixed=True),
        _c("en", "Is this available outside Maharashtra? Asking for my cousin in Chennai.", NEUTRAL, "delivery", week=1),
        _c("en", "Lovely film. The last scene with the tin made me tear up.", POSITIVE, "film-emotion", week=1),
    ],
    ("IN-TN", ORIGINAL): [
        _c("ta", "விளம்பரம் மராத்தியில் இருக்கிறது, எனக்கு ஒன்றும் புரியவில்லை.", NEGATIVE, "language-fit", week=1),
        _c("ta", "தமிழில் இந்த விளம்பரம் வருமா?", NEUTRAL, "language-fit", week=1),
        _c("ta", "டின் பார்க்க அழகாக இருக்கிறது, பரிசளிக்க நன்றாக இருக்கும்.", POSITIVE, "tin-packaging", week=1),
        _c("ta", "மகாராஷ்டிராவின் சிறந்த பராள் டின் என்று போட்டிருக்கிறார்கள். எங்களுக்கு அதனால் என்ன?", NEGATIVE, "superiority-claim", week=2),
        _c("ta", "சென்னைக்கு தீபாவளிக்கு முன் டெலிவரி கிடைக்குமா?", NEUTRAL, "delivery", week=2),
        _c("ta", "பராள் நன்றாக இருக்கலாம், ஆனால் எங்கள் ஊர் பலகாரங்கள் வேண்டும்.", MIXED, "taste-authenticity", week=3),
        _c("en", "Nice visuals, but why Marathi for a Chennai audience?", NEUTRAL, "language-fit", week=1),
        _c("en", "'Best in Maharashtra' means nothing to me in Tamil Nadu.", NEGATIVE, "superiority-claim", week=3),
        _c("ta", "Ad super ah irukku but Tamil la podunga, purinjukka mudiyala.", NEUTRAL, "language-fit", week=2, script="Latn", mixed=True),
    ],
    ("IN-KL", ORIGINAL): [
        _c("ml", "പരസ്യം മറാഠിയിലാണ്, ഒന്നും മനസ്സിലായില്ല.", NEGATIVE, "language-fit", week=1),
        _c("ml", "ഇത് മലയാളത്തിൽ വരുമോ?", NEUTRAL, "language-fit", week=1),
        _c("ml", "ടിൻ കാണാൻ നല്ല ഭംഗിയുണ്ട്.", POSITIVE, "tin-packaging", week=1),
        _c("ml", "മഹാരാഷ്ട്രയിലെ ഏറ്റവും മികച്ച ഫറാൾ ടിൻ എന്ന് എഴുതിയിട്ടുണ്ട്, അതിന് തെളിവ് എവിടെ?", NEGATIVE, "superiority-claim", week=2),
        _c("ml", "കൊച്ചിയിൽ ഡെലിവറി ഉണ്ടോ?", NEUTRAL, "delivery", week=2),
        _c("ml", "സമ്മാനം കൊടുക്കാൻ നല്ലതാണ്, പക്ഷേ വില കുറച്ച് കൂടുതലാണ്.", MIXED, "price-gifting", week=3),
        _c("en", "Gorgeous packaging, but the ad in Marathi feels like it is not meant for us.", NEGATIVE, "language-fit", "tin-packaging", week=1),
        _c("ml", "Ad kollam, pakshe Malayalam subtitle venam.", NEUTRAL, "language-fit", week=2, script="Latn", mixed=True),
    ],
    ("IN-WB", ORIGINAL): [
        _c("bn", "বিজ্ঞাপনটা মারাঠিতে, কিছুই বুঝলাম না।", NEGATIVE, "language-fit", week=1),
        _c("bn", "বাংলায় কি এই বিজ্ঞাপন পাওয়া যাবে?", NEUTRAL, "language-fit", week=1),
        _c("bn", "টিনটা দেখতে খুব সুন্দর, উপহার দেওয়ার জন্য ভালো।", POSITIVE, "tin-packaging", week=1),
        _c("bn", "মহারাষ্ট্রের সেরা ফরাল টিন লিখেছে, কিসের ভিত্তিতে?", NEGATIVE, "superiority-claim", week=2),
        _c("bn", "কলকাতায় পুজোর আগে ডেলিভারি পাব তো?", NEUTRAL, "delivery", week=2),
        _c("bn", "ফরাল কেমন জানি না, আমাদের মিষ্টি তো আলাদা।", MIXED, "taste-authenticity", week=3),
        _c("en", "'Best faral tin' in Maharashtra, they say. Fine, but prove it.", NEGATIVE, "superiority-claim", week=3),
        _c("bn", "Ad ta bhalo but Bangla te dile aro bhalo hoto.", NEUTRAL, "language-fit", week=2, script="Latn", mixed=True),
    ],
    ("IN-TN", ADAPTED_A): [
        _c("ta", "தமிழில் பார்க்கும்போது மனதுக்கு நெருக்கமாக இருக்கிறது.", POSITIVE, "language-fit", week=1),
        _c("ta", "பாடலும் காட்சிகளும் மிகவும் அருமை.", POSITIVE, "film-emotion", week=1),
        _c("ta", "டின் அழகாக இருக்கிறது, அக்காவுக்கு பரிசளிக்கலாம்.", POSITIVE, "tin-packaging", week=2),
        _c("ta", "தமிழ் நன்றாக இருக்கிறது, ஆனால் கொஞ்சம் புத்தகத் தமிழ் மாதிரி இருக்கிறது.", MIXED, "language-fit", week=2),
        _c("ta", "மதுரையில் டெலிவரி உண்டா?", NEUTRAL, "delivery", week=2),
        _c("ta", "750 கிராம் என்று போட்டிருக்கிறார்கள், உள்ளே என்னென்ன இருக்கும்?", NEUTRAL, "taste-authenticity", week=3),
        _c("en", "Finally an ad in proper Tamil. Well done.", POSITIVE, "language-fit", week=1),
        _c("en", "Looks good, but is it worth the price for 750 g?", MIXED, "price-gifting", week=3),
        _c("ta", "Tin romba nalla irukku, gift ku perfect.", POSITIVE, "tin-packaging", week=2, script="Latn", mixed=True),
    ],
    ("IN-KL", ADAPTED_A): [
        _c("ml", "മലയാളത്തിൽ കണ്ടപ്പോൾ വളരെ സന്തോഷം.", POSITIVE, "language-fit", week=1),
        _c("ml", "ടിൻ ഗംഭീരം, സമ്മാനമായി കൊടുക്കാൻ നല്ലത്.", POSITIVE, "tin-packaging", week=1),
        _c("ml", "ഭാഷ കൊള്ളാം, പക്ഷേ ചില വാക്കുകൾ ഡബ്ബിംഗ് പോലെ തോന്നി.", MIXED, "language-fit", week=2),
        _c("ml", "തിരുവനന്തപുരത്ത് ഡെലിവറി ഉണ്ടോ?", NEUTRAL, "delivery", week=2),
        _c("ml", "ഉള്ളിൽ എന്തൊക്കെയാണ് ഉണ്ടാവുക എന്ന് പറയാമോ?", NEUTRAL, "taste-authenticity", week=3),
        _c("en", "Beautiful film, the music is lovely.", POSITIVE, "film-emotion", week=1),
        _c("en", "Diwali is nice, but honestly Onam is our big festival.", NEGATIVE, "festival-reference", week=2),
        _c("ml", "Tin adipoli, gift ayi kodukkan nallath.", POSITIVE, "tin-packaging", week=3, script="Latn", mixed=True),
    ],
    ("IN-WB", ADAPTED_A): [
        _c("bn", "বাংলায় দেখে খুব ভালো লাগল।", POSITIVE, "language-fit", week=1),
        _c("bn", "গান আর দৃশ্য দুটোই মন ছুঁয়ে গেল।", POSITIVE, "film-emotion", week=1),
        _c("bn", "ভাষাটা ভালো, কিন্তু একটু বইয়ের ভাষার মতো লাগছে।", MIXED, "language-fit", week=2),
        _c("bn", "হাওড়ায় ডেলিভারি পাওয়া যাবে?", NEUTRAL, "delivery", week=2),
        _c("bn", "৭৫০ গ্রাম লেখা আছে, ভেতরে কী কী থাকবে?", NEUTRAL, "taste-authenticity", week=3),
        _c("en", "The tin is gorgeous. Perfect for gifting.", POSITIVE, "tin-packaging", week=1),
        _c("en", "It's Kali Puja time for us, and the ad only talks about Diwali.", NEGATIVE, "festival-reference", week=2),
        _c("bn", "Bangla version ta darun hoyeche!", POSITIVE, "language-fit", week=2, script="Latn", mixed=True),
    ],
    ("IN-TN", ADAPTED_B): [
        _c("ta", "தீபாவளி பலகாரம் என்று சொன்னது நம் வீட்டு பண்டிகை போலவே இருக்கிறது.", POSITIVE, "festival-reference", week=1),
        _c("ta", "தமிழ் வரிகள் இயல்பாக இருக்கின்றன.", POSITIVE, "language-fit", week=1),
        _c("ta", "அந்த கடைசிக் காட்சி மனதைத் தொட்டது.", POSITIVE, "film-emotion", week=2),
        _c("ta", "தீபாவளிக்கு முன் கோயம்புத்தூரில் டெலிவரி கிடைக்குமா?", NEUTRAL, "delivery", week=2),
        _c("ta", "டின் நன்றாக இருக்கிறது, விலை கொஞ்சம் அதிகம்.", MIXED, "price-gifting", "tin-packaging", week=3),
        _c("en", "Love that it talks about Deepavali snacks the way we say it.", POSITIVE, "festival-reference", "taste-authenticity", week=1),
        _c("en", "Will the Deepavali delivery date be guaranteed?", NEUTRAL, "delivery", "festival-reference", week=3),
        _c("ta", "Tin packaging semma, gift ku super.", POSITIVE, "tin-packaging", week=2, script="Latn", mixed=True),
    ],
    ("IN-KL", ADAPTED_B): [
        _c("ml", "ദീപാവലി പലഹാരം എന്ന് പറയുന്നു, പക്ഷേ ഞങ്ങൾക്ക് വലുത് ഓണമാണ്.", NEGATIVE, "festival-reference", week=1),
        _c("ml", "ഓണത്തിന് പറ്റുന്ന രീതിയിൽ ഒരു പരസ്യം വേണം, ദീപാവലി ഇവിടെ അത്ര വലുതല്ല.", NEGATIVE, "festival-reference", week=2),
        _c("ml", "ഭാഷ നന്നായി വന്നിട്ടുണ്ട്.", POSITIVE, "language-fit", week=1),
        _c("ml", "പാട്ട് ഇഷ്ടപ്പെട്ടു.", POSITIVE, "film-emotion", week=2),
        _c("ml", "ഡെലിവറി എത്ര ദിവസമെടുക്കും?", NEUTRAL, "delivery", week=2),
        _c("en", "Onam would have made more sense for Kerala. Diwali feels borrowed.", NEGATIVE, "festival-reference", week=2),
        _c("en", "Pretty tin, but the festival angle is off for us.", MIXED, "tin-packaging", "festival-reference", week=3),
        _c("ml", "Tin kidu, gift cheyyan nallath.", POSITIVE, "tin-packaging", week=1, script="Latn", mixed=True),
    ],
    ("IN-WB", ADAPTED_B): [
        _c("bn", "আমাদের এখানে এই সময় কালীপুজো, দীপাবলি নয়।", NEGATIVE, "festival-reference", week=1),
        _c("bn", "দীপাবলির কথা ঠিক আছে, তবে কালী পূজার কথাও থাকলে ভালো হতো।", MIXED, "festival-reference", week=2),
        _c("bn", "ভাষা সহজ, বুঝতে অসুবিধা হয়নি।", POSITIVE, "language-fit", week=1),
        _c("bn", "টিনটা সুন্দর, উপহার দেওয়া যাবে।", POSITIVE, "tin-packaging", week=2),
        _c("bn", "কলকাতায় ডেলিভারি কতদিনে পাব?", NEUTRAL, "delivery", week=2),
        _c("en", "Kali Puja is the big night here. This feels like a North Indian Diwali ad.", NEGATIVE, "festival-reference", week=2),
        _c("en", "Nice song and visuals.", POSITIVE, "film-emotion", week=3),
        _c("bn", "Price ta thik ache, gift er jonno bhalo.", POSITIVE, "price-gifting", week=3, script="Latn", mixed=True),
    ],
}


@dataclass(frozen=True)
class SampleComment:
    ref: str
    day: date
    platform: str
    region_code: str
    version_label: str
    language: str
    script: str
    code_mixed: bool
    text: str
    likes: int


def generate_comments() -> list[SampleComment]:
    """All sample comments in a stable order. Identical on every call."""
    out: list[SampleComment] = []
    for (region, version), authored in SLICES.items():
        for item in authored:
            rng = random.Random(f"{DATASET_VERSION}|{region}|{version}|{len(out)}")
            day = START + timedelta(days=7 * (item.week - 1) + rng.randrange(7))
            out.append(SampleComment(
                ref=f"cm-{len(out) + 1:04d}", day=day, platform=PLATFORM, region_code=region, version_label=version,
                language=item.language, script=item.script, code_mixed=item.code_mixed, text=item.text,
                likes=min(60, int(rng.expovariate(1 / 6))),
            ))
    return out


@lru_cache
def demo_labels() -> dict[str, tuple[str, tuple[str, ...]]]:
    """ref -> (sentiment, theme ids): the demo's stand-in for a model reading. Used only by the demo responder."""
    labels: dict[str, tuple[str, tuple[str, ...]]] = {}
    refs = iter(c.ref for c in generate_comments())
    for authored in SLICES.values():
        for item in authored:
            labels[next(refs)] = (item.sentiment, item.themes)
    return labels


def watch_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def comment_read(ctx: Mapping[str, Any]) -> dict[str, Any] | None:
    """Demo responder for `comment-read-v1`: answers only for this dataset's own comments (any other ref gets no fixture)."""
    labels = demo_labels()
    refs = [c["ref"] for c in ctx["comments"]]
    if not refs or any(r not in labels for r in refs):
        return None
    used = {t for r in refs for t in labels[r][1]}
    return {
        "comments": [{"ref": r, "sentiment": labels[r][0], "themes": list(labels[r][1])} for r in refs],
        "themes": [{"id": t, "label": THEMES[t][0], "summary": THEMES[t][1]} for t in THEMES if t in used],
    }


RESPONDERS = {"comment-read-v1": comment_read}
