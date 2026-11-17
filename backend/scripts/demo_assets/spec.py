"""Copy, image prompts and voice-over script for the original Maharashtra creative (Aamod, Diwali / Bhau Beej).

Single source for generate.py (paid model calls) and render.py (compositing). Marathi copy is rendered in code;
English back-translations are the author's, for reviewers. Prompt texts are versioned by PROMPT_VERSION.
"""

PROMPT_VERSION = "aamod-mh-original-v2"  # v2: scene 4 identity crop + sibling ages, full-bleed key visual; rest as v1
IMAGE_MODEL = "gemini-3.1-flash-image"
TTS_MODEL = "gemini-3.8-flash-tts"
ASR_MODEL = "gemini-3.8-flash"
MUSIC_MODEL = "lyria-002"
VOICE = "Sulafat"  # Gemini prebuilt voice described as warm

NO_TEXT = ("Do not render any text, letters, numerals, logos or watermarks anywhere in the image; leave clean space "
           "where text will be added later.")
STYLE = ("Photorealistic, natural skin tones and realistic hands, warm cinematic light, full-frame camera, 35 mm lens, "
         "shallow depth of field. An authentic, contemporary Maharashtrian middle-class home; respectful, no caricature.")
PACK_REF = ("The first reference image shows the product, the Aamod Festive Tin. Wherever the tin appears, reproduce "
            "exactly this tin: the same cylindrical shape and proportions, peacock-teal body, brass-gold lid, gold "
            "paisley band and the round cream medallion with the same teal emblem and flame. Do not change its design "
            "or colours and do not add any letters to it.")

PACK_PROMPT = (
    "A studio product photograph of a single cylindrical metal sweets tin, about 18 cm wide and 12 cm tall, with a "
    "fitted lid, seen from the front and slightly above (about 15 degrees). The body is a deep peacock teal (#0E4D58) "
    "with a satin finish. A band of brass-gold paisley and marigold-flower motifs runs around the lower third of the "
    "body. The lid and the thin rim at the base are polished brass-gold. On the front of the body, centred and facing "
    "the camera, is a plain round cream (#FBF1DD) medallion with a thin gold border, about 8 cm across, completely "
    "blank. The tin stands alone on a seamless pure white background, evenly lit, with no shadow and no reflection, "
    "the whole tin in frame with generous white margins. No props."
)


def _tin(bbox: list[float]) -> dict:
    """The pack as drawn by the image model in a scene: protected; bbox hand-calibrated on the plate (x, y, w, h)."""
    return {"id": "product", "kind": "product", "value": "Aamod Festive Tin (drawn by the image model from "
            "brand/pack_reference.png)", "locked": True, "bbox": bbox}

