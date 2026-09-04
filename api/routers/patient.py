"""Patient-facing endpoints. Everything here is scoped to the caller's own
record - there is no patient_id parameter anywhere in this router by design."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import require_patient
from ..care import care_plan_payload
from ..schemas import (
    CheckBackAnswer,
    EpisodeCreate,
    LanguageChange,
    SymptomCreate,
    TreatmentResponse,
)
from ..service import (
    age_from_dob,
    assess_and_store,
    handoff_card,
    rules,
    schedule_checkbacks,
)
from ..tables import (
    Assessment,
    CareResponse,
    CareTask,
    CheckBack,
    ClinicianNote,
    Consent,
    ConsentStatus,
    Episode,
    PatientProfile,
    SeverityReading,
    Symptom,
    SymptomStatus,
    User,
)
from ..ws import notify

router = APIRouter(prefix="/me", tags=["patient"])


def _profile(db: Session, user: User) -> PatientProfile:
    prof = db.get(PatientProfile, user.id)
    if prof is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "patient profile missing")
    return prof


def _notify_linked_doctors(db: Session, patient_id: str, event: str, payload: dict) -> None:
    """Push to every clinician who currently holds a live artefact. Revoked
    and expired consents are simply not in this list, which is why revocation
    needs no extra plumbing."""
    now = datetime.now(timezone.utc)
    for c in (
        db.query(Consent)
        .filter(Consent.patient_id == patient_id, Consent.status == ConsentStatus.ACTIVE)
        .all()
    ):
        if c.is_live(now):
            notify(c.doctor_id, event, payload)


@router.get("/dashboard")
def dashboard(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    """Everything the patient home screen needs, in one call.

    Deliberately one round trip: this screen is opened on a cheap phone on a
    slow connection, and four sequential requests is four chances to fail.
    """
    prof = _profile(db, user)
    rs = rules()
    today = date.today()

    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == user.id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )

    symptoms = (
        db.query(Symptom)
        .filter(Symptom.patient_id == user.id, Symptom.status != SymptomStatus.resolved)
        .order_by(Symptom.onset_date)
        .all()
    )

    tracked = []
    for s in symptoms:
        spec = rs.symptoms.get(s.code, {})
        elapsed = (today - s.onset_date).days
        window = s.safe_window_days or 1
        tracked.append(
            {
                "id": s.id,
                "code": s.code,
                "label": (spec.get("label", {}) or {}).get(prof.language)
                or (spec.get("label", {}) or {}).get("en", s.code),
                "onset_date": s.onset_date.isoformat(),
                "days": elapsed,
                "safe_window_days": s.safe_window_days,
                # Rendered as a progress ring on the home screen. It is a
                # clock, not a risk score, and it is never coloured red.
                "progress": min(1.0, round(elapsed / window, 2)) if window else 1.0,
                "is_red_flag": s.is_red_flag,
            }
        )

    due = (
        db.query(CheckBack)
        .filter(
            CheckBack.patient_id == user.id,
            CheckBack.responded_at.is_(None),
            CheckBack.scheduled_for <= today,
        )
        .order_by(CheckBack.scheduled_for)
        .all()
    )

    screening = []
    if latest is not None:
        from ..service import build_state
        from engine.rules_engine import evaluate_screening

        screening = evaluate_screening(build_state(db, user.id, today), rs, today)

    active_consents = [
        c
        for c in db.query(Consent)
        .filter(Consent.patient_id == user.id, Consent.status == ConsentStatus.ACTIVE)
        .all()
        if c.is_live()
    ]

    return {
        "patient": {
            "name": prof.name,
            "age": age_from_dob(prof.dob, today),
            "aira_code": prof.aira_code,
            "language": prof.language,
            "village": prof.village,
        },
        "status": {
            "tier": latest.tier if latest else "LOW",
            "ladder_level": latest.ladder_level if latest else 0,
            "ladder_code": latest.ladder_code if latest else "L0_OBSERVED",
            "message": _headline(latest, prof.language),
            "as_of": latest.as_of.isoformat() if latest else today.isoformat(),
        },
        "tracked_symptoms": tracked,
        "checkbacks_due": [
            {
                "id": c.id,
                "symptom_id": c.symptom_id,
                "scheduled_for": c.scheduled_for.isoformat(),
                "days_since_scheduled": (today - c.scheduled_for).days,
            }
            for c in due
        ],
        "screening": [s for s in screening if s["status"] == "available"],
        "doctors_with_access": len(active_consents),
        "pending_consent_requests": db.query(Consent)
        .filter(Consent.patient_id == user.id, Consent.status == ConsentStatus.PENDING)
        .count(),
    }


def _headline(latest: Assessment | None, lang: str) -> str:
    if latest is None:
        return {
            "en": "Nothing is being tracked yet. Add a symptom when something bothers you.",
            "hi": "अभी कुछ भी ट्रैक नहीं हो रहा। कोई परेशानी हो तो लक्षण जोड़ें।",
            "kn": "ಇನ್ನೂ ಏನನ್ನೂ ಗಮನಿಸುತ್ತಿಲ್ಲ. ತೊಂದರೆ ಇದ್ದರೆ ಲಕ್ಷಣ ಸೇರಿಸಿ.",
        }.get(lang, "Nothing is being tracked yet.")

    reasons = json.loads(latest.reasons_json)
    for r in reasons:
        if r.get("patient"):
            return r["patient"]
    return {
        "en": "We are keeping track. We will check with you again soon.",
        "hi": "हम नजर रख रहे हैं। जल्दी फिर पूछेंगे।",
        "kn": "ನಾವು ಗಮನಿಸುತ್ತಿದ್ದೇವೆ. ಶೀಘ್ರದಲ್ಲೇ ಮತ್ತೆ ಕೇಳುತ್ತೇವೆ.",
    }.get(lang, "We are keeping track.")


SUPPORTED_LANGUAGES = {"en": "English", "hi": "हिन्दी", "kn": "ಕನ್ನಡ"}


@router.post("/language")
def set_language(
    body: LanguageChange,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """Change the language of everything: the symptom list, the headline, the
    chatbot, the voice prompts, and the note a clinician drafts for you.

    Language is stored on the profile rather than in the browser because it
    has to reach the clinician - when Dr Rao presses "draft a note", AIRA has
    to know to write it in Kannada, and the doctor's browser cannot tell her
    that. A phone that is handed between family members changes language
    here and the whole record follows.
    """
    if body.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported language")

    prof = _profile(db, user)
    previous, prof.language = prof.language, body.language
    db.commit()

    # The headline on the home screen is stored, not computed on read: what we
    # told a patient on a given day is a record, and a model retrained tomorrow
    # must not silently rewrite it. So changing language means re-running the
    # engine - the same rules, the same tier, re-phrased. If it produced a
    # different TIER, that would be a bug in the ruleset and worth knowing.
    assess_and_store(db, user.id)

    audit.record(
        db,
        action="patient.language.changed",
        actor_user_id=user.id,
        actor_role="patient",
        target_type="patient_profile",
        target_id=user.id,
        detail={"from": previous, "to": body.language},
        request=request,
    )
    return {"language": prof.language, "label": SUPPORTED_LANGUAGES[prof.language]}


@router.get("/symptom-catalogue")
def catalogue(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    """The pick-list, in the patient's language, phrased the way a person
    would say it rather than the way a textbook would."""
    prof = _profile(db, user)
    rs = rules()
    lang = prof.language
    out = []
    for code, spec in rs.symptoms.items():
        if not _eligible(spec, prof, user, db):
            continue
        out.append(
            {
                "code": code,
                "cluster": spec["cluster"],
                "label": spec["label"].get(lang) or spec["label"]["en"],
                "phrasing": (spec.get("patient_phrasing") or {}).get(lang)
                or (spec.get("patient_phrasing") or {}).get("en", ""),
            }
        )
    return sorted(out, key=lambda s: (s["cluster"], s["label"]))


def _eligible(spec: dict, prof: PatientProfile, user: User, db: Session) -> bool:
    applies = spec.get("applies", {})
    age = age_from_dob(prof.dob)
    if applies.get("min_age") is not None and age < applies["min_age"]:
        return False
    if applies.get("max_age") is not None and age > applies["max_age"]:
        return False
    sex = applies.get("sex")
    if sex not in (None, "any") and prof.sex != sex:
        return False
    return True


@router.post("/symptoms", status_code=201)
def add_symptom(
    body: SymptomCreate,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    rs = rules()
    if body.code not in rs.symptoms:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown symptom code {body.code}")

    spec = rs.symptom(body.code)
    is_flag = any(f["symptom"] == body.code for f in rs.red_flags)

    row = Symptom(
        patient_id=user.id,
        code=body.code,
        cluster_id=spec["cluster"],
        onset_date=body.onset_date,
        # Snapshotted, not looked up later. If a clinician changes the safe
        # window next month, this symptom's history stays interpretable.
        safe_window_days=rs.safe_window(body.code),
        ruleset_version=rs.version,
        is_red_flag=is_flag,
        source=body.source,
    )
    db.add(row)
    db.flush()

    if body.severity is not None:
        db.add(
            SeverityReading(
                symptom_id=row.id, reading_date=body.onset_date, score=body.severity
            )
        )
    db.commit()

    assessment = assess_and_store(db, user.id)
    schedule_checkbacks(db, user.id)

    audit.record(
        db,
        action="SYMPTOM_ADDED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="symptom",
        target_id=row.id,
        detail={"code": body.code, "source": body.source},
        request=request,
    )

    _notify_linked_doctors(
        db,
        user.id,
        "patient.updated",
        {
            "patient_id": user.id,
            "reason": "symptom_added",
            "tier": assessment.tier,
            "ladder_level": assessment.ladder_level,
        },
    )

    return {
        "symptom_id": row.id,
        "assessment_id": assessment.id,
        "tier": assessment.tier,
        "ladder_level": assessment.ladder_level,
        "message": _headline(assessment, _profile(db, user).language),
    }


@router.post("/episodes", status_code=201)
def add_episode(
    body: EpisodeCreate,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """'I went to a doctor and this is what happened.'

    This is the single most valuable thing a patient can record, and the one
    every other symptom checker throws away. Without it there is no loop.
    """
    row = Episode(
        patient_id=user.id,
        cluster_id=body.cluster_id,
        encounter_date=body.encounter_date,
        provider_type=body.provider_type,
        intervention_class=body.intervention_class,
        investigation_ordered=body.investigation_ordered,
        outcome_at_followup=body.outcome_at_followup,
        recorded_by=user.id,
        source="patient",
    )
    db.add(row)
    db.commit()

    assessment = assess_and_store(db, user.id)
    audit.record(
        db,
        action="EPISODE_ADDED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="episode",
        target_id=row.id,
        request=request,
    )
    _notify_linked_doctors(
        db,
        user.id,
        "patient.updated",
        {
            "patient_id": user.id,
            "reason": "episode_added",
            "tier": assessment.tier,
            "ladder_level": assessment.ladder_level,
        },
    )
    return {"episode_id": row.id, "tier": assessment.tier, "ladder_level": assessment.ladder_level}


# ─────────────────────────────────────────────────────────────────────────────
# The check-back loop
# ─────────────────────────────────────────────────────────────────────────────

CHECKBACK_QUESTION = {
    "en": "{days} days ago you told us about {symptom}. How is it now?",
    "hi": "{days} दिन पहले आपने {symptom} के बारे में बताया था। अब कैसा है?",
    "kn": "{days} ದಿನಗಳ ಹಿಂದೆ ನೀವು {symptom} ಬಗ್ಗೆ ಹೇಳಿದ್ದೀರಿ. ಈಗ ಹೇಗಿದೆ?",
}

CHECKBACK_OPTIONS = {
    "en": {
        "same": "Still the same",
        "better": "Better",
        "gone": "Gone",
        "worse": "Worse",
        "new_problem": "Something new started",
    },
    "hi": {
        "same": "वैसा ही है",
        "better": "बेहतर है",
        "gone": "ठीक हो गया",
        "worse": "और खराब है",
        "new_problem": "कुछ नया शुरू हुआ",
    },
    "kn": {
        "same": "ಹಾಗೇ ಇದೆ",
        "better": "ಸುಧಾರಿಸಿದೆ",
        "gone": "ಗುಣವಾಗಿದೆ",
        "worse": "ಹೆಚ್ಚಾಗಿದೆ",
        "new_problem": "ಹೊಸದೇನೋ ಶುರುವಾಗಿದೆ",
    },
}


@router.get("/checkbacks/{checkback_id}")
def get_checkback(
    checkback_id: str,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    cb = db.get(CheckBack, checkback_id)
    if cb is None or cb.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "check-back not found")

    sym = db.get(Symptom, cb.symptom_id)
    prof = _profile(db, user)
    rs = rules()
    spec = rs.symptoms.get(sym.code, {})
    label = (spec.get("label", {}) or {}).get(prof.language) or sym.code
    days = (date.today() - sym.onset_date).days
    lang = prof.language

    cb.sent_at = cb.sent_at or datetime.now(timezone.utc)
    db.commit()

    return {
        "id": cb.id,
        "symptom_id": sym.id,
        "question": CHECKBACK_QUESTION.get(lang, CHECKBACK_QUESTION["en"]).format(
            days=days, symptom=label
        ),
        # Ticks, not typing. The people this is built for should be able to
        # answer with one tap while holding a child.
        "options": CHECKBACK_OPTIONS.get(lang, CHECKBACK_OPTIONS["en"]),
        "tts_cache_key": f"checkback_{lang}",
    }


@router.post("/checkbacks/{checkback_id}/answer")
def answer_checkback(
    checkback_id: str,
    body: CheckBackAnswer,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    cb = db.get(CheckBack, checkback_id)
    if cb is None or cb.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "check-back not found")
    if cb.responded_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already answered")

    cb.responded_at = datetime.now(timezone.utc)
    cb.response = body.response
    cb.severity = body.severity
    cb.note = body.note

    sym = db.get(Symptom, cb.symptom_id)

    if body.severity is not None:
        db.add(
            SeverityReading(symptom_id=sym.id, reading_date=date.today(), score=body.severity)
        )

    if body.response == "gone":
        sym.status = SymptomStatus.resolved

    if body.response == "new_problem" and body.new_symptom_code:
        rs = rules()
        if body.new_symptom_code in rs.symptoms:
            spec = rs.symptom(body.new_symptom_code)
            db.add(
                Symptom(
                    patient_id=user.id,
                    code=body.new_symptom_code,
                    cluster_id=spec["cluster"],
                    onset_date=date.today(),
                    safe_window_days=rs.safe_window(body.new_symptom_code),
                    ruleset_version=rs.version,
                    is_red_flag=any(
                        f["symptom"] == body.new_symptom_code for f in rs.red_flags
                    ),
                    source="text",
                )
            )
    db.commit()

    assessment = assess_and_store(db, user.id)
    schedule_checkbacks(db, user.id)

    audit.record(
        db,
        action="CHECKBACK_ANSWERED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="checkback",
        target_id=cb.id,
        detail={"response": body.response},
        request=request,
    )
    _notify_linked_doctors(
        db,
        user.id,
        "patient.updated",
        {
            "patient_id": user.id,
            "reason": "checkback_answered",
            "tier": assessment.tier,
            "ladder_level": assessment.ladder_level,
        },
    )
    return {
        "tier": assessment.tier,
        "ladder_level": assessment.ladder_level,
        "message": _headline(assessment, _profile(db, user).language),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Timeline and Handoff Card
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/timeline")
def timeline(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    """One chronological stream: symptoms starting, visits happening,
    check-backs answered. This view is what three separate NGOs independently
    asked us for, in the same words: 'a patient timeline'."""
    rs = rules()
    prof = _profile(db, user)
    lang = prof.language
    events: list[dict] = []

    # Coded fields go to the client and are localised there with the same
    # vocabulary the "record a visit" form uses - one word list, not two.
    for s in db.query(Symptom).filter(Symptom.patient_id == user.id).all():
        spec = rs.symptoms.get(s.code, {})
        events.append(
            {
                "date": s.onset_date.isoformat(),
                "kind": "symptom_started",
                "symptom_label": (spec.get("label", {}) or {}).get(lang) or s.code,
                "safe_window_days": s.safe_window_days,
                "red_flag": s.is_red_flag,
            }
        )

    for e in db.query(Episode).filter(Episode.patient_id == user.id).all():
        events.append(
            {
                "date": e.encounter_date.isoformat(),
                "kind": "visit",
                "provider": e.provider_type,
                "given": e.intervention_class,
                "investigation": e.investigation_ordered,
                "outcome": e.outcome_at_followup or "unknown",
                # The flag that makes the timeline damning rather than decorative.
                "no_investigation": e.investigation_ordered == "none",
            }
        )

    for c in (
        db.query(CheckBack)
        .filter(CheckBack.patient_id == user.id, CheckBack.responded_at.isnot(None))
        .all()
    ):
        events.append(
            {
                "date": c.responded_at.date().isoformat(),
                "kind": "checkback",
                "response": c.response or "",
            }
        )

    events.sort(key=lambda e: e["date"])
    return {"events": events}


@router.get("/handoff-card")
def my_handoff_card(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    try:
        return handoff_card(db, user.id, _profile(db, user).language)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/reassess")
def reassess(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    a = assess_and_store(db, user.id)
    schedule_checkbacks(db, user.id)
    return {
        "assessment_id": a.id,
        "tier": a.tier,
        "ladder_level": a.ladder_level,
        "ruleset_version": a.ruleset_version,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Next Action - the checklist that never lets a risk score be the last word
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/next-action")
def next_action(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    prof = _profile(db, user)
    return care_plan_payload(db, user.id, prof.language)


@router.post("/care-tasks/{task_id}/advance")
def advance_care_task(
    task_id: str,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """The patient moves a task forward: pending -> in progress -> done, and
    back to pending from done if they tapped it by mistake. AIRA never makes
    this move on the patient's behalf - a checklist that ticks itself is one
    nobody believes."""
    row = db.get(CareTask, task_id)
    if row is None or row.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if row.auto_complete_on is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this step completes on its own when the matching record arrives",
        )

    nxt = {"pending": "in_progress", "in_progress": "completed", "overdue": "completed",
           "completed": "pending"}
    row.status = nxt.get(row.status, "in_progress")
    row.completed_at = datetime.now(timezone.utc) if row.status == "completed" else None
    db.commit()

    audit.record(
        db,
        action="CARE_TASK_ADVANCED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="care_task",
        target_id=row.id,
        detail={"key": row.key, "status": row.status},
        request=request,
    )
    if row.status == "completed":
        _notify_linked_doctors(
            db, user.id, "care.task_completed",
            {"patient_id": user.id, "task": row.key},
        )
    return care_plan_payload(db, user.id, _profile(db, user).language)


@router.post("/treatment-response")
def treatment_response(
    body: TreatmentResponse,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """The treatment-response loop. After a doctor's plan has had time to
    work, the patient says how they feel and whether it helped. A run of
    'same / no' across successive plans is the treatment-refractory pattern
    the Loop Detector is built to catch - so this also writes an Episode
    outcome and re-runs the assessment.
    """
    latest_note = (
        db.query(ClinicianNote)
        .filter(ClinicianNote.patient_id == user.id, ClinicianNote.status == "released")
        .order_by(ClinicianNote.released_at.desc())
        .first()
    )

    row = CareResponse(
        patient_id=user.id,
        note_id=latest_note.id if latest_note else None,
        feeling=body.feeling,
        helped=body.helped,
        note=body.note,
    )
    db.add(row)

    # Record the outcome against the most recent treatment episode so the
    # trajectory model sees it. "no / same" -> unchanged; "worse" -> worse.
    outcome = {"worse": "worse", "no": "unchanged", "partially": "partial",
               "yes": "resolved"}.get(body.helped)
    if body.feeling == "worse":
        outcome = "worse"
    last_tx = (
        db.query(Episode)
        .filter(Episode.patient_id == user.id, Episode.intervention_class != "none")
        .order_by(Episode.encounter_date.desc(), Episode.created_at.desc())
        .first()
    )
    if last_tx is not None and outcome and last_tx.outcome_at_followup in (None, "unknown"):
        last_tx.outcome_at_followup = outcome
    db.commit()

    assessment = assess_and_store(db, user.id)
    schedule_checkbacks(db, user.id)

    audit.record(
        db,
        action="TREATMENT_RESPONSE_RECORDED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="care_response",
        target_id=row.id,
        detail={"feeling": body.feeling, "helped": body.helped},
        request=request,
    )
    _notify_linked_doctors(
        db,
        user.id,
        "treatment.response",
        {
            "patient_id": user.id,
            "feeling": body.feeling,
            "helped": body.helped,
            "tier": assessment.tier,
            "ladder_level": assessment.ladder_level,
        },
    )
    payload = care_plan_payload(db, user.id, _profile(db, user).language)
    payload["tier"] = assessment.tier
    return payload
