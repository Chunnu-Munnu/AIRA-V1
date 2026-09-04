"""
Free-text and speech to symptom codes.

Deliberately keyword-based rather than an LLM call. Three reasons, and all
three are defensible on stage:

  1. A hallucinated symptom code is a clinical safety incident. A keyword
     matcher that fails to match is merely unhelpful - it asks the patient to
     confirm from a list. Those two failure modes are not comparable.
  2. It costs nothing and runs instantly on a cheap phone.
  3. Every match is inspectable. You can point at the word that caused it.

The output is always a SUGGESTION the patient confirms with a tap. AIRA never
silently decides what someone said.
"""

from __future__ import annotations

import re
import unicodedata

# Deliberately generous: recall matters more than precision here, because the
# patient confirms every suggestion before anything is recorded.
KEYWORDS: dict[str, list[str]] = {
    "cough": ["cough", "khansi", "खांसी", "ಕೆಮ್ಮು", "kemmu", "khasi"],
    "haemoptysis": ["blood in cough", "coughing blood", "khoon khansi", "खून", "ರಕ್ತ ಕೆಮ್ಮು"],
    "breathlessness": ["breathless", "short of breath", "saans", "सांस", "ಉಸಿರಾಟ", "usiratada"],
    "chest_pain": ["chest pain", "seene mein dard", "छाती", "ಎದೆ ನೋವು", "ede novu"],
    "dyspepsia": ["acidity", "indigestion", "gas", "jalan", "एसिडिटी", "ಆಮ್ಲೀಯತೆ", "hottе urи", "heartburn"],
    "dysphagia": ["swallow", "nigalne", "निगलने", "ನುಂಗಲು", "food stuck", "khana atakta"],
    "epigastric_pain": ["stomach pain", "pet dard", "पेट दर्द", "ಹೊಟ್ಟೆ ನೋವು"],
    "vomiting_persistent": ["vomit", "ulti", "उल्टी", "ವಾಂತಿ", "vanti"],
    "weight_loss": ["weight loss", "losing weight", "vajan", "वजन", "ತೂಕ", "thin", "dubla"],
    "appetite_loss": ["no appetite", "not hungry", "bhookh", "भूख", "ಹಸಿವು"],
    "fatigue": ["tired", "weak", "thakan", "थकान", "ಆಯಾಸ", "ayasa", "kamzori"],
    "fever_prolonged": ["fever", "bukhar", "बुखार", "ಜ್ವರ", "jwara", "temperature"],
    "night_sweats": ["night sweat", "pasina", "पसीना", "ಬೆವರು"],
    "lymph_node_swelling": ["gland", "swelling neck", "gilti", "गिल्टी", "ಗ್ರಂಥಿ"],
    "pallor": ["pale", "peela", "पीला", "ಬಿಳಿಚಿ", "whitish"],
    "easy_bruising": ["bruise", "neel", "नील", "ಮೂಗೇಟು"],
    "bone_pain": ["bone pain", "haddi", "हड्डी", "ಮೂಳೆ ನೋವು"],
    "mouth_ulcer_nonhealing": ["mouth ulcer", "sore in mouth", "chala", "छाला", "ಬಾಯಿ ಹುಣ್ಣು"],
    "oral_white_red_patch": ["white patch", "red patch", "safed daag", "सफेद", "ಬಿಳಿ ಕಲೆ"],
    "trismus": ["mouth not opening", "muh nahi khulta", "ಬಾಯಿ ತೆರೆಯುವುದಿಲ್ಲ"],
    "loose_teeth": ["loose teeth", "daant hil", "दांत", "ಹಲ್ಲು ಸಡಿಲ"],
    "hoarseness": ["voice", "hoarse", "awaz", "आवाज", "ಧ್ವನಿ"],
    "neck_lump": ["neck lump", "gardan gaanth", "गर्दन", "ಕುತ್ತಿಗೆ ಗಂಟು"],
    "breast_lump": ["breast lump", "lump in breast", "stan gaanth", "स्तन", "ಸ್ತನ ಗಂಟು"],
    "nipple_discharge": ["nipple discharge", "निप्पल", "ಮೊಲೆತೊಟ್ಟು"],
    "postmenopausal_bleeding": ["bleeding after menopause", "rajonivritti", "ಋತುಬಂಧ"],
    "postcoital_bleeding": ["bleeding after intercourse", "sambhog", "ಸಂಭೋಗ"],
    "intermenstrual_bleeding": ["bleeding between periods", "masik ke beech", "ಮುಟ್ಟಿನ ನಡುವೆ"],
    "vaginal_discharge_foul": ["discharge smell", "badbudar", "दुर्गंध", "ದುರ್ವಾಸನೆ"],
    "pelvic_pain": ["pelvic pain", "pet ke niche", "ಹೊಟ್ಟೆ ಕೆಳಗೆ"],
    "abdominal_distension": ["bloating", "pet phoolna", "पेट फूल", "ಹೊಟ್ಟೆ ಉಬ್ಬು"],
    "rectal_bleeding": ["blood in stool", "blood motion", "mal mein khoon", "मल में खून", "ಮಲದಲ್ಲಿ ರಕ್ತ", "piles bleeding"],
    "bowel_habit_change": ["bowel change", "motion change", "शौच", "ಮಲ ವಿಸರ್ಜನೆ"],
    "haematuria": ["blood in urine", "peshab mein khoon", "पेशाब", "ಮೂತ್ರದಲ್ಲಿ ರಕ್ತ"],
    "urinary_hesitancy": ["difficulty urine", "peshab dikkat", "ಮೂತ್ರ ತೊಂದರೆ"],
    "testicular_lump": ["testicle lump", "andkosh", "अंडकोष", "ವೃಷಣ"],
    "jaundice": ["yellow eyes", "peelia", "पीलिया", "ಕಾಮಾಲೆ", "jaundice"],
    "skin_sore_nonhealing": ["sore not healing", "ghav", "घाव", "ಗಾಯ"],
    "changing_mole": ["mole changing", "til", "तिल", "ಮಚ್ಚೆ"],
    "headache_progressive": ["headache", "sir dard", "सिरदर्द", "ತಲೆನೋವು"],
    "abdominal_lump": ["lump in stomach", "pet gaanth", "पेट गांठ", "ಹೊಟ್ಟೆ ಗಂಟು"],
    "recurrent_chest_infection": ["chest infection again", "baar baar infection"],
    "sore_throat_persistent": ["sore throat", "gale kharash", "गले", "ಗಂಟಲು"],
    "ear_pain_unilateral": ["ear pain", "kaan dard", "कान", "ಕಿವಿ ನೋವು"],
    "early_satiety": ["full quickly", "thoda khana", "ಬೇಗ ಹೊಟ್ಟೆ"],
    "tenesmus": ["incomplete motion", "pura nahi", "ಪೂರ್ತಿ ಇಲ್ಲ"],
    "breast_skin_change": ["breast skin", "स्तन त्वचा", "ಸ್ತನ ಚರ್ಮ"],
    "nipple_retraction": ["nipple inward", "निप्पल अंदर", "ಮೊಲೆತೊಟ್ಟು ಒಳಗೆ"],
    "axillary_lump": ["armpit lump", "bagal gaanth", "बगल", "ಕಂಕುಳ"],
    "abdominal_mass_child": ["child stomach lump", "bacche ke pet"],
}

