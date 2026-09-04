"""
The handover note: drafted by AIRA, edited by the clinician, released to the
patient in their own language.

WHY THIS EXISTS

The clinician already has everything on screen. The patient walks out with
nothing, and by the evening remembers roughly a third of what was said - less
if they were frightened, less again if the consultation was in a language they
read poorly. The gap between "the doctor knew what to do" and "the patient did
it" is where a lot of the delay this project is about actually lives.

So: AIRA drafts the note from what the rules already decided, the clinician
edits it in the room, and releases it. It lands on the patient's phone before
they have left the building.

WHAT THE CLINICIAN CAN CHANGE, AND WHAT IS RECORDED

Everything. The text, the investigations, the follow-up interval. AIRA's draft
is a starting point, not a recommendation the clinician has to argue with.
Both versions are kept - `draft_text` as generated and `final_text` as sent -
because the edit distance between them is the only honest measure of whether
the drafting is any good, and discarding it would mean never being able to
improve it.

THE ONE THING IT WILL NOT DO

It will not release a note the clinician has not opened. There is no
auto-send. A generated note that reaches a patient without a human reading it
is exactly the failure this architecture exists to prevent.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from llm.answer import SYSTEM
from rag.corpus import investigation_label
from rag.store import retriever
from rag.verify import verify

from .. import audit
from ..db import get_db
from ..deps import authorise_patient_access, current_user, require_doctor, require_patient
from ..llm_service import gemini
from ..service import rules
from ..tables import (
    Assessment,
    ClinicianNote,
    DoctorProfile,
    PatientProfile,
    Role,
    User,
)
from ..ws import notify

router = APIRouter(tags=["notes"])


class NoteUpdate(BaseModel):
    final_text: str = Field(min_length=10, max_length=4000)
    investigations: list[str] = []
    follow_up_days: int | None = Field(default=None, ge=1, le=365)
    language: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Drafting
# ─────────────────────────────────────────────────────────────────────────────

HEADINGS = {
    "en": ["What we found", "What happens next", "Come back if"],
    "hi": ["हमें क्या मिला", "आगे क्या होगा", "वापस आएँ अगर"],
    "kn": ["ನಾವು ಏನು ಕಂಡುಕೊಂಡೆವು", "ಮುಂದೇನಾಗುತ್ತದೆ", "ಮತ್ತೆ ಬನ್ನಿ ಒಂದು ವೇಳೆ"],
}

SAFETY_NET = {
    "en": "you cough or pass blood, you cannot swallow, you lose more weight, or you feel much worse.",
    "hi": "खून आए, निगलने में दिक्कत हो, और वजन घटे, या तबीयत बहुत बिगड़े।",
    "kn": "ರಕ್ತ ಬಂದರೆ, ನುಂಗಲು ಆಗದಿದ್ದರೆ, ಇನ್ನಷ್ಟು ತೂಕ ಕಡಿಮೆಯಾದರೆ, ಅಥವಾ ತುಂಬಾ ಕೆಟ್ಟದಾಗಿ ಅನಿಸಿದರೆ.",
}


def _template_note(
    features: dict, investigations: list[str], follow_up: int, lang: str, rs
) -> str:
    """The deterministic draft. Every number in it comes from the stored
    assessment, so it is correct whether or not a model is available."""
    h = HEADINGS.get(lang, HEADINGS["en"])
    symptom = features.get("anchor_symptom") or "your symptom"
    spec = rs.symptoms.get(symptom, {})
    label = (spec.get("label") or {}).get(lang) or (spec.get("label") or {}).get("en") or symptom
    days = features.get("days_elapsed", 0)
    window = features.get("safe_window_days", 0)
    tests = ", ".join(i.replace("_", " ") for i in investigations) or "the tests we discussed"

    if lang == "hi":
        return (
            f"{h[0]}:\n{label} आपको {days} दिन से है। आमतौर पर इस तरह की परेशानी "
            f"{window} दिन में ठीक हो जाती है, इसलिए अब जाँच करानी चाहिए।\n\n"
            f"{h[1]}:\nजाँच: {tests}। {follow_up} दिन में दोबारा दिखाएँ, "
            f"रिपोर्ट साथ लाएँ।\n\n{h[2]}:\n{SAFETY_NET['hi']}"
        )
    if lang == "kn":
        return (
            f"{h[0]}:\n{label} ನಿಮಗೆ {days} ದಿನಗಳಿಂದ ಇದೆ. ಸಾಮಾನ್ಯವಾಗಿ ಇಂತಹ ತೊಂದರೆ "
            f"{window} ದಿನಗಳಲ್ಲಿ ಸರಿಹೋಗುತ್ತದೆ, ಆದ್ದರಿಂದ ಈಗ ಪರೀಕ್ಷೆ ಮಾಡಿಸಬೇಕು.\n\n"
            f"{h[1]}:\nಪರೀಕ್ಷೆ: {tests}. {follow_up} ದಿನಗಳಲ್ಲಿ ಮತ್ತೆ ತೋರಿಸಿ, "
            f"ವರದಿ ತನ್ನಿ.\n\n{h[2]}:\n{SAFETY_NET['kn']}"
        )
    return (
        f"{h[0]}:\nYou have had {label.lower()} for {days} days. A problem like this "
        f"usually settles within {window} days, so it should be tested now rather "
        f"than treated again.\n\n"
        f"{h[1]}:\nTests: {tests}. Come back in {follow_up} days and bring the "
        f"reports with you.\n\n"
        f"{h[2]}:\n{SAFETY_NET['en']}"
    )


def _polish(draft: str, lang: str, facts: dict) -> tuple[str, str]:
    """Optionally have the model make the template read less like a form.

    It is given the finished note and told to rewrite it, not to write one.
    If the rewrite fails verification, the template ships unchanged - which
    is why the template has to be good enough on its own, and is.
    """
    client = gemini()
    if not client.available:
        return draft, "template"

    r = retriever()
    hits = r.search(facts.get("anchor_symptom", "") + " safe window next step", k=4)
    prompt = (
        "READER: patient. Short sentences, everyday words, no medical jargon.\n"
        f"LANGUAGE: {'English' if lang == 'en' else 'Hindi' if lang == 'hi' else 'Kannada'}.\n\n"
        "TASK: rewrite the NOTE below so it reads like a person wrote it. Keep the "
        "three headings. Keep every number exactly as it is. Do not add advice, do "
        "not add a cause, do not name any illness.\n\n"
        f"NOTE:\n{draft}\n"
    )
    result = client.generate(system=SYSTEM, prompt=prompt, task="note", max_output_tokens=800)
    text = result.get("text")
    if not text:
        return draft, "template"
    verdict = verify(text, hits, known_facts=facts, require_quote_for_numbers=False)
    if verdict.unsupported_numbers or verdict.problems and "numbers" in str(verdict.problems):
        return draft, "template"
    client.commit({**result, "text": text})
    return text, "ai-polished"


# ─────────────────────────────────────────────────────────────────────────────
# Clinician endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/clinic/patients/{patient_id}/note/draft", status_code=201)
def draft(
    patient_id: str,
    request: Request,
    access=Depends(authorise_patient_access),
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    _, consent = access
    prof = db.get(PatientProfile, patient_id)
    rs = rules()

    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == patient_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )
    if latest is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no assessment to draft from")

    features = json.loads(latest.features_json or "{}")
    investigations = json.loads(latest.investigations_json or "[]")[:3]
    # Higher tiers get a shorter leash. This is the safety net made concrete:
    # the interval is the promise that somebody will look again.
    follow_up = {"HIGH": 14, "MODERATE": 28}.get(latest.tier, 42)
    lang = prof.language or "en"

    template = _template_note(features, investigations, follow_up, lang, rs)
    text, drafted_by = _polish(template, lang, features)

    row = ClinicianNote(
        patient_id=patient_id,
        doctor_id=user.id,
        assessment_id=latest.id,
        consent_id=consent.id if consent else None,
        language=lang,
        draft_text=text,
        final_text=text,
        investigations=json.dumps(investigations),
        follow_up_days=follow_up,
        drafted_by=drafted_by,
        status="draft",
    )
    db.add(row)
    db.commit()

    audit.record(
        db,
        action="NOTE_DRAFTED",
        actor_user_id=user.id,
        actor_role="DOCTOR",
        target_type="note",
        target_id=row.id,
        consent_id=consent.id if consent else None,
        detail={"drafted_by": drafted_by, "language": lang},
        request=request,
    )
    return _note_payload(row, technical=True)


@router.get("/clinic/patients/{patient_id}/notes")
def list_for_patient(
    patient_id: str,
    access=Depends(authorise_patient_access),
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ClinicianNote)
        .filter(ClinicianNote.patient_id == patient_id)
        .order_by(ClinicianNote.created_at.desc())
        .all()
    )
    return [_note_payload(r, technical=True) for r in rows]


@router.put("/clinic/notes/{note_id}")
def edit(
    note_id: str,
    body: NoteUpdate,
    request: Request,
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    row = _own_note(db, note_id, user)
    if row.status == "released":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this note has already been given to the patient. write a new one rather than "
            "changing what they were told.",
        )
    row.final_text = body.final_text
    row.investigations = json.dumps(body.investigations)
    row.follow_up_days = body.follow_up_days
    if body.language:
        row.language = body.language
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _note_payload(row, technical=True)


@router.post("/clinic/notes/{note_id}/release")
def release(
    note_id: str,
    request: Request,
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    """Hand it to the patient. Their phone lights up before they leave."""
    row = _own_note(db, note_id, user)
    if row.status == "released":
        return _note_payload(row, technical=True)

    row.status = "released"
    row.released_at = datetime.now(timezone.utc)
    db.commit()

    doctor = db.get(DoctorProfile, user.id)
    audit.record(
        db,
        action="NOTE_RELEASED",
        actor_user_id=user.id,
        actor_role="DOCTOR",
        target_type="note",
        target_id=row.id,
        consent_id=row.consent_id,
        detail={
            "edited": row.final_text.strip() != row.draft_text.strip(),
            "chars_changed": abs(len(row.final_text) - len(row.draft_text)),
        },
        request=request,
    )
    notify(
        row.patient_id,
        "note.released",
        {
            "note_id": row.id,
            "doctor_name": doctor.name if doctor else "your doctor",
            "follow_up_days": row.follow_up_days,
        },
    )
    return _note_payload(row, technical=True)


# ─────────────────────────────────────────────────────────────────────────────
# Patient endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/me/notes")
def my_notes(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    rows = (
        db.query(ClinicianNote)
        .filter(ClinicianNote.patient_id == user.id, ClinicianNote.status == "released")
        .order_by(ClinicianNote.released_at.desc())
        .all()
    )
    for r in rows:
        if r.read_at is None:
            r.read_at = datetime.now(timezone.utc)
    db.commit()

    out = []
    for r in rows:
        doctor = db.get(DoctorProfile, r.doctor_id)
        payload = _note_payload(r, technical=False)
        payload["doctor_name"] = doctor.name if doctor else None
        payload["facility"] = doctor.facility if doctor else None
        out.append(payload)
    return out


# ─────────────────────────────────────────────────────────────────────────────


def _own_note(db: Session, note_id: str, user: User) -> ClinicianNote:
    row = db.get(ClinicianNote, note_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    if row.doctor_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "this note belongs to another clinician"
        )
    return row


def _note_payload(row: ClinicianNote, technical: bool) -> dict:
    codes = json.loads(row.investigations)
    payload = {
        "id": row.id,
        "patient_id": row.patient_id,
        "language": row.language,
        "text": row.final_text,
        "investigations": codes,
        "investigation_labels": [
            {"code": c, "label": investigation_label(c)} for c in codes
        ],
        "follow_up_days": row.follow_up_days,
        "status": row.status,
        "released_at": row.released_at.isoformat() if row.released_at else None,
        "created_at": row.created_at.isoformat(),
    }
    if technical:
        payload |= {
            "draft_text": row.draft_text,
            "drafted_by": row.drafted_by,
            "edited": row.final_text.strip() != row.draft_text.strip(),
            "assessment_id": row.assessment_id,
        }
    return payload
