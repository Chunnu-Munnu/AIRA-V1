"""
The consent flow - AIRA's implementation of the ABDM consent model.

Read this alongside TECHNICAL.md. Every field on the Consent row maps to a
field in the ABDM consent request schema, and the sequence below is the ABDM
sequence with our own identity provider standing in for ABHA:

    patient generates a PIN         (challenge, 10 minutes, 3 attempts)
    doctor submits code + PIN       -> a REQUEST is created. Doctor sees nothing.
    patient's device is notified    (WebSocket, real time)
    patient hears the notice aloud  (Sarvam, in their own language)
    patient allows or denies        -> artefact issued, or not
    patient may revoke at any time  -> access dies on the doctor's next request

The single most important property: submitting a valid code and PIN grants
ZERO access. It only creates a request. Authentication is not authorisation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import current_user, live_consent, require_doctor, require_patient
from ..schemas import ConsentDecision, ConsentOut, ConsentRequestBody, LinkPinResponse
from ..security import hash_token, new_link_pin
from ..tables import (
    Consent,
    ConsentStatus,
    DoctorProfile,
    LinkPin,
    PatientProfile,
    Role,
    User,
)
from ..ws import notify

router = APIRouter(prefix="/consent", tags=["consent"])
settings = get_settings()


def _to_out(db: Session, c: Consent) -> ConsentOut:
    doc = db.get(DoctorProfile, c.doctor_id)
    pat = db.get(PatientProfile, c.patient_id)
    return ConsentOut(
        id=c.id,
        status=c.status.value,
        purpose=c.purpose,
        scope=[s for s in c.scope.split(",") if s],
        doctor_name=doc.name if doc else None,
        doctor_facility=doc.facility if doc else None,
        patient_name=pat.name if pat else None,
        aira_code=pat.aira_code if pat else None,
        requested_at=c.requested_at,
        granted_at=c.granted_at,
        expires_at=c.expires_at,
        revoked_at=c.revoked_at,
        read_aloud_at=c.read_aloud_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Patient: generate the challenge
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/pin", response_model=LinkPinResponse)
def generate_pin(
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    profile = db.get(PatientProfile, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "patient profile missing")

    now = datetime.now(timezone.utc)

    # Any previously issued, unused PIN is burned. Only one live challenge per
    # patient at a time, so an old screenshot is worthless.
    for old in (
        db.query(LinkPin)
        .filter(LinkPin.patient_id == user.id, LinkPin.used_at.is_(None))
        .all()
    ):
        old.used_at = now

    raw = new_link_pin()
    expires = now + timedelta(minutes=settings.link_pin_ttl_minutes)
    db.add(LinkPin(patient_id=user.id, pin_hash=hash_token(raw), expires_at=expires))
    db.commit()

    audit.record(
        db,
        action="LINK_PIN_ISSUED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="patient",
        target_id=user.id,
        request=request,
    )
    return LinkPinResponse(
        aira_code=profile.aira_code,
        pin=raw,
        expires_at=expires,
        valid_for_minutes=settings.link_pin_ttl_minutes,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Doctor: ask
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/request", response_model=ConsentOut, status_code=201)
def request_access(
    body: ConsentRequestBody,
    request: Request,
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(PatientProfile)
        .filter(PatientProfile.aira_code == body.aira_code.strip().upper())
        .first()
    )
    now = datetime.now(timezone.utc)

    def deny(detail: str):
        audit.record(
            db,
            action="CONSENT_REQUEST",
            actor_user_id=user.id,
            actor_role="DOCTOR",
            outcome="denied",
            detail=detail,
            request=request,
        )
        # Deliberately identical for "no such code" and "wrong PIN", so this
        # endpoint cannot be used to discover which AIRA codes are real.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid code or PIN")

    if profile is None:
        deny(f"unknown aira_code {body.aira_code}")

    pin_row = (
        db.query(LinkPin)
        .filter(LinkPin.patient_id == profile.user_id, LinkPin.used_at.is_(None))
        .order_by(LinkPin.created_at.desc())
        .first()
    )
    if pin_row is None:
        deny("no active PIN for this patient")

    expires = (
        pin_row.expires_at
        if pin_row.expires_at.tzinfo
        else pin_row.expires_at.replace(tzinfo=timezone.utc)
    )
    if expires <= now:
        pin_row.used_at = now
        db.commit()
        deny("PIN expired")

    if pin_row.attempts >= settings.link_pin_max_attempts:
        pin_row.used_at = now
        db.commit()
        deny("PIN attempt limit reached")

    if pin_row.pin_hash != hash_token(body.pin):
        pin_row.attempts += 1
        db.commit()
        deny("wrong PIN")

    # Correct code and PIN. This creates a REQUEST. The doctor still sees
    # nothing at all until the patient approves.
    pin_row.used_at = now

    existing = live_consent(db, doctor_id=user.id, patient_id=profile.user_id)
    if existing is not None:
        db.commit()
        return _to_out(db, existing)

    consent = Consent(
        patient_id=profile.user_id,
        doctor_id=user.id,
        status=ConsentStatus.PENDING,
        scope=",".join(body.scope),
        purpose=body.purpose,
        expires_at=now + timedelta(days=body.days),
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)

    audit.record(
        db,
        action="CONSENT_REQUEST",
        actor_user_id=user.id,
        actor_role="DOCTOR",
        target_type="patient",
        target_id=profile.user_id,
        consent_id=consent.id,
        detail={"scope": body.scope, "purpose": body.purpose, "days": body.days},
        request=request,
    )

    doc = db.get(DoctorProfile, user.id)
    notify(
        profile.user_id,
        "consent.requested",
        {
            "consent_id": consent.id,
            "doctor_name": doc.name if doc else "A clinician",
            "doctor_facility": doc.facility if doc else "",
            "scope": body.scope,
            "purpose": body.purpose,
            "days": body.days,
        },
    )
    return _to_out(db, consent)


# ─────────────────────────────────────────────────────────────────────────────
# Patient: the notice, in their own language, before they decide
# ─────────────────────────────────────────────────────────────────────────────

SCOPE_LABELS = {
    "symptoms": {
        "en": "the symptoms you have recorded",
        "hi": "आपके दर्ज किए गए लक्षण",
        "kn": "ನೀವು ದಾಖಲಿಸಿದ ಲಕ್ಷಣಗಳು",
    },
    "episodes": {
        "en": "your record of doctor visits and treatments",
        "hi": "आपके डॉक्टर के दौरे और इलाज का रिकॉर्ड",
        "kn": "ನಿಮ್ಮ ವೈದ್ಯರ ಭೇಟಿ ಮತ್ತು ಚಿಕಿತ್ಸೆಯ ದಾಖಲೆ",
    },
    "assessments": {
        "en": "what this app has concluded about your symptoms",
        "hi": "इस ऐप ने आपके लक्षणों के बारे में क्या निष्कर्ष निकाला",
        "kn": "ಈ ಆ್ಯಪ್ ನಿಮ್ಮ ಲಕ್ಷಣಗಳ ಬಗ್ಗೆ ಏನು ತೀರ್ಮಾನಿಸಿದೆ",
    },
}

NOTICE_TEMPLATE = {
    "en": (
        "{doctor} from {facility} is asking to see {scope}. "
        "They will not be able to see your phone number. "
        "This permission lasts {days} days and you can cancel it at any time. "
        "You may say no, and your treatment will not be affected."
    ),
    "hi": (
        "{facility} के {doctor} {scope} देखने की अनुमति मांग रहे हैं। "
        "वे आपका फोन नंबर नहीं देख पाएंगे। "
        "यह अनुमति {days} दिनों तक रहेगी और आप इसे कभी भी रद्द कर सकते हैं। "
        "आप मना कर सकते हैं, इससे आपके इलाज पर कोई असर नहीं पड़ेगा।"
    ),
    "kn": (
        "{facility} ನ {doctor} {scope} ನೋಡಲು ಅನುಮತಿ ಕೇಳುತ್ತಿದ್ದಾರೆ. "
        "ಅವರಿಗೆ ನಿಮ್ಮ ಫೋನ್ ನಂಬರ್ ಕಾಣುವುದಿಲ್ಲ. "
        "ಈ ಅನುಮತಿ {days} ದಿನಗಳವರೆಗೆ ಇರುತ್ತದೆ, ನೀವು ಯಾವಾಗ ಬೇಕಾದರೂ ರದ್ದು ಮಾಡಬಹುದು. "
        "ನೀವು ಬೇಡ ಎನ್ನಬಹುದು, ನಿಮ್ಮ ಚಿಕಿತ್ಸೆಗೆ ಯಾವುದೇ ತೊಂದರೆ ಆಗುವುದಿಲ್ಲ."
    ),
}


@router.get("/{consent_id}/notice")
def consent_notice(
    consent_id: str,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """The exact text that gets read aloud. Consent that cannot be read is not
    consent, and roughly a quarter of the women this system is built for
    cannot read the screen they are being asked to tap."""
    consent = db.get(Consent, consent_id)
    if consent is None or consent.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "consent request not found")

    profile = db.get(PatientProfile, user.id)
    doc = db.get(DoctorProfile, consent.doctor_id)
    lang = profile.language if profile else "en"

    scopes = [s for s in consent.scope.split(",") if s]
    scope_text = ", ".join(
        SCOPE_LABELS.get(s, {}).get(lang, s) for s in scopes
    )
    days = 0
    if consent.expires_at:
        exp = (
            consent.expires_at
            if consent.expires_at.tzinfo
            else consent.expires_at.replace(tzinfo=timezone.utc)
        )
        days = max(0, (exp - datetime.now(timezone.utc)).days)

    text = NOTICE_TEMPLATE.get(lang, NOTICE_TEMPLATE["en"]).format(
        doctor=doc.name if doc else "A clinician",
        facility=doc.facility if doc else "a health facility",
        scope=scope_text,
        days=days,
    )
    return {
        "consent_id": consent.id,
        "language": lang,
        "text": text,
        "scope": [
            {"code": s, "label": SCOPE_LABELS.get(s, {}).get(lang, s)} for s in scopes
        ],
        "days": days,
        "doctor_name": doc.name if doc else None,
        "doctor_facility": doc.facility if doc else None,
        "tts_cache_key": f"consent_notice_{lang}",
    }


@router.post("/{consent_id}/heard", status_code=204)
def mark_heard(
    consent_id: str,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """Records that the notice was actually played. This is evidence of
    informed consent, not of a tap."""
    consent = db.get(Consent, consent_id)
    if consent is None or consent.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "consent request not found")
    profile = db.get(PatientProfile, user.id)
    consent.read_aloud_at = datetime.now(timezone.utc)
    consent.read_aloud_language = profile.language if profile else "en"
    db.commit()
    audit.record(
        db,
        action="CONSENT_NOTICE_HEARD",
        actor_user_id=user.id,
        actor_role="PATIENT",
        consent_id=consent.id,
        request=request,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Patient: decide, and revoke
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{consent_id}/decide", response_model=ConsentOut)
def decide(
    consent_id: str,
    body: ConsentDecision,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    consent = db.get(Consent, consent_id)
    if consent is None or consent.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "consent request not found")
    if consent.status != ConsentStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"this request is already {consent.status.value}"
        )

    now = datetime.now(timezone.utc)
    if body.decision == "allow":
        consent.status = ConsentStatus.ACTIVE
        consent.granted_at = now
    else:
        consent.status = ConsentStatus.DENIED
    db.commit()
    db.refresh(consent)

    audit.record(
        db,
        action="CONSENT_GRANTED" if body.decision == "allow" else "CONSENT_DENIED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="doctor",
        target_id=consent.doctor_id,
        consent_id=consent.id,
        request=request,
    )

    profile = db.get(PatientProfile, user.id)
    notify(
        consent.doctor_id,
        "consent.decided",
        {
            "consent_id": consent.id,
            "status": consent.status.value,
            "patient_id": consent.patient_id if body.decision == "allow" else None,
            "patient_name": profile.name if (profile and body.decision == "allow") else None,
            "aira_code": profile.aira_code if profile else None,
        },
    )
    return _to_out(db, consent)


@router.post("/{consent_id}/revoke", response_model=ConsentOut)
def revoke(
    consent_id: str,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """Revocation is immediate. There is no session to expire and no cache to
    invalidate, because authorisation was never cached in the first place -
    it is re-evaluated on the doctor's very next request."""
    consent = db.get(Consent, consent_id)
    if consent is None or consent.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "consent not found")
    if consent.status not in (ConsentStatus.ACTIVE, ConsentStatus.PENDING):
        raise HTTPException(status.HTTP_409_CONFLICT, "nothing to revoke")

    consent.status = ConsentStatus.REVOKED
    consent.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(consent)

    audit.record(
        db,
        action="CONSENT_REVOKED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="doctor",
        target_id=consent.doctor_id,
        consent_id=consent.id,
        request=request,
    )
    notify(
        consent.doctor_id,
        "consent.revoked",
        {"consent_id": consent.id, "patient_id": consent.patient_id},
    )
    return _to_out(db, consent)


# ─────────────────────────────────────────────────────────────────────────────
# Listings
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/mine", response_model=list[ConsentOut])
def my_consents(
    user: User = Depends(require_patient), db: Session = Depends(get_db)
):
    """Every patient can see, at any time, exactly who can read their record
    and until when. This screen is not an extra: without it, 'you are in
    control of your data' is a slogan rather than a fact."""
    rows = (
        db.query(Consent)
        .filter(Consent.patient_id == user.id)
        .order_by(Consent.requested_at.desc())
        .all()
    )
    return [_to_out(db, c) for c in rows]


@router.get("/granted", response_model=list[ConsentOut])
def granted_to_me(
    user: User = Depends(require_doctor), db: Session = Depends(get_db)
):
    rows = (
        db.query(Consent)
        .filter(Consent.doctor_id == user.id)
        .order_by(Consent.requested_at.desc())
        .all()
    )
    return [_to_out(db, c) for c in rows]
