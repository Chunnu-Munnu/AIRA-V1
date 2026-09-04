"""
Administrator console.

Note what is absent: there is no endpoint here that returns a patient's
symptoms. Administrators run the system; they do not read clinical records.
An ops console with a "view any patient" button is a breach waiting to be
written up, and building one would undercut every privacy claim on the
consent screen.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db, ping
from ..deps import require_admin
from ..service import rules
from ..tables import (
    Assessment,
    AuditLog,
    CheckBack,
    ClinicianOverride,
    Consent,
    ConsentStatus,
    DoctorProfile,
    Episode,
    Role,
    Symptom,
    User,
)
from ..ws import manager

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def overview(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rs = rules()
    today = date.today()

    tiers = dict(
        db.query(Assessment.tier, func.count(Assessment.id))
        .group_by(Assessment.tier)
        .all()
    )
    ladders = dict(
        db.query(Assessment.ladder_level, func.count(Assessment.id))
        .group_by(Assessment.ladder_level)
        .all()
    )

    overdue = (
        db.query(CheckBack)
        .filter(CheckBack.responded_at.is_(None), CheckBack.scheduled_for < today)
        .count()
    )

    # The operational metric that matters most. Every episode with no
    # investigation is a chance that was not taken.
    episodes_total = db.query(Episode).count()
    episodes_no_inv = (
        db.query(Episode).filter(Episode.investigation_ordered == "none").count()
    )

    return {
        "system": {
            "mysql_version": ping(),
            "ruleset_version": rs.version,
            "symptoms_loaded": len(rs.symptoms),
            "red_flags_loaded": len(rs.red_flags),
            "combination_rules": len(rs.combinations),
            "screening_programmes": len(rs.programmes),
            "needs_clinical_review": rs.symptoms_doc.get("needs_clinical_review", False),
            "websocket_connections": sum(manager.stats().values()),
        },
        "users": {
            "patients": db.query(User).filter(User.role == Role.PATIENT).count(),
            "doctors": db.query(User).filter(User.role == Role.DOCTOR).count(),
            "admins": db.query(User).filter(User.role == Role.ADMIN).count(),
        },
        "consent": {
            status.value: db.query(Consent).filter(Consent.status == status).count()
            for status in ConsentStatus
        },
        "clinical": {
            "symptoms_tracked": db.query(Symptom).count(),
            "episodes_recorded": episodes_total,
            "episodes_without_investigation": episodes_no_inv,
            "investigation_gap_rate": round(episodes_no_inv / episodes_total, 3)
            if episodes_total
            else None,
            "assessments": db.query(Assessment).count(),
            "by_tier": tiers,
            "by_ladder_level": ladders,
            "checkbacks_overdue": overdue,
            "clinician_overrides": db.query(ClinicianOverride).count(),
        },
    }


@router.get("/audit")
def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    action: str | None = None,
    outcome: str | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """The append-only trail. Denials are in here too - an audit log that
    records only what succeeded cannot tell you someone spent an afternoon
    guessing link PINs."""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if outcome:
        q = q.filter(AuditLog.outcome == outcome)
    rows = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "at": r.created_at.isoformat(),
            "actor": r.actor_user_id,
            "role": r.actor_role,
            "action": r.action,
            "target": f"{r.target_type}:{r.target_id}" if r.target_type else None,
            "consent_id": r.consent_id,
            "outcome": r.outcome,
            "detail": r.detail,
            "ip": r.ip,
        }
        for r in rows
    ]


@router.get("/security-report")
def security_report(
    user: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """What a security reviewer would ask for first."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    denials = (
        db.query(AuditLog.action, func.count(AuditLog.id))
        .filter(AuditLog.outcome == "denied", AuditLog.created_at >= since)
        .group_by(AuditLog.action)
        .all()
    )
    reads = (
        db.query(AuditLog.actor_user_id, func.count(AuditLog.id))
        .filter(AuditLog.action == "RECORD_READ", AuditLog.created_at >= since)
        .group_by(AuditLog.actor_user_id)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
        .all()
    )
    return {
        "window_days": 7,
        "denials_by_action": {a: c for a, c in denials},
        "most_active_readers": [
            {"doctor_id": uid, "record_reads": count} for uid, count in reads
        ],
        "controls": {
            "password_hashing": "argon2id",
            "access_token_lifetime_minutes": 15,
            "refresh_token_rotation": True,
            "authorisation_model": "consent artefact, re-checked per request",
            "revocation_latency": "next request",
            "audit": "append-only; app user has no DELETE grant on audit_log",
            "admin_clinical_access": "none by design",
            "pii_to_llm": "blocked at the adapter; age band and sex only",
            "forbidden_features": ["caste", "religion", "income", "region"],
        },
    }


@router.get("/doctors")
def doctors(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(DoctorProfile).all()
    out = []
    for d in rows:
        active = (
            db.query(Consent)
            .filter(Consent.doctor_id == d.user_id, Consent.status == ConsentStatus.ACTIVE)
            .count()
        )
        out.append(
            {
                "user_id": d.user_id,
                "name": d.name,
                "reg_no": d.reg_no,
                "facility": d.facility,
                "specialty": d.specialty,
                "patients_with_active_consent": active,
            }
        )
    return out


@router.get("/ruleset")
def ruleset(user: User = Depends(require_admin)):
    """The rules are data. This endpoint exists so a clinical reviewer can
    read exactly what the system is deciding on, without reading any code."""
    rs = rules()
    return {
        "version": rs.version,
        "needs_clinical_review": rs.symptoms_doc.get("needs_clinical_review"),
        "review_note": rs.symptoms_doc.get("review_note"),
        "symptoms": [
            {
                "code": c,
                "cluster": s["cluster"],
                "safe_window_days": s["safe_window_days"],
                "milestones": [m["day"] for m in s.get("milestones", [])],
                "expected_investigations": s.get("expected_investigations", []),
                "source": s.get("citation", {}).get("source"),
                "section": s.get("citation", {}).get("section"),
                "confidence": s.get("citation", {}).get("confidence"),
            }
            for c, s in sorted(rs.symptoms.items())
        ],
        "red_flags": [
            {"id": f["id"], "symptom": f["symptom"], "action": f["action"]}
            for f in rs.red_flags
        ],
        "combination_rules": [
            {"id": c["id"], "label": c["label"], "action": c["then"]["action"]}
            for c in rs.combinations
        ],
    }
