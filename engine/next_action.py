"""
The Next Action engine.

    "A risk score is not an answer. Tell me what to do now."

Every other symptom checker stops at a number. AIRA's whole thesis is that the
delay it is fighting lives in the gap between "the system knew what should
happen" and "it actually happened" - so after every assessment it derives a
CARE STATE and, from that, a concrete checklist.

This module is pure: it takes plain dicts and lists (assembled by the API
layer from the database) and returns a `CarePlan` - a state plus an ordered
list of `TaskSpec`. It imports nothing from FastAPI, SQLAlchemy or the model.
The persistence and the i18n rendering happen a layer up.

THE STATES, IN THE ORDER THEY ADVANCE

    MONITORING          nothing is flagged; we are just watching
    NEEDS_CARE          a pattern is flagged, no clinician has seen it yet
    VISIT_LOGGED        a consultation happened, no written plan yet
    PLAN_RECEIVED       a doctor released a plan; it is being followed
    FOLLOW_UP_DUE       the follow-up window is open; how did it go?
    LOOP_COMPLETE       consultation -> plan -> test -> result -> review -> outcome

A state never decides a task is *done*. It decides which tasks EXIST. Whether
each one is pending, started or finished is the patient's to say (or a hard
fact - a released note, an uploaded report - makes it true). See
`AUTO_COMPLETE` for the short list of facts allowed to tick a box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# States
# ─────────────────────────────────────────────────────────────────────────────

MONITORING = "MONITORING"
NEEDS_CARE = "NEEDS_CARE"
VISIT_LOGGED = "VISIT_LOGGED"
PLAN_RECEIVED = "PLAN_RECEIVED"
FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
LOOP_COMPLETE = "LOOP_COMPLETE"

# The fact that is allowed to auto-complete a task. Anything not on this list
# needs a patient tap.
AUTO_COMPLETE = {
    "consent_active",          # a doctor now has live access
    "note_released",           # a written plan arrived
    "document_uploaded",       # a report was uploaded
    "document_reviewed",       # the doctor reviewed it
    "investigation_recorded",  # an episode shows a test was actually done
    "care_response",           # the patient recorded how it went
}


@dataclass
class TaskSpec:
    key: str
    labels: dict[str, str]
    source: str = "aira"
    due_date: date | None = None
    auto_complete_on: str | None = None
    note_id: str | None = None


@dataclass
class CarePlan:
    state: str
    headline: dict[str, str]
    subhead: dict[str, str]
    tasks: list[TaskSpec] = field(default_factory=list)
    primary_cta: str | None = None          # "find_care" | "record_response" | "upload_report" | None
    secondary_cta: str | None = None        # "why_flagged" | "view_plan" | None
    escalated: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Task library. One place, so the wording is consistent and translatable.
# ─────────────────────────────────────────────────────────────────────────────

def _t(en: str, hi: str, kn: str) -> dict[str, str]:
    return {"en": en, "hi": hi, "kn": kn}


TASKS: dict[str, dict[str, str]] = {
    "review_flag": _t(
        "See why AIRA flagged this",
        "AIRA ने इसे क्यों चिह्नित किया, यह देखें",
        "AIRA ಇದನ್ನು ಏಕೆ ಗುರುತಿಸಿದೆ ಎಂದು ನೋಡಿ",
    ),
    "gather_reports": _t(
        "Gather your earlier medical reports",
        "अपनी पुरानी मेडिकल रिपोर्ट इकट्ठा करें",
        "ನಿಮ್ಮ ಹಿಂದಿನ ವೈದ್ಯಕೀಯ ವರದಿಗಳನ್ನು ಸಂಗ್ರಹಿಸಿ",
    ),
    "book_evaluation": _t(
        "Book a clinical evaluation",
        "जाँच के लिए डॉक्टर से समय लें",
        "ವೈದ್ಯಕೀಯ ಪರಿಶೀಲನೆಗೆ ಸಮಯ ನಿಗದಿಪಡಿಸಿ",
    ),
    "share_history": _t(
        "Give the doctor access to your history",
        "डॉक्टर को अपनी हिस्ट्री देखने की अनुमति दें",
        "ವೈದ್ಯರಿಗೆ ನಿಮ್ಮ ಇತಿಹಾಸ ನೋಡಲು ಅನುಮತಿ ಕೊಡಿ",
    ),
    "attend_consultation": _t(
        "Attend the consultation",
        "जाँच के लिए जाएँ",
        "ಸಮಾಲೋಚನೆಗೆ ಹಾಜರಾಗಿ",
    ),
    "complete_investigation": _t(
        "Complete the test the doctor asked for",
        "डॉक्टर ने जो जाँच बताई है वह कराएँ",
        "ವೈದ್ಯರು ಹೇಳಿದ ಪರೀಕ್ಷೆಯನ್ನು ಮಾಡಿಸಿ",
    ),
    "follow_treatment": _t(
        "Follow the treatment the doctor gave",
        "डॉक्टर की बताई दवा/इलाज लें",
        "ವೈದ್ಯರು ನೀಡಿದ ಚಿಕಿತ್ಸೆಯನ್ನು ಅನುಸರಿಸಿ",
    ),
    "upload_result": _t(
        "Upload your test result",
        "अपनी जाँच रिपोर्ट अपलोड करें",
        "ನಿಮ್ಮ ಪರೀಕ್ಷಾ ವರದಿಯನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ",
    ),
    "await_plan": _t(
        "Wait for your doctor's written plan",
        "डॉक्टर की लिखित सलाह का इंतज़ार करें",
        "ವೈದ್ಯರ ಲಿಖಿತ ಯೋಜನೆಗಾಗಿ ಕಾಯಿರಿ",
    ),
    "return_followup": _t(
        "Return to the doctor for follow-up",
        "फ़ॉलो-अप के लिए डॉक्टर के पास दोबारा जाएँ",
        "ಫಾಲೋ-ಅಪ್‌ಗಾಗಿ ವೈದ್ಯರ ಬಳಿ ಮತ್ತೆ ಹೋಗಿ",
    ),
    "record_response": _t(
        "Tell us whether the treatment helped",
        "बताएँ कि इलाज से आराम हुआ या नहीं",
        "ಚಿಕಿತ್ಸೆಯಿಂದ ಸಹಾಯವಾಯಿತೇ ಎಂದು ತಿಳಿಸಿ",
    ),
    "get_report_reviewed": _t(
        "Ask your doctor to review the report you uploaded",
        "अपलोड की गई रिपोर्ट डॉक्टर से देखने को कहें",
        "ಅಪ್‌ಲೋಡ್ ಮಾಡಿದ ವರದಿಯನ್ನು ವೈದ್ಯರಿಂದ ಪರಿಶೀಲಿಸಿ",
    ),
}


HEAD = {
    MONITORING: _t(
        "We are keeping track",
        "हम नज़र रख रहे हैं",
        "ನಾವು ಗಮನಿಸುತ್ತಿದ್ದೇವೆ",
    ),
    NEEDS_CARE: _t(
        "This pattern should be looked at by a doctor",
        "इस पैटर्न को डॉक्टर को दिखाना चाहिए",
        "ಈ ಮಾದರಿಯನ್ನು ವೈದ್ಯರು ನೋಡಬೇಕು",
    ),
    VISIT_LOGGED: _t(
        "You have seen a doctor — here is what to finish",
        "आपने डॉक्टर को दिखाया — अब यह पूरा करें",
        "ನೀವು ವೈದ್ಯರನ್ನು ಭೇಟಿಯಾಗಿದ್ದೀರಿ — ಇದನ್ನು ಮುಗಿಸಿ",
    ),
    PLAN_RECEIVED: _t(
        "Your doctor has given you a plan",
        "आपके डॉक्टर ने एक प्लान दिया है",
        "ನಿಮ್ಮ ವೈದ್ಯರು ಒಂದು ಯೋಜನೆ ನೀಡಿದ್ದಾರೆ",
    ),
    FOLLOW_UP_DUE: _t(
        "It is time for your follow-up",
        "आपके फ़ॉलो-अप का समय है",
        "ನಿಮ್ಮ ಫಾಲೋ-ಅಪ್ ಸಮಯ ಬಂದಿದೆ",
    ),
    LOOP_COMPLETE: _t(
        "This care pathway is complete",
        "यह देखभाल का रास्ता पूरा हुआ",
        "ಈ ಆರೈಕೆ ಹಾದಿ ಪೂರ್ಣಗೊಂಡಿದೆ",
    ),
}

SUB = {
    MONITORING: _t(
        "Nothing needs a doctor right now. Add a symptom whenever something changes.",
        "अभी किसी डॉक्टर की ज़रूरत नहीं। कुछ बदले तो लक्षण जोड़ें।",
        "ಈಗ ವೈದ್ಯರ ಅಗತ್ಯವಿಲ್ಲ. ಏನಾದರೂ ಬದಲಾದರೆ ಲಕ್ಷಣ ಸೇರಿಸಿ.",
    ),
    NEEDS_CARE: _t(
        "Your symptoms have gone on longer than expected and repeated treatment has not settled them. That does not mean anything is seriously wrong — it means a qualified doctor should review the whole picture.",
        "आपके लक्षण उम्मीद से ज़्यादा समय तक रहे हैं और बार-बार इलाज से भी ठीक नहीं हुए। इसका मतलब यह नहीं कि कुछ गंभीर है — इसका मतलब है कि एक योग्य डॉक्टर को पूरी बात देखनी चाहिए।",
        "ನಿಮ್ಮ ಲಕ್ಷಣಗಳು ನಿರೀಕ್ಷೆಗಿಂತ ಹೆಚ್ಚು ಕಾಲ ಇವೆ ಮತ್ತು ಪದೇ ಪದೇ ಚಿಕಿತ್ಸೆಯಿಂದಲೂ ಗುಣವಾಗಿಲ್ಲ. ಇದು ಗಂಭೀರ ಎಂದಲ್ಲ — ಅರ್ಹ ವೈದ್ಯರು ಇಡೀ ಚಿತ್ರವನ್ನು ನೋಡಬೇಕು ಎಂದರ್ಥ.",
    ),
    VISIT_LOGGED: _t(
        "Finish the test and treatment the doctor asked for, and upload the result so it stays on your record.",
        "डॉक्टर की बताई जाँच और इलाज पूरा करें, और रिपोर्ट अपलोड करें ताकि वह रिकॉर्ड में रहे।",
        "ವೈದ್ಯರು ಹೇಳಿದ ಪರೀಕ್ಷೆ ಮತ್ತು ಚಿಕಿತ್ಸೆಯನ್ನು ಮುಗಿಸಿ, ವರದಿಯನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ.",
    ),
    PLAN_RECEIVED: _t(
        "Follow each step below. AIRA will check back with you near the follow-up date.",
        "नीचे दिए हर कदम का पालन करें। फ़ॉलो-अप की तारीख के पास AIRA आपसे पूछेगा।",
        "ಕೆಳಗಿನ ಪ್ರತಿ ಹೆಜ್ಜೆಯನ್ನು ಅನುಸರಿಸಿ. ಫಾಲೋ-ಅಪ್ ದಿನಾಂಕದ ಬಳಿ AIRA ನಿಮ್ಮನ್ನು ಕೇಳುತ್ತದೆ.",
    ),
    FOLLOW_UP_DUE: _t(
        "Tell us how you are feeling and whether the treatment helped. If it has not, we will make sure your doctor knows.",
        "बताएँ कि आप कैसा महसूस कर रहे हैं और इलाज से फ़ायदा हुआ या नहीं। अगर नहीं, तो हम आपके डॉक्टर को बताएँगे।",
        "ನೀವು ಹೇಗಿದ್ದೀರಿ ಮತ್ತು ಚಿಕಿತ್ಸೆ ಸಹಾಯ ಮಾಡಿತೇ ಎಂದು ತಿಳಿಸಿ. ಇಲ್ಲದಿದ್ದರೆ ನಿಮ್ಮ ವೈದ್ಯರಿಗೆ ತಿಳಿಸುತ್ತೇವೆ.",
    ),
    LOOP_COMPLETE: _t(
        "The documented care pathway for this concern is complete. This does not mean you are cleared of anything — it means every step that was recommended has been done and recorded.",
        "इस परेशानी के लिए दर्ज देखभाल का रास्ता पूरा हो गया है। इसका मतलब यह नहीं कि आप किसी चीज़ से मुक्त हैं — इसका मतलब है कि हर सुझाया गया कदम पूरा और दर्ज हो चुका है।",
        "ಈ ಸಮಸ್ಯೆಗೆ ದಾಖಲಾದ ಆರೈಕೆ ಹಾದಿ ಪೂರ್ಣಗೊಂಡಿದೆ. ಇದು ನೀವು ಯಾವುದರಿಂದಲೂ ಮುಕ್ತ ಎಂದಲ್ಲ — ಶಿಫಾರಸು ಮಾಡಿದ ಪ್ರತಿ ಹೆಜ್ಜೆಯೂ ಪೂರ್ಣಗೊಂಡು ದಾಖಲಾಗಿದೆ ಎಂದರ್ಥ.",
    ),
}


def _spec(key: str, **kw) -> TaskSpec:
    return TaskSpec(key=key, labels=TASKS[key], **kw)


# ─────────────────────────────────────────────────────────────────────────────
# The state machine
# ─────────────────────────────────────────────────────────────────────────────

def derive(
    *,
    assessment: dict | None,
    episodes: list[dict],
    released_notes: list[dict],
    documents: list[dict],
    care_responses: list[dict],
    consent_active: bool,
    today: date | None = None,
) -> CarePlan:
    """`released_notes` and `care_responses` are newest-first. `episodes` and
    `documents` order does not matter."""
    today = today or date.today()

    tier = (assessment or {}).get("tier", "LOW")
    ladder = (assessment or {}).get("ladder_level", 0)
    flagged = tier in ("HIGH", "MODERATE") or ladder >= 1

    latest_note = released_notes[0] if released_notes else None
    latest_response = care_responses[0] if care_responses else None
    unreviewed_docs = [d for d in documents if not d.get("reviewed_at")]
    any_investigation = any(
        (e.get("investigation_ordered") or "none") != "none" for e in episodes
    ) or any(d.get("reviewed_at") for d in documents)

    # "A doctor has seen this" means a doctor engaged with the WHOLE picture
    # through AIRA - a clinician-sourced episode, or a released plan. The
    # patient's own record of earlier outside visits ("Doctor A gave an
    # antacid") does NOT count: those visits are the flagged pattern, not
    # progress past it.
    doctor_has_seen = bool(latest_note) or any(
        e.get("source") == "clinician" for e in episodes
    )

    # ── LOOP_COMPLETE ───────────────────────────────────────────────────────
    if (
        latest_note
        and any_investigation
        and documents
        and all(d.get("reviewed_at") for d in documents)
        and latest_response
    ):
        return CarePlan(
            state=LOOP_COMPLETE,
            headline=HEAD[LOOP_COMPLETE],
            subhead=SUB[LOOP_COMPLETE],
            secondary_cta="view_plan",
        )

    # ── FOLLOW_UP_DUE / PLAN_RECEIVED ───────────────────────────────────────
    if latest_note:
        follow_days = latest_note.get("follow_up_days")
        released_on = latest_note.get("released_on")  # date
        due = None
        if follow_days and released_on:
            due = released_on + timedelta(days=int(follow_days))

        window_open = due is not None and today >= due - timedelta(days=3)
        needs_response = latest_response is None or (
            due is not None
            and latest_response.get("created_on")
            and latest_response["created_on"] < (released_on or today)
        )

        escalated = bool(
            latest_response
            and latest_response.get("feeling") == "worse"
            or (latest_response and latest_response.get("helped") == "no")
        )

        tasks = [
            _spec("follow_treatment", note_id=latest_note["id"]),
            _spec(
                "complete_investigation",
                note_id=latest_note["id"],
                auto_complete_on="investigation_recorded",
            ),
            _spec(
                "upload_result",
                note_id=latest_note["id"],
                auto_complete_on="document_uploaded",
            ),
        ]
        if unreviewed_docs:
            tasks.append(
                _spec("get_report_reviewed", auto_complete_on="document_reviewed")
            )
        if due is not None:
            tasks.append(_spec("return_followup", note_id=latest_note["id"], due_date=due))
        tasks.append(
            _spec(
                "record_response",
                note_id=latest_note["id"],
                auto_complete_on="care_response",
            )
        )

        if window_open and needs_response:
            return CarePlan(
                state=FOLLOW_UP_DUE,
                headline=HEAD[FOLLOW_UP_DUE],
                subhead=SUB[FOLLOW_UP_DUE],
                tasks=tasks,
                primary_cta="record_response",
                secondary_cta="view_plan",
                escalated=escalated,
            )
        return CarePlan(
            state=PLAN_RECEIVED,
            headline=HEAD[PLAN_RECEIVED],
            subhead=SUB[PLAN_RECEIVED],
            tasks=tasks,
            primary_cta="upload_report" if not documents else None,
            secondary_cta="view_plan",
            escalated=escalated,
        )

    # ── VISIT_LOGGED ───────────────────────────────────────────────────────
    if doctor_has_seen:
        tasks = [
            _spec("complete_investigation", auto_complete_on="investigation_recorded"),
            _spec("follow_treatment"),
            _spec("upload_result", auto_complete_on="document_uploaded"),
            _spec("await_plan", auto_complete_on="note_released"),
        ]
        return CarePlan(
            state=VISIT_LOGGED,
            headline=HEAD[VISIT_LOGGED],
            subhead=SUB[VISIT_LOGGED],
            tasks=tasks,
            primary_cta="upload_report",
            secondary_cta="why_flagged",
        )

    # ── NEEDS_CARE ─────────────────────────────────────────────────────────
    if flagged:
        tasks = [
            _spec("review_flag"),
            _spec("gather_reports"),
            _spec("book_evaluation"),
            _spec("share_history", auto_complete_on="consent_active"),
            _spec("attend_consultation", auto_complete_on="note_released"),
        ]
        if unreviewed_docs:
            tasks.insert(
                2, _spec("get_report_reviewed", auto_complete_on="document_reviewed")
            )
        return CarePlan(
            state=NEEDS_CARE,
            headline=HEAD[NEEDS_CARE],
            subhead=SUB[NEEDS_CARE],
            tasks=tasks,
            primary_cta="find_care",
            secondary_cta="why_flagged",
        )

    # ── MONITORING ─────────────────────────────────────────────────────────
    return CarePlan(
        state=MONITORING,
        headline=HEAD[MONITORING],
        subhead=SUB[MONITORING],
    )