# Scenes of the 9:16 video. `refs`: extra reference images after the pack (ids of earlier scenes).
SCENES = [
    {
        "id": "mh-s1", "name": "balcony", "refs": [], "ost_y": 800,  # headline below the lantern
        "description": "Dusk on a Pune apartment balcony on Diwali: glowing akash kandil (star lantern), clay panti "
                       "lamps on the ledge, rangoli at the doorway; the Aamod tin stands among the lamps.",
        "prompt": "A vertical 9:16 photograph at dusk on the balcony of an older apartment building in Pune, "
                  "Maharashtra, on a Diwali evening. A large traditional akash kandil, a star-shaped paper lantern in "
                  "saffron, red and yellow with paper tassels, hangs from the balcony ceiling and glows from inside. A "
                  "row of small clay panti oil lamps burns along the balcony ledge. A colourful rangoli of dots and "
                  "flower patterns decorates the balcony floor near the open doorway. Strings of warm lights; the "
                  "neighbourhood's lit windows softly blurred in the background against a deep blue sky. On the "
                  "ledge, among the lamps, stands the tin from the reference image, facing the camera. No people. "
                  "Keep the upper third of the frame calm, mostly sky and soft lantern glow, for a headline. Keep "
                  "the lower fifth of the frame simple.",
        "regions": [_tin([0.572, 0.536, 0.146, 0.082]),
                    {"id": "akash-kandil", "kind": "image_region", "value": "Akash kandil (star-shaped paper lantern)",
                     "locked": False, "bbox": [0.40, 0.02, 0.24, 0.37]}],
        "ost": ["दिवाळी म्हणजे", "फराळ!"], "ost_en": "Diwali means faral!",
    },
    {
        "id": "mh-s2", "name": "aaji", "refs": [],
        "description": "Grandmother (aaji) in a Paithani saree and her granddaughter arrange homemade faral (chakli, "
                       "karanji, besan ladoo, shankarpali) on a brass plate; the tin on the table.",
        "prompt": "A vertical 9:16 photograph inside a warm Maharashtrian family home on Diwali. A grandmother in her "
                  "late sixties, wearing a purple Paithani silk saree with a green and gold peacock border, and her "
                  "granddaughter in her twenties, wearing a simple yellow festive kurta, sit at a wooden dining "
                  "table, smiling and talking as they arrange homemade Diwali faral on a large round brass plate: "
                  "spiral chakli, crescent-shaped karanji, round yellow besan ladoo and small diamond-shaped "
                  "shankarpali. The closed tin from the reference image stands on the table next to the plate, "
                  "facing the camera. Marigold garlands on the doorway behind them, clay diyas glowing on a shelf, "
                  "soft evening window light. Candid, joyful, documentary-style family moment. Keep the upper "
                  "quarter of the frame uncluttered (wall and garlands) for a headline.",
        "regions": [_tin([0.73, 0.702, 0.205, 0.116]),
                    {"id": "faral-plate", "kind": "image_region", "value": "Brass plate of faral: chakli, karanji, besan ladoo, shankarpali",
                     "locked": False, "bbox": [0.15, 0.725, 0.57, 0.13]}],
        "ost": ["आजीच्या हातची चव"], "ost_en": "The taste of Grandma's cooking",
    },
    {
        "id": "mh-s3", "name": "tin", "refs": [], "caption_y": 740,  # caption above the tin, never on it
        "description": "Product hero: the open Aamod tin filled with faral on a carved table with diyas and marigolds.",
        "prompt": "A vertical 9:16 close-up food photograph. The tin from the reference image stands on a carved "
                  "wooden table, its brass-gold lid leaning against its side, filled to the top with Maharashtrian "
                  "Diwali faral: spiral chakli, crescent-shaped karanji, round besan ladoo and diamond-shaped "
                  "shankarpali. The tin's front with the round cream medallion faces the camera. Around it: small "
                  "glowing clay diyas, a few marigold flowers and petals, a red and gold cloth, warm bokeh lights in "
                  "the background. Appetising, premium, warm golden light. The tin is the hero, placed in the lower "
                  "middle of the frame; keep the upper third calm and dark for a headline.",
        "regions": [_tin([0.23, 0.535, 0.74, 0.27])],
        "ost": ["घरच्या चवीचा फराळ,", "आता एकाच टिनमध्ये"], "ost_en": "Faral that tastes like home, now in one tin",
        "label": "Aamod Festive Tin",
    },
    {
        "id": "mh-s4", "name": "bhaubeej", "refs": ["mh-s2-sister"], "caption_y": 1440,
        "description": "Bhau Beej: the sister (the granddaughter from scene 2) performs aukshan (aarti) for her "
                       "brother seated on a pat; he gives her the Aamod tin.",
        "prompt": "A vertical 9:16 photograph of a Bhau Beej celebration in a Maharashtrian home: two siblings close "
                  "in age. The sister, a young woman of about twenty-two, is the young woman shown in the second "
                  "reference image (same face, hair and features); she is not middle-aged. She wears a green festive "
                  "silk saree and holds a brass aarti plate with a small lit diya, rice and kumkum, performing the "
                  "aukshan ritual for her brother, a young man of about eighteen. He sits cross-legged on a low "
                  "wooden pat with a colourful rangoli in front of it, wearing a cream kurta, and with both hands he "
                  "presents her the tin from the first reference image. Both are laughing warmly. Warm diya light, "
                  "marigold garlands, a softly lit home in the background. Keep the upper quarter of the frame "
                  "uncluttered for a headline.",
        "regions": [_tin([0.505, 0.602, 0.176, 0.094])],
        "ost": ["भाऊबीजेला द्या", "गोड भेट"], "ost_en": "Give a sweet gift this Bhau Beej",
    },
]

