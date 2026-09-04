"""Signup, login, refresh, logout."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..schemas import (
    DoctorSignup,
    LoginRequest,
    PatientSignup,
    RefreshRequest,
    TokenPair,
)
from ..security import (
    create_access_token,
    hash_password,
    hash_token,
    new_aira_code,
    new_refresh_token,
    verify_password,
)
from ..tables import DoctorProfile, PatientProfile, RefreshToken, Role, User

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def _issue(db: Session, user: User, display_name: str, aira_code: str | None) -> TokenPair:
    raw_refresh = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.refresh_token_days),
        )
    )
    db.commit()
    return TokenPair(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=raw_refresh,
        role=user.role.value,
        user_id=user.id,
        display_name=display_name,
        aira_code=aira_code,
    )


@router.post("/signup/patient", response_model=TokenPair, status_code=201)
def signup_patient(body: PatientSignup, request: Request, db: Session = Depends(get_db)):
    if db.query(User).filter(User.phone == body.phone).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "an account with this phone already exists")

    user = User(
        role=Role.PATIENT,
        phone=body.phone,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()

    # The AIRA code is generated once and never changes. It is an address, not
    # a credential: knowing it lets a doctor ASK for access and nothing more.
    code = new_aira_code()
    while db.query(PatientProfile).filter(PatientProfile.aira_code == code).first():
        code = new_aira_code()

    db.add(
        PatientProfile(
            user_id=user.id,
            aira_code=code,
            name=body.name,
            dob=body.dob,
            sex=body.sex,
            language=body.language,
            village=body.village,
            risk_factors=",".join(sorted(set(body.risk_factors))),
            family_history=json.dumps([]),
            bmi=body.bmi,
        )
    )
    db.commit()

    audit.record(
        db,
        action="SIGNUP_PATIENT",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="user",
        target_id=user.id,
        request=request,
    )
    return _issue(db, user, body.name, code)


@router.post("/signup/doctor", response_model=TokenPair, status_code=201)
def signup_doctor(body: DoctorSignup, request: Request, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "an account with this email already exists")

    user = User(
        role=Role.DOCTOR,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()
    db.add(
        DoctorProfile(
            user_id=user.id,
            name=body.name,
            reg_no=body.reg_no,
            facility=body.facility,
            specialty=body.specialty,
        )
    )
    db.commit()

    audit.record(
        db,
        action="SIGNUP_DOCTOR",
        actor_user_id=user.id,
        actor_role="DOCTOR",
        target_type="user",
        target_id=user.id,
        detail={"reg_no": body.reg_no, "facility": body.facility},
        request=request,
    )
    return _issue(db, user, body.name, None)


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    identifier = body.identifier.strip()
    user = (
        db.query(User)
        .filter((User.email == identifier) | (User.phone == identifier))
        .first()
    )

    now = datetime.now(timezone.utc)

    if user is not None and user.locked_until is not None:
        locked_until = (
            user.locked_until
            if user.locked_until.tzinfo
            else user.locked_until.replace(tzinfo=timezone.utc)
        )
        if locked_until > now:
            audit.record(
                db,
                action="LOGIN",
                actor_user_id=user.id,
                outcome="denied",
                detail="account temporarily locked",
                request=request,
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many failed attempts. try again shortly.",
            )

    if user is None or not verify_password(body.password, user.password_hash):
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_logins = 0
            db.commit()
        audit.record(
            db,
            action="LOGIN",
            actor_user_id=user.id if user else None,
            outcome="denied",
            detail="bad credentials",
            request=request,
        )
        # Identical message whether the account exists or not - otherwise this
        # endpoint becomes a way to enumerate who is registered.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account disabled")

    user.failed_logins = 0
    user.locked_until = None
    db.commit()

    display, code = "user", None
    if user.role == Role.PATIENT:
        prof = db.get(PatientProfile, user.id)
        if prof:
            display, code = prof.name, prof.aira_code
    elif user.role == Role.DOCTOR:
        prof = db.get(DoctorProfile, user.id)
        if prof:
            display = prof.name
    else:
        display = user.email or "administrator"

    audit.record(
        db, action="LOGIN", actor_user_id=user.id, actor_role=user.role.value, request=request
    )
    return _issue(db, user, display, code)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Refresh tokens rotate: the presented token is revoked and a new one
    issued. A stolen refresh token is therefore usable at most once, and its
    use invalidates the legitimate holder's token - which is detectable."""
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_token(body.refresh_token))
        .first()
    )
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")

    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token expired")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account not active")

    row.revoked_at = now
    db.commit()

    display, code = "user", None
    if user.role == Role.PATIENT:
        prof = db.get(PatientProfile, user.id)
        if prof:
            display, code = prof.name, prof.aira_code
    elif user.role == Role.DOCTOR:
        prof = db.get(DoctorProfile, user.id)
        if prof:
            display = prof.name

    return _issue(db, user, display, code)


@router.post("/logout", status_code=204)
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    for row in (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .all()
    ):
        row.revoked_at = now
    db.commit()
    audit.record(
        db, action="LOGOUT", actor_user_id=user.id, actor_role=user.role.value, request=request
    )
