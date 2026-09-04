"""
Clinician endpoints.

The design brief for this surface is the opposite of the patient app. A
clinician has minutes, not attention. Density is a kindness here: the queue
sorts itself by concern, and the detail view leads with the one number the
clinician cannot get from the patient in front of them - how many
investigations have ever been ordered for this complaint.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import authorise_patient_access, live_consent, require_doctor
from ..schemas import EpisodeCreate, OverrideCreate
from ..disclosure import patient_projection, queue_projection
from ..service import age_from_dob, assess_and_store, handoff_card, rules
from ..tables import (
    Assessment,
    CheckBack,
    ClinicianOverride,
    Consent,
    ConsentStatus,
    Episode,
    PatientProfile,
    Symptom,
    User,
)
from ..ws import notify

router = APIRouter(prefix="/clinic", tags=["doctor"])

TIER_RANK = {"HIGH": 0, "MODERATE": 1, "LOW": 2}


@router.get("/queue")
def queue(
    request: Request,
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    """Every patient who has granted this clinician access, ordered by how
    badly their trajectory is going. Not alphabetical, not by appointment
    time - by concern. The list is the product."""
    now = datetime.now(timezone.utc)
    consents = [
        c
        for c in db.query(Consent)
        .filter(Consent.doctor_id == user.id, Consent.status == ConsentStatus.ACTIVE)
        .all()
        if c.is_live(now)
    ]

    rows = []
    for c in consents:
        prof = db.get(PatientProfile, c.patient_id)
        if prof is None:
            continue
        latest = (
            db.query(Assessment)
            .filter(Assessment.patient_id == c.patient_id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .first()
        )
        features = json.loads(latest.features_json) if latest else {}
        missed = (
            db.query(CheckBack)
            .filter(
                CheckBack.patient_id == c.patient_id,
                CheckBack.responded_at.is_(None),
                CheckBack.scheduled_for < date.today(),
            )
            .count()
        )
        rows.append(
            {
                "patient_id": c.patient_id,
                "consent_id": c.id,
                "consent_expires": c.expires_at.isoformat() if c.expires_at else None,
                # Demographics come from api/disclosure.py and nowhere else,
                # so there is exactly one place that decides what a clinician
                # can see about a patient.
                **queue_projection(prof),
                "tier": latest.tier if latest else "LOW",
                "ladder_level": latest.ladder_level if latest else 0,
                "ladder_code": latest.ladder_code if latest else "L0_OBSERVED",
                "anchor": latest.anchor_symptom if latest else None,
                "days_elapsed": features.get("days_elapsed"),
                "duration_ratio": features.get("duration_ratio"),
                "encounters": features.get("n_episodes"),
                "investigations": features.get("n_investigations"),
                "failed_treatments": features.get("n_failed_treatments"),
                "missed_checkbacks": missed,
                "last_assessed": latest.created_at.isoformat() if latest else None,
            }
        )

    rows.sort(
        key=lambda r: (
            TIER_RANK.get(r["tier"], 3),
            -(r["ladder_level"] or 0),
            -(r["duration_ratio"] or 0),
        )
    )

    audit.record(
        db,
        action="QUEUE_VIEWED",
        actor_user_id=user.id,
        actor_role="DOCTOR",
        detail={"patients": len(rows)},
        request=request,
    )
    return {
        "count": len(rows),
        "high": sum(1 for r in rows if r["tier"] == "HIGH"),
        "patients": rows,
    }


@router.get("/patients/{patient_id}")
def patient_detail(
    patient_id: str,
    access=Depends(authorise_patient_access),
    db: Session = Depends(get_db),
):
    """Full clinical view. The dependency above enforces that a live consent
    artefact exists, re-checked on this request rather than trusted from the
    session, and writes an access record either way."""
    patient, consent = access
    prof = db.get(PatientProfile, patient_id)
    rs = rules()

    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == patient_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )

    symptoms = db.query(Symptom).filter(Symptom.patient_id == patient_id).all()
    episodes = (
        db.query(Episode)
        .filter(Episode.patient_id == patient_id)
        .order_by(Episode.encounter_date)
        .all()
    )

    return {
        "patient": patient_projection(prof, consent),
        "consent": {
            "id": consent.id if consent else None,
            "scope": [s for s in consent.scope.split(",")] if consent else [],
            "expires_at": consent.expires_at.isoformat()
            if consent and consent.expires_at
            else None,
        },
        "assessment": _assessment_payload(latest) if latest else None,
        "symptoms": [
            {
                "id": s.id,
                "code": s.code,
                "label": (rs.symptoms.get(s.code, {}).get("label", {}) or {}).get("en", s.code),
                # The cluster travels with the symptom so a clinician recording
                # an encounter is offered the clusters this patient actually
                # presents with, rather than a list of all ten.
                "cluster": s.cluster_id,
                "onset_date": s.onset_date.isoformat(),
                "days": (date.today() - s.onset_date).days,
                "safe_window_days": s.safe_window_days,
                "status": s.status.value,
                "is_red_flag": s.is_red_flag,
                "expected_investigations": rs.symptoms.get(s.code, {}).get(
                    "expected_investigations", []
                ),
            }
            for s in symptoms
        ],
        "episodes": [
            {
                "id": e.id,
                "date": e.encounter_date.isoformat(),
                "cluster": e.cluster_id,
                "provider": e.provider_type,
                "intervention": e.intervention_class,
                "investigation": e.investigation_ordered,
                "outcome": e.outcome_at_followup,
                "no_investigation": e.investigation_ordered == "none",
            }
            for e in episodes
        ],
    }


def _assessment_payload(a: Assessment) -> dict:
    return {
        "id": a.id,
        "as_of": a.as_of.isoformat(),
        "tier": a.tier,
        "ladder_level": a.ladder_level,
        "ladder_code": a.ladder_code,
        "anchor_symptom": a.anchor_symptom,
        "features": json.loads(a.features_json),
        "reasons": json.loads(a.reasons_json),
        "suggested_investigations": json.loads(a.investigations_json),
        "model": {
            "version": a.model_version,
            "probability": a.model_probability,
            # The EBM breakdown, stored at decision time. Not recomputed, not
            # approximated after the fact - this IS how the number was made.
            "contributions": json.loads(a.contributions_json),
        },
        "ruleset_version": a.ruleset_version,
    }


@router.get("/patients/{patient_id}/handoff-card")
def card(
    patient_id: str,
    access=Depends(authorise_patient_access),
    db: Session = Depends(get_db),
):
    try:
        return handoff_card(db, patient_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/patients/{patient_id}/episodes", status_code=201)
def record_episode(
    patient_id: str,
    body: EpisodeCreate,
    request: Request,
    access=Depends(authorise_patient_access),
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    """A clinician recording what they actually did.

    The `investigation_ordered` field on this call is the one that breaks the
    loop. When it is anything other than 'none', the L1 condition stops being
    true and AIRA stops nagging - which is exactly the behaviour a clinician
    who did the right thing deserves.
    """
    _, consent = access
    row = Episode(
        patient_id=patient_id,
        cluster_id=body.cluster_id,
        encounter_date=body.encounter_date,
        provider_type=body.provider_type,
        intervention_class=body.intervention_class,
        investigation_ordered=body.investigation_ordered,
        outcome_at_followup=body.outcome_at_followup,
        recorded_by=user.id,
        source="clinician",
    )
    db.add(row)
    db.commit()

    a = assess_and_store(db, patient_id)
    audit.record(
        db,
        action="EPISODE_RECORDED",
        actor_user_id=user.id,
        actor_role="DOCTOR",
        target_type="patient",
        target_id=patient_id,
        consent_id=consent.id if consent else None,
        detail={"investigation": body.investigation_ordered},
        request=request,
    )
    notify(
        patient_id,
        "record.updated",
        {"reason": "clinician_episode", "tier": a.tier, "ladder_level": a.ladder_level},
    )
    return {"episode_id": row.id, "tier": a.tier, "ladder_level": a.ladder_level}


@router.post("/patients/{patient_id}/override", status_code=201)
def override(
    patient_id: str,
    body: OverrideCreate,
    request: Request,
    access=Depends(authorise_patient_access),
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    """A clinician disagreeing with AIRA.

    This is not an error path. A clinician's disagreement is the most valuable
    training signal this system will ever receive, and it is stored with a
    mandatory rationale rather than swallowed. Nothing is retrained from these
    automatically - they queue for review, because a model that quietly learns
    to agree with whoever overrides it most is a model that has learned
    nothing about cancer.
    """
    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == patient_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no assessment to override")

    row = ClinicianOverride(
        assessment_id=latest.id,
        doctor_id=user.id,
        original_tier=latest.tier,
        new_tier=body.new_tier,
        rationale=body.rationale,
    )
    db.add(row)
    db.commit()

    audit.record(
        db,
        action="CLINICIAN_OVERRIDE",
        actor_user_id=user.id,
        actor_role="DOCTOR",
        target_type="assessment",
        target_id=latest.id,
        detail={"from": latest.tier, "to": body.new_tier},
        request=request,
    )
    return {"override_id": row.id, "from": latest.tier, "to": body.new_tier}


@router.get("/patients/{patient_id}/explain")
def explain(
    patient_id: str,
    access=Depends(authorise_patient_access),
    db: Session = Depends(get_db),
):
    """Why did AIRA say what it said.

    Three layers, all of them printable: which rules fired and from which
    guideline, what the trajectory numbers are, and - when a model
    contributed - the exact per-feature arithmetic that produced the score.
    """
    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == patient_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no assessment yet")

    reasons = json.loads(latest.reasons_json)
    contributions = json.loads(latest.contributions_json)

    return {
        "verdict": {
            "tier": latest.tier,
            "ladder_level": latest.ladder_level,
            "ladder_code": latest.ladder_code,
        },
        "decided_by": "rules" if not contributions else "rules + model",
        "boundary": (
            "Rules set the tier. The model may raise it and can never lower it. "
            "No generated text can change it."
        ),
        "rules_that_fired": [
            {
                "rule_id": r["rule_id"],
                "kind": r["kind"],
                "statement": r["clinician"],
                "source": (r.get("citation") or {}).get("source"),
                "section": (r.get("citation") or {}).get("section"),
                "quote": (r.get("citation") or {}).get("quote"),
            }
            for r in reasons
        ],
        "trajectory": json.loads(latest.features_json),
        "model_contributions": contributions,
        "model_probability": latest.model_probability,
        "ruleset_version": latest.ruleset_version,
        "model_version": latest.model_version,
    }