KV_PROMPT = (
    "A 4:5 festive still life for a Diwali advertisement, shot from a slightly high angle. On a dark peacock-teal "
    "tabletop, an abundant but tidy spread of Maharashtrian Diwali faral on round brass plates and in small brass "
    "bowls: spiral chakli, crescent-shaped karanji, round besan ladoo, diamond-shaped shankarpali and a bowl of poha "
    "chivda. Small clay panti lamps glow among the plates, with marigold flowers and petals. In the softly blurred "
    "upper background, a glowing star-shaped akash kandil paper lantern. Leave the lower-right third of the frame as "
    "an empty, clean area of tabletop (a product pack will be placed there later). The photograph fills the whole "
    "frame edge to edge, with no borders, bands or blocks of flat colour; the upper part of the frame shows a dark, "
    "softly lit wall with gentle bokeh, giving calm space for a headline. Premium food photography, warm golden "
    "light. No packaging, no tins, no boxes."
)

# Reference crops made from earlier generations: id -> (source raw image, normalised crop box x0, y0, x1, y1).
CROPS = {"mh-s2-sister": ("mh-s2", (0.52, 0.38, 1.0, 0.74))}  # the granddaughter only, as scene 4's identity reference

# No style prefix: with language_code mr-IN, gemini-3.8-flash-tts read an English style instruction aloud before the
# Marathi line (first take, 17 Nov 2026). The warm preset voice carries the tone instead.
TTS_STYLE = ""

# Voice-over, one Gemini TTS call per line (exact caption timing). scene: where the line plays.
VO_LINES = [
    {"id": "mh-vo-1", "scene": "mh-s1", "text": "दिवाळी आली की घरभर फराळाचा सुगंध दरवळतो.",
     "en": "When Diwali arrives, the aroma of faral fills the whole house."},
    {"id": "mh-vo-2", "scene": "mh-s2", "text": "आजीच्या हातची चकली, करंजी, बेसनाचे लाडू…",
     "en": "Grandma's own chakli, karanji, besan laddoos…"},
    {"id": "mh-vo-3", "scene": "mh-s3", "text": "तीच घरची चव, आता आमोद फेस्टिव्ह टिनमध्ये.",
     "en": "That same taste of home, now in the Aamod Festive Tin."},
    {"id": "mh-vo-4", "scene": "mh-s4", "text": "या भाऊबीजेला, आपल्या माणसांना द्या गोड भेट.",
     "en": "This Bhau Beej, give your loved ones a sweet gift."},
    {"id": "mh-vo-5", "scene": "mh-s5", "text": "भाऊबीजेपूर्वी घरपोच. आजच ऑर्डर करा!",
     "en": "Delivered home before Bhau Beej. Order today!"},
    {"id": "mh-vo-6", "scene": "mh-s5", "text": "आमोद. Every bond, a little sweeter.",
     "en": "Aamod. Every bond, a little sweeter."},
]

MUSIC_PROMPT = ("Warm, joyful Indian festive instrumental for a family Diwali advertisement: soft dholki and tabla "
                "groove, bansuri flute melody, light sitar accents and gentle temple bells, uplifting and homely, "
                "100 BPM, clean modern mix.")
MUSIC_NEGATIVE = "vocals, singing, speech, lyrics, harsh noise, distortion"

# End card and key visual copy (Marathi with a little English). The asterisked small print is the deliberate risk.
GREETING = ("दिवाळीच्या हार्दिक शुभेच्छा!", "Heartfelt Diwali greetings!")
PRODUCT = ("Aamod Festive Tin*", "Aamod Festive Tin*")
CTA_HOOK = ("भाऊबीजेपूर्वी घरपोच", "Delivered home before Bhau Beej")
CTA_BUTTON = ("आजच ऑर्डर करा · Order now", "Order today · Order now")
TAGLINE = ("Every bond, a little sweeter.", "Every bond, a little sweeter.")
SMALL_PRINT = ("*ग्राहकांच्या पसंतीनुसार महाराष्ट्रातील सर्वोत्तम फराळ टिन.",
               "*Maharashtra's best faral tin, as per customer preference.")
