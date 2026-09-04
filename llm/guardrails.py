"""
What the LLM is allowed to see, and what each audience is allowed to read.

Three separate jobs live here, and keeping them separate is the point:

  ROUTE      Some questions must not reach a model at all. An emergency
             description needs an instruction, not a paragraph. A request for
             a diagnosis or a drug dose is outside scope and the right answer
             is a short refusal plus what we CAN do.

  SCRUB      What leaves this building. Names, phone numbers, AIRA codes,
             villages and exact dates never reach Gemini. The model receives
             an age BAND, a sex, and the clinical facts - which is everything
             it needs to phrase an answer and nothing it needs to identify a
             person. This is enforced here, at the adapter, not by asking the
             prompt nicely.

  AUDIENCE   The same underlying facts render two ways. A patient gets plain
             language and no site names, no probabilities, no staging
             vocabulary. A clinician gets the technical layer in full: the
             model probability, the trajectory vector, the site vocabulary,
             the guideline sections. Neither is a redacted version of the
             other - they are two correct renderings for two readers with
             different jobs.

The audience rule is not politeness. Telling a patient "your profile scores
10.9%, consistent with a lung primary" is a harm: it is a number they cannot
act on attached to a word they will not stop thinking about, delivered by
software that cannot examine them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ─────────────────────────────────────────────────────────────────────────────
# ROUTE
# ─────────────────────────────────────────────────────────────────────────────

EMERGENCY_PATTERNS = [
    r"\b(?:heavy|severe|lot of|profuse)\s+bleed",
    r"\bbleeding (?:a lot|heavily|non ?stop|won'?t stop|will not stop)\b",
    r"\bcan'?t breathe\b|\bcannot breathe\b|\bunable to breathe\b",
    r"\bsudden(?:ly)?\b.{0,20}\b(?:breathless|collaps|weak(?:ness)? on one side|numb)",
    r"\bchest pain\b.{0,30}\b(?:sweat|arm|jaw|crush)",
    r"\b(?:seizure|fit|convulsion)s?\b",
    r"\bunconscious\b|\bpassed out\b|\bnot waking\b|\bnot responding\b",
    # Retention is an emergency however it is phrased - "cannot pass urine",
    # "not passed urine at all since yesterday", "unable to pass any urine".
    r"\b(?:cannot|can'?t|could not|couldn'?t|not|unable to|no)\s+(?:been\s+)?(?:pass|passed|passing)\s+(?:any\s+)?urine\b",
    r"\bno urine\b|\burinary retention\b",
    r"\bvomiting blood\b|\bblood in vomit\b",
    r"\bsuicid|\bkill myself\b|\bend my life\b",
]

# Questions the system declines, with the reason and the nearest thing it can
# actually do. A refusal that offers nothing teaches people to stop asking.
REFUSAL_RULES: list[tuple[str, str, str]] = [
    (
        r"\b(?:do|have) i (?:have|got)\b.{0,30}\b(cancer|tumou?r|malignan)",
        "AIRA cannot tell anyone whether they have cancer. Only a test can do that.",
        "It can tell you how long your symptom has lasted against what is expected, and what the guidelines say should happen next.",
    ),
    (
        r"\bis (?:it|this|that)\b.{0,20}\b(cancer|tumou?r|malignan)",
        "AIRA cannot tell you whether something is cancer.",
        "It can tell you whether this has gone on longer than expected and what test is usually done at this point.",
    ),
    (
        r"\b(?:which|what)\s+(?:medicine|tablet|drug|antibiotic|dose|dosage)\b",
        "AIRA does not recommend medicines or doses.",
        "That decision belongs to the clinician who prescribed for you. AIRA can show them what has already been tried and did not work.",
    ),
    (
        r"\bshould i (?:stop|start|change)\b.{0,25}\b(?:medicine|tablet|treatment|chemo)",
        "AIRA cannot tell you to start, stop or change a treatment.",
        "Take this question to the clinician who prescribed it. The handoff card lists what you have been given so far.",
    ),
    (
        # People ask for a prognosis in more ways than they ask for anything
        # else, and almost never in the textbook phrasing. "Will this kill
        # me" and "am I going to die" are the same question as "what is my
        # life expectancy", and answering two of the three is worse than
        # answering none, because it teaches people the filter is arbitrary.
        r"\bhow long\b.{0,20}\bto live\b|\bhow long have i got\b|\blife expectancy\b"
        r"|\bsurvival rate\b|\bam i (?:going to|gonna) die\b|\bwill (?:i|this|it) kill\b"
        r"|\bwill i die\b|\bis this (?:fatal|terminal)\b|\bhow serious is (?:this|it)\b"
        r"|\bchances? of (?:survival|surviving|dying)\b",
        "AIRA does not give prognoses.",
        "Nothing in a symptom history supports a statement about how long anyone will live. "
        "What it can tell you is how long your symptom has gone on and what the guidelines "
        "say should be done about it next.",
    ),
    (
        r"\b(?:read|look at|check|interpret)\b.{0,25}\b(?:x-?ray|scan|ct|mri|mammogram|image|photo|picture)\b",
        "AIRA cannot interpret images. It does not read X-rays, scans or photographs.",
        "If you type out what the report says, AIRA can tell you what the reference range for that test is and what the guidelines do with that result.",
    ),
    (
        r"\bstage\b.{0,20}\b(?:cancer|tumou?r)\b|\bwhat stage\b",
        "AIRA cannot stage a cancer. Staging needs imaging and a biopsy.",
        "It can show a clinician the full history so the right investigation gets ordered.",
    ),
]

EMERGENCY_TEXT = {
    "en": (
        "This needs help now, not an answer from an app. Go to the nearest hospital "
        "emergency department, or call 108 for an ambulance. Take someone with you if you can."
    ),
    "hi": (
        "इसमें अभी मदद चाहिए, ऐप के जवाब का इंतज़ार नहीं। नज़दीकी अस्पताल की इमरजेंसी में जाएँ, "
        "या एम्बुलेंस के लिए 108 पर कॉल करें। हो सके तो किसी को साथ ले जाएँ।"
    ),
    "kn": (
        "ಇದಕ್ಕೆ ಈಗಲೇ ಸಹಾಯ ಬೇಕು, ಆ್ಯಪ್‌ನ ಉತ್ತರವಲ್ಲ. ಹತ್ತಿರದ ಆಸ್ಪತ್ರೆಯ ತುರ್ತು ವಿಭಾಗಕ್ಕೆ ಹೋಗಿ, "
        "ಅಥವಾ ಆ್ಯಂಬುಲೆನ್ಸ್‌ಗಾಗಿ 108 ಗೆ ಕರೆ ಮಾಡಿ. ಸಾಧ್ಯವಾದರೆ ಯಾರನ್ನಾದರೂ ಜೊತೆಗೆ ಕರೆದೊಯ್ಯಿರಿ."
    ),
}


@dataclass
class Route:
    action: str  # "answer" | "refuse" | "emergency"
    reason: str | None = None
    alternative: str | None = None


def route(question: str) -> Route:
    q = question.lower()

    for pattern in EMERGENCY_PATTERNS:
        if re.search(pattern, q):
            return Route(action="emergency")

    for pattern, reason, alternative in REFUSAL_RULES:
        if re.search(pattern, q):
            return Route(action="refuse", reason=reason, alternative=alternative)

    return Route(action="answer")


# ─────────────────────────────────────────────────────────────────────────────
# SCRUB
# ─────────────────────────────────────────────────────────────────────────────

_PHONE = re.compile(r"\b(?:\+?91[\s-]?)?[6-9]\d{9}\b")
_AIRA_CODE = re.compile(r"\bAIRA-[A-Z0-9]{4}-[A-Z0-9]{4}\b", re.I)
_ABHA = re.compile(r"\b\d{2}-\d{4}-\d{4}-\d{4}\b")
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_UHID = re.compile(r"\b(?:uhid|mrn|ip\s?no|op\s?no|reg(?:istration)?\s?no)\W{0,3}[\w/-]+", re.I)

REDACTIONS = [
    (_EMAIL, "[email]"),
    (_PHONE, "[phone]"),
    (_AADHAAR, "[id]"),
    (_ABHA, "[abha]"),
    (_AIRA_CODE, "[code]"),
    (_UHID, "[hospital-id]"),
    (_DATE, "[date]"),
]


def age_band(age: int | None) -> str:
    """A band, never the number. An exact age plus a village plus a sex is
    identifying in a place where three hundred people live."""
    if age is None:
        return "unknown"
    if age < 15:
        return "child (under 15)"
    if age < 30:
        return "15-29"
    if age < 40:
        return "30-39"
    if age < 50:
        return "40-49"
    if age < 60:
        return "50-59"
    if age < 70:
        return "60-69"
    return "70 or over"


def scrub(text: str) -> tuple[str, list[str]]:
    """Strip direct identifiers. Returns (clean_text, what_was_removed)."""
    removed: list[str] = []
    out = text
    for pattern, placeholder in REDACTIONS:
        out, n = pattern.subn(placeholder, out)
        if n:
            removed.append(f"{placeholder} x{n}")
    return out, removed


# Names are not regex-detectable in general, so the caller passes the names it
# knows about and they are removed by exact match. Everything the API sends to
# the model is assembled by us, so this list is complete by construction.
def scrub_names(text: str, names: list[str]) -> str:
    out = text
    for name in names:
        for part in [name] + name.split():
            if len(part) >= 3:
                out = re.sub(rf"\b{re.escape(part)}\b", "[name]", out, flags=re.I)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# AUDIENCE
# ─────────────────────────────────────────────────────────────────────────────

# Vocabulary that belongs in a clinician's reading and not in a patient's.
CLINICAL_ONLY_TERMS = [
    r"\bcarcinom\w*", r"\bmalignan\w*", r"\bneoplas\w*", r"\bmetastas\w*",
    r"\badenocarcinoma\b", r"\blymphom\w*", r"\bleukaemi\w*|\bleukemi\w*",
    r"\bprimary (?:site|tumou?r)\b", r"\bhistopatholog\w*", r"\bdifferential\b",
    r"\bpathognomonic\b", r"\bstaging\b", r"\bprognos\w*",
]

# Naming the SITE is the line, not naming cancer. "Free cervical screening"
# and "what happens at a breast check" are exactly what this app should say
# out loud. "Oesophageal or stomach cancer" said to a woman with acidity is a
# diagnosis she did not ask for, delivered by a phone, with nine hours until
# the clinic opens. So: the pairing is banned, the words alone are not.
SITE_NAMED_CANCER = [
    r"\b(?:oesophageal|esophageal|gastric|stomach|colorectal|bowel|colon|rectal"
    r"|lung|oral|mouth|tongue|laryngeal|nasopharyngeal|throat|pancreatic"
    r"|hepatocellular|liver|ovarian|cervical|endometrial|uterine|prostate"
    r"|bladder|renal|kidney|thyroid|breast|skin|bone|brain|blood)"
    r"[\s-]+(?:cancers?|tumou?rs?|malignanc\w*)\b",
    r"\bcancers?\s+of\s+the\s+\w+",
]

PATIENT_BANNED = CLINICAL_ONLY_TERMS + SITE_NAMED_CANCER + [
    r"\b\d{1,3}(?:\.\d+)?\s?%",          # no probabilities to a patient
    r"\blog-?odds\b", r"\bAUPRC\b", r"\bPPV\b", r"\bsensitivit\w*",
    r"\btier\s+(?:HIGH|MODERATE|LOW)\b",
]


@dataclass
class AudiencePolicy:
    name: str
    may_see_probability: bool
    may_see_site_vocabulary: bool
    may_see_model_internals: bool
    reading_level: str
    banned: list[str]


PATIENT = AudiencePolicy(
    name="patient",
    may_see_probability=False,
    may_see_site_vocabulary=False,
    may_see_model_internals=False,
    reading_level=(
        "Short sentences. Everyday words. No medical vocabulary unless you "
        "immediately explain it. Never name a cancer type. Never give a "
        "percentage. Speak to the person, not about them."
    ),
    banned=PATIENT_BANNED,
)

CLINICIAN = AudiencePolicy(
    name="clinician",
    may_see_probability=True,
    may_see_site_vocabulary=True,
    may_see_model_internals=True,
    reading_level=(
        "Terse and technical. Assume a medical officer at a community health "
        "centre. Lead with the numbers and the guideline section. No "
        "reassurance, no hedging padding."
    ),
    banned=[
        # Even a clinician is not told a diagnosis by this system.
        r"\b(?:this (?:is|represents)|diagnosis is)\b.{0,20}\b(?:cancer|carcinoma)\b",
    ],
)

POLICIES = {"patient": PATIENT, "clinician": CLINICIAN, "admin": CLINICIAN}


def policy_for(role: str) -> AudiencePolicy:
    return POLICIES.get(role.lower(), PATIENT)


def audience_violations(answer: str, policy: AudiencePolicy) -> list[str]:
    """Terms that must not appear in this audience's rendering."""
    found = []
    for pattern in policy.banned:
        m = re.search(pattern, answer, flags=re.I)
        if m:
            found.append(m.group(0).strip())
    return sorted(set(found))
