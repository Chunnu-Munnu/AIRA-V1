"""
Authentication and authorisation dependencies.

The distinction that matters, and that most teams get wrong:

    AUTHENTICATION  proves who you are.        (the JWT)
    AUTHORISATION   proves you may see THIS.   (the consent artefact)

A doctor logging in successfully grants them access to precisely zero patient
records. Access to one patient exists only while that patient's consent
artefact is live, and that is re-checked on EVERY request rather than cached
in the session - which is what makes revocation instant instead of
"instant at next login".
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import audit
from .db import get_db
from .security import decode_access_token
from .tables import Consent, ConsentStatus, PatientProfile, Role, User

bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    payload = decode_access_token(creds.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")

    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account not active")

    request.state.user = user
    return user


def require_role(*roles: Role):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"this endpoint requires role {' or '.join(r.value for r in roles)}",
            )
        return user

    return dependency


require_patient = require_role(Role.PATIENT)
require_doctor = require_role(Role.DOCTOR)
require_admin = require_role(Role.ADMIN)
require_clinical = require_role(Role.DOCTOR, Role.ADMIN)


def live_consent(db: Session, doctor_id: str, patient_id: str) -> Consent | None:
    """The authorisation check. Expiry is evaluated here rather than by a
    background job, so an artefact that lapsed one second ago is already dead
    even if nothing has swept the table yet."""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(Consent)
        .filter(
            Consent.doctor_id == doctor_id,
            Consent.patient_id == patient_id,
            Consent.status == ConsentStatus.ACTIVE,
        )
        .all()
    )
    for c in rows:
        if c.is_live(now):
            return c
        # Lapsed on read: mark it, so the dashboard and the audit trail agree.
        c.status = ConsentStatus.EXPIRED
        db.commit()
    return None


def authorise_patient_access(
    patient_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> tuple[User, Consent | None]:
    """Returns (patient_user, consent_or_None).

    A patient reading their own record needs no consent artefact - consent to
    yourself is meaningless. Everyone else needs a live artefact, and the
    check is logged either way.
    """
    patient = db.get(User, patient_id)
    if patient is None or patient.role != Role.PATIENT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "patient not found")

    if user.role == Role.PATIENT:
        if user.id != patient_id:
            audit.record(
                db,
                action="ACCESS_DENIED",
                actor_user_id=user.id,
                actor_role=user.role.value,
                target_type="patient",
                target_id=patient_id,
                outcome="denied",
                detail="patient attempted to read another patient's record",
                request=request,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "you may only read your own record")
        return patient, None

    if user.role == Role.ADMIN:
        # Admins administer the system, they do not read clinical records.
        # Deliberate: an ops console that can read every patient's symptoms is
        # a breach waiting to be written up.
        audit.record(
            db,
            action="ACCESS_DENIED",
            actor_user_id=user.id,
            actor_role=user.role.value,
            target_type="patient",
            target_id=patient_id,
            outcome="denied",
            detail="admin role has no clinical read access by design",
            request=request,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "administrators do not have access to clinical records",
        )

    consent = live_consent(db, doctor_id=user.id, patient_id=patient_id)
    if consent is None:
        audit.record(
            db,
            action="ACCESS_DENIED",
            actor_user_id=user.id,
            actor_role=user.role.value,
            target_type="patient",
            target_id=patient_id,
            outcome="denied",
            detail="no live consent artefact",
            request=request,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "no active consent from this patient. request access and wait for approval.",
        )

    audit.record(
        db,
        action="RECORD_READ",
        actor_user_id=user.id,
        actor_role=user.role.value,
        target_type="patient",
        target_id=patient_id,
        consent_id=consent.id,
        request=request,
    )
    return patient, consent


def patient_profile(db: Session, user_id: str) -> PatientProfile:
    prof = db.get(PatientProfile, user_id)
    if prof is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "patient profile not found")
    return prof