DEMO_LABEL = ("Fictional brand · Omnicult demo creative", "Fictional brand · Omnicult demo creative")
KV_HEADLINE = ("दिवाळी म्हणजे फराळ!", "Diwali means faral!")
KV_SUB = ("घरच्या चवीचा फराळ, आता एकाच टिनमध्ये", "Faral that tastes like home, now in one tin")

# Authoring notes for demo QA (written into creative_mh_original.json under authoring_notes). These are the author's
# design intent and hypotheses to check against Market Lens evidence; they are not evidence and not findings.
ADAPTATION_HOOKS = [
    {"id": "hook-bhau-beej", "kind": "festival_reference",
     "element_ids": ["mh-vid-s4-headline", "mh-vid-cta-hook", "mh-kv-cta-hook"], "transcript_ids": ["mh-vo-4", "mh-vo-5"],
     "note": "Bhau Beej is the Marathi name and framing of the sibling day after Diwali. Check its name, date and "
             "weight in each target state before reusing it (the same day has other names and customs elsewhere)."},
    {"id": "hook-faral", "kind": "regional_food",
     "element_ids": ["mh-vid-s1-headline", "mh-vid-s3-headline", "mh-vid-s2-faral-plate", "mh-kv-headline", "mh-kv-sub"],
     "transcript_ids": ["mh-vo-1", "mh-vo-2"], "scene_ids": ["mh-s2", "mh-s3"],
     "note": "Faral (chakli, karanji, besan ladoo, shankarpali) is the Maharashtrian Diwali snack assortment; both the "
             "word and the items are regional. The tin's contents may change by region; the tin itself may not."},
    {"id": "hook-akash-kandil", "kind": "visual_setting", "scene_ids": ["mh-s1"], "element_ids": ["mh-vid-s1-akash-kandil", "mh-kv-plate"],
     "note": "The star-shaped akash kandil lantern on a Pune balcony is a Maharashtra Diwali signature; check what "
             "festive decoration reads as local in each target state."},
    {"id": "hook-marathi-idiom", "kind": "language",
     "element_ids": ["mh-vid-s1-headline", "mh-vid-s2-headline"], "transcript_ids": ["mh-vo-2", "mh-vo-4"],
     "note": "\"दिवाळी म्हणजे फराळ!\", \"आजीच्या हातची चव\" (the taste of Grandma's cooking) and \"आपल्या माणसांना\" "
             "(to our own people) are idiomatic Marathi and need transcreation, not word-for-word translation."},
    {"id": "hook-paithani", "kind": "visual_setting", "scene_ids": ["mh-s2"],
     "note": "The grandmother's Paithani saree and the Pune flat mark the family as Maharashtrian."},
    {"id": "hook-festival-deadline-cta", "kind": "cta", "element_ids": ["mh-vid-cta-hook", "mh-kv-cta-hook"],
     "transcript_ids": ["mh-vo-5"],
     "note": "The CTA promises delivery before Bhau Beej. The delivery deadline must follow the festival day that "
             "matters in each region, which is not necessarily the same date."},
    {"id": "hook-greeting", "kind": "language", "element_ids": ["mh-vid-greeting"],
     "note": "Marathi Diwali greeting on the end card; each region needs its own greeting in its own script."},
]
DELIBERATE_RISKS = [
    {"id": "risk-unsubstantiated-superiority-claim", "kind": "claim", "planted": True,
     "element_ids": ["mh-vid-small-print", "mh-kv-small-print", "mh-vid-product-name", "mh-kv-product-name"],
     "text": SMALL_PRINT[0], "translation_en": SMALL_PRINT[1],
     "why": "A superiority claim ('best faral tin in Maharashtra') attached by asterisk to the product name, based on "
            "an unnamed 'customer preference' with no source, sample or date. Indian advertising self-regulation "
            "(ASCI Code) expects superiority and leadership claims to be substantiated, and the Aamod brand kit "
            "forbids superiority claims. Expected: Risk Check flags it on the end card and the key visual."},
    {"id": "risk-small-print-legibility", "kind": "legibility", "planted": False,
     "element_ids": ["mh-vid-small-print", "mh-kv-small-print"],
     "why": "Secondary, expected: the small print is set at 26 px on a 1920 px frame (19 px on the key visual), on "
            "screen for about eight seconds, near the bottom platform overlay zone of Reels and Shorts."},
]
