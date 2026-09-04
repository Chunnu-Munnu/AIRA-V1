"""
Care-plan persistence: the glue between engine/next_action.py (pure state
machine) and the database.

`sync_care_plan` is called after anything that can change a patient's care
state - a new assessment, a released note, an uploaded or reviewed report, a
recorded treatment response. It:

  1. reads the facts from the database
  2. asks engine.next_action.derive() for the current state and task list
  3. upserts CareTask rows by (patient_id, key), never losing a status
  4. auto-completes the handful of tasks a hard fact makes true
  5. marks anything past its due date overdue

The API layer then renders the plan in the patient's language.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from engine import next_action as na

from .tables import (
    Assessment,
    CareResponse,
    CareTask,
    ClinicianNote,
    Consent,
    ConsentStatus,
    Episode,
    MedicalDocument,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _facts(db: Session, patient_id: str) -> dict:
    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == patient_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )
    assessment = (
        {
            "tier": latest.tier,
            "ladder_level": latest.ladder_level,
            "ladder_code": latest.ladder_code,
            "anchor": latest.anchor_symptom,
        }
        if latest
        else None
    )

    episodes = [
        {
            "date": e.encounter_date,
            "provider_type": e.provider_type,
            "intervention_class": e.intervention_class,
            "investigation_ordered": e.investigation_ordered,
            "outcome": e.outcome_at_followup,
            "source": e.source,
            "recorded_by": e.recorded_by,
        }
        for e in db.query(Episode).filter(Episode.patient_id == patient_id).all()
    ]

    notes = (
        db.query(ClinicianNote)
        .filter(
            ClinicianNote.patient_id == patient_id,
            ClinicianNote.status == "released",
        )
        .order_by(ClinicianNote.released_at.desc())
        .all()
    )
    released_notes = [
        {
            "id": n.id,
            "released_on": n.released_at.date() if n.released_at else None,
            "follow_up_days": n.follow_up_days,
        }
        for n in notes
    ]

    documents = [
        {"id": d.id, "created_on": d.created_at.date(), "reviewed_at": d.reviewed_at}
        for d in db.query(MedicalDocument)
        .filter(MedicalDocument.patient_id == patient_id)
        .all()
    ]

    responses = (
        db.query(CareResponse)
        .filter(CareResponse.patient_id == patient_id)
        .order_by(CareResponse.created_at.desc())
        .all()
    )
    care_responses = [
        {
            "feeling": r.feeling,
            "helped": r.helped,
            "created_on": r.created_at.date(),
        }
        for r in responses
    ]

    now = _now()
    consent_active = any(
        c.is_live(now)
        for c in db.query(Consent)
        .filter(Consent.patient_id == patient_id, Consent.status == ConsentStatus.ACTIVE)
        .all()
    )

    return {
        "assessment": assessment,
        "episodes": episodes,
        "released_notes": released_notes,
        "documents": documents,
        "care_responses": care_responses,
        "consent_active": consent_active,
        "_fact_flags": {
            "consent_active": consent_active,
            "note_released": bool(released_notes),
            "document_uploaded": bool(documents),
            "document_reviewed": bool(documents) and all(d["reviewed_at"] for d in documents),
            "investigation_recorded": any(
                (e["investigation_ordered"] or "none") != "none" for e in episodes
            )
            or any(d["reviewed_at"] for d in documents),
            "care_response": bool(care_responses),
        },
    }


def sync_care_plan(db: Session, patient_id: str) -> na.CarePlan:
    facts = _facts(db, patient_id)
    plan = na.derive(
        assessment=facts["assessment"],
        episodes=facts["episodes"],
        released_notes=facts["released_notes"],
        documents=facts["documents"],
        care_responses=facts["care_responses"],
        consent_active=facts["consent_active"],
    )

    existing = {
        t.key: t
        for t in db.query(CareTask).filter(CareTask.patient_id == patient_id).all()
    }
    flags = facts["_fact_flags"]
    today = date.today()

    for order, spec in enumerate(plan.tasks):
        row = existing.get(spec.key)
        if row is None:
            row = CareTask(
                patient_id=patient_id,
                key=spec.key,
                state=plan.state,
                label_en=spec.labels["en"],
                label_hi=spec.labels.get("hi", ""),
                label_kn=spec.labels.get("kn", ""),
                source=spec.source,
            )
            db.add(row)
            existing[spec.key] = row

        row.state = plan.state
        row.sort_order = order
        row.note_id = spec.note_id
        row.due_date = spec.due_date
        row.auto_complete_on = spec.auto_complete_on
        # keep labels fresh if the copy changed
        row.label_en, row.label_hi, row.label_kn = (
            spec.labels["en"],
            spec.labels.get("hi", ""),
            spec.labels.get("kn", ""),
        )

        if row.status != "completed":
            if spec.auto_complete_on and flags.get(spec.auto_complete_on):
                row.status = "completed"
                row.completed_at = _now()
            elif spec.due_date and spec.due_date < today:
                row.status = "overdue"
            elif row.status == "overdue" and not (spec.due_date and spec.due_date < today):
                row.status = "pending"

    db.commit()
    return plan


CTA_LABELS = {
    "find_care": na._t("Find clinical care", "इलाज कहाँ मिलेगा", "ಆರೈಕೆ ಎಲ್ಲಿ ಸಿಗುತ್ತದೆ"),
    "record_response": na._t("How are you feeling?", "आप कैसा महसूस कर रहे हैं?", "ನೀವು ಹೇಗಿದ್ದೀರಿ?"),
    "upload_report": na._t("Upload a report", "रिपोर्ट अपलोड करें", "ವರದಿ ಅಪ್‌ಲೋಡ್ ಮಾಡಿ"),
    "why_flagged": na._t("Why was I flagged?", "मुझे क्यों चिह्नित किया गया?", "ನನ್ನನ್ನು ಏಕೆ ಗುರುತಿಸಲಾಯಿತು?"),
    "view_plan": na._t("See the full plan", "पूरा प्लान देखें", "ಪೂರ್ಣ ಯೋಜನೆ ನೋಡಿ"),
}


def care_plan_payload(db: Session, patient_id: str, lang: str = "en") -> dict:
    """Render the current plan for the patient, in their language."""
    plan = sync_care_plan(db, patient_id)

    order = {spec.key: i for i, spec in enumerate(plan.tasks)}
    rows = sorted(
        db.query(CareTask)
        .filter(CareTask.patient_id == patient_id, CareTask.key.in_(order.keys()))
        .all(),
        key=lambda r: order.get(r.key, 99),
    )

    def label(row: CareTask) -> str:
        return {"hi": row.label_hi, "kn": row.label_kn}.get(lang) or row.label_en

    tasks = [
        {
            "id": r.id,
            "key": r.key,
            "label": label(r),
            "status": r.status,
            "source": r.source,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "note_id": r.note_id,
            "patient_actionable": r.auto_complete_on is None,
        }
        for r in rows
    ]
    done = sum(1 for t in tasks if t["status"] == "completed")

    def pick(d: dict | None) -> str | None:
        if not d:
            return None
        return d.get(lang) or d["en"]

    return {
        "state": plan.state,
        "headline": pick(plan.headline),
        "subhead": pick(plan.subhead),
        "escalated": plan.escalated,
        "tasks": tasks,
        "progress": {"done": done, "total": len(tasks)},
        "primary_cta": (
            {"key": plan.primary_cta, "label": pick(CTA_LABELS.get(plan.primary_cta))}
            if plan.primary_cta
            else None
        ),
        "secondary_cta": (
            {"key": plan.secondary_cta, "label": pick(CTA_LABELS.get(plan.secondary_cta))}
            if plan.secondary_cta
            else None
        ),
        "disclaimer": {
            "en": "Decision-support guidance, not a diagnosis. Your treating doctor makes the final call.",
            "hi": "यह निर्णय में मदद के लिए है, कोई निदान नहीं। अंतिम फ़ैसला आपके डॉक्टर का है।",
            "kn": "ಇದು ನಿರ್ಧಾರ ಸಹಾಯಕ್ಕಾಗಿ, ರೋಗನಿರ್ಣಯವಲ್ಲ. ಅಂತಿಮ ತೀರ್ಮಾನ ನಿಮ್ಮ ವೈದ್ಯರದ್ದು.",
        }.get(lang, "Decision-support guidance, not a diagnosis."),
    }