# Rough duration extraction, so "cough for three weeks" starts the clock in
# the right place instead of today.
DURATION_PATTERNS = [
    (re.compile(r"(\d+)\s*(day|days|din|दिन|ದಿನ)", re.I), 1),
    (re.compile(r"(\d+)\s*(week|weeks|hafte|हफ्ते|ವಾರ)", re.I), 7),
    (re.compile(r"(\d+)\s*(month|months|mahine|महीने|ತಿಂಗಳು)", re.I), 30),
    (re.compile(r"(\d+)\s*(year|years|saal|साल|ವರ್ಷ)", re.I), 365),
]

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "panch": 5,
}


def _ruleset_keywords() -> dict[str, list[str]]:
    """Fold every label and patient phrasing from rules/symptoms.json into the
    keyword table, in all three languages.

    The hand-written table above covers the common presentations with the
    colloquialisms people actually use ("gilti", "peelia"). This adds the
    formal Hindi and Kannada wording for all fifty symptoms, so a Kannada
    speaker who says the word the ruleset itself uses is matched even if
    nobody thought to list it. Free, offline, and it can never drift from the
    ruleset because it IS the ruleset.
    """
    try:
        from engine.rules_loader import load_ruleset

        rs = load_ruleset()
    except Exception:
        return {}

    extra: dict[str, list[str]] = {}
    for code, spec in rs.symptoms.items():
        terms: list[str] = []
        for field in ("label", "patient_phrasing"):
            block = spec.get(field) or {}
            if isinstance(block, dict):
                terms += [v for v in block.values() if isinstance(v, str) and len(v) > 3]
        if terms:
            extra[code] = terms
    return extra


def _merged() -> dict[str, list[str]]:
    merged = {code: list(terms) for code, terms in KEYWORDS.items()}
    for code, terms in _ruleset_keywords().items():
        merged.setdefault(code, [])
        for t in terms:
            if t not in merged[code]:
                merged[code].append(t)
    return merged


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


def extract_duration_days(text: str) -> int | None:
    t = _normalise(text)
    for word, n in WORD_NUMBERS.items():
        t = re.sub(rf"\b{word}\b", str(n), t)
    for pattern, multiplier in DURATION_PATTERNS:
        m = pattern.search(t)
        if m:
            return int(m.group(1)) * multiplier
    return None


def map_text(text: str, limit: int = 5) -> list[dict]:
    """Return ranked candidate symptom codes with the phrase that matched.

    Never returns a decision. The patient taps to confirm, and a suggestion
    nobody confirms is never written to the record.
    """
    t = _normalise(text)
    hits: list[dict] = []
    for code, terms in _merged().items():
        best = None
        for term in terms:
            if _normalise(term) in t:
                # Longer matches are more specific: "blood in cough" should
                # outrank a bare "cough". Keep the longest match per symptom
                # rather than the first, so the ruleset phrasings compete
                # fairly with the hand-written colloquialisms.
                if best is None or len(term) > len(best):
                    best = term
        if best:
            hits.append(
                {
                    "code": code,
                    "matched_on": best,
                    "confidence": round(min(0.95, 0.4 + len(best) / 40), 2),
                }
            )

    hits.sort(key=lambda h: -h["confidence"])
    return hits[:limit]


def parse(text: str, translated_from: str | None = None) -> dict:
    days = extract_duration_days(text)
    return {
        "text": text,
        "candidates": map_text(text),
        "duration_days": days,
        "needs_confirmation": True,
        "translated_from": translated_from,
        "note": (
            "These are suggestions from the words you used. "
            "Nothing is recorded until you confirm it."
        ),
    }
