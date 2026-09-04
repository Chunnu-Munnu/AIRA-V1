"""
The MySQL schema.

Three design decisions worth defending in a viva:

1. Clinical history is APPEND-ONLY. A symptom is never edited into a new
   state; a new episode is written. You cannot understand a diagnostic delay
   from a table that has been overwritten.

2. Every assessment stores its ruleset_version AND the model contributions
   that produced it. Six months later you can reopen any decision and see
   exactly what the system knew and why it concluded what it did. This is
   what "explainable" means in practice, as opposed to on a slide.

3. There is no caste column, no religion column, no income column and no
   region column. Not "we do not use them" - they do not exist. A field that
   is absent cannot leak, cannot be correlated against, and cannot quietly
   become a feature when someone retrains a model in a hurry.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────


class Role(str, enum.Enum):
    PATIENT = "PATIENT"
    DOCTOR = "DOCTOR"
    ADMIN = "ADMIN"


class ConsentStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SymptomStatus(str, enum.Enum):
    watching = "watching"
    resolved = "resolved"
    escalated = "escalated"


# ─────────────────────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    patient: Mapped["PatientProfile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    doctor: Mapped["DoctorProfile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class PatientProfile(Base):
    __tablename__ = "patient_profile"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    # The AIRA code is this project's stand-in for an ABHA address. It is the
    # handle a doctor uses to REQUEST access - never to gain it.
    aira_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    dob: Mapped[Date] = mapped_column(Date, nullable=False)
    sex: Mapped[str] = mapped_column(String(10), nullable=False)
    language: Mapped[str] = mapped_column(String(5), default="en", nullable=False)
    village: Mapped[str | None] = mapped_column(String(120))

    # Risk factors are stored as a comma-separated token list matching the
    # vocabulary in rules/screening.json risk_factor_definitions.
    risk_factors: Mapped[str] = mapped_column(Text, default="", nullable=False)
    family_history: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    bmi: Mapped[float | None] = mapped_column(Float)

    user: Mapped[User] = relationship(back_populates="patient")


class DoctorProfile(Base):
    __tablename__ = "doctor_profile"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    reg_no: Mapped[str] = mapped_column(String(60), nullable=False)
    facility: Mapped[str] = mapped_column(String(160), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(80))

    user: Mapped[User] = relationship(back_populates="doctor")


# ─────────────────────────────────────────────────────────────────────────────
# Consent - the ABDM artefact
# ─────────────────────────────────────────────────────────────────────────────


class LinkPin(Base):
    """Short-lived challenge the patient shows a doctor. Possession of the
    AIRA code alone grants nothing; it must be paired with a PIN the patient
    generated in the last few minutes, and even then it only opens a REQUEST.
    """

    __tablename__ = "link_pin"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Consent(Base):
    """A real ABDM-shaped consent artefact: scoped, purpose-bound,
    time-bound and revocable. Every field here maps to a field in the ABDM
    consent request schema. Swap the identity provider for ABHA and the
    record store for an HIP and the protocol is unchanged.
    """

    __tablename__ = "consent"
    __table_args__ = (
        Index("ix_consent_pair", "patient_id", "doctor_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doctor_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ConsentStatus] = mapped_column(
        Enum(ConsentStatus), default=ConsentStatus.PENDING, nullable=False
    )
    scope: Mapped[str] = mapped_column(
        Text, default="symptoms,episodes,assessments", nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), default="CAREMGT", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Consent must be comprehended, not merely clicked. This records that the
    # terms were played aloud in the patient's own language before approval.
    read_aloud_language: Mapped[str | None] = mapped_column(String(5))
    read_aloud_at: Mapped[datetime | None] = mapped_column(DateTime)

    def is_live(self, now: datetime | None = None) -> bool:
        now = now or _now()
        if self.status != ConsentStatus.ACTIVE:
            return False
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and _aware(self.expires_at) <= now:
            return False
        return True


def _aware(dt: datetime) -> datetime:
    """MySQL DATETIME columns come back naive. Compare them in UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Clinical record - append only
# ─────────────────────────────────────────────────────────────────────────────


class Symptom(Base):
    __tablename__ = "symptom"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(40), nullable=False)
    # Mandatory. Without an onset date there is no clock, and without a clock
    # there is no trajectory and no product.
    onset_date: Mapped[Date] = mapped_column(Date, nullable=False)
    status: Mapped[SymptomStatus] = mapped_column(
        Enum(SymptomStatus), default=SymptomStatus.watching, nullable=False
    )
    # Snapshotted from the ruleset at creation time so a later rule change
    # cannot silently rewrite the history of this symptom.
    safe_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_red_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(12), default="text", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class SeverityReading(Base):
    __tablename__ = "severity_reading"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    symptom_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("symptom.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reading_date: Mapped[Date] = mapped_column(Date, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Episode(Base):
    """One healthcare encounter. This table is what makes AIRA longitudinal.
    Without it there is no loop to detect."""

    __tablename__ = "episode"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cluster_id: Mapped[str] = mapped_column(String(40), nullable=False)
    encounter_date: Mapped[Date] = mapped_column(Date, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    intervention_class: Mapped[str] = mapped_column(String(30), default="none", nullable=False)
    investigation_ordered: Mapped[str] = mapped_column(String(60), default="none", nullable=False)
    outcome_at_followup: Mapped[str | None] = mapped_column(String(20))
    recorded_by: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(12), default="patient", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class CheckBack(Base):
    """Scheduled by the clock, not by the user opening the app. Someone who
    stops opening the app is exactly the person we most need to hear from."""

    __tablename__ = "checkback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symptom_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("symptom.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_for: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime)
    # same | better | gone | worse | new_problem
    response: Mapped[str | None] = mapped_column(String(20))
    severity: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(12), default="app", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Assessment(Base):
    __tablename__ = "assessment"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    as_of: Mapped[Date] = mapped_column(Date, nullable=False)
    tier: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    ladder_level: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ladder_code: Mapped[str] = mapped_column(String(40), nullable=False)
    anchor_symptom: Mapped[str | None] = mapped_column(String(60))

    features_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    investigations_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # The explainability payload. Stored, not recomputed - a model retrained
    # tomorrow must not be able to change what we told a patient today.
    model_version: Mapped[str | None] = mapped_column(String(40))
    model_probability: Mapped[float | None] = mapped_column(Float)
    contributions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    ruleset_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class VoiceNote(Base):
    __tablename__ = "voice_note"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    translated_en: Mapped[str | None] = mapped_column(Text)
    mapped_codes: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    provider: Mapped[str] = mapped_column(String(20), default="mock", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ClinicianOverride(Base):
    """When a clinician disagrees with AIRA, that disagreement is the single
    most valuable training signal the system will ever receive. It is stored,
    never discarded, and never silently used to retrain without review."""

    __tablename__ = "clinician_override"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessment.id", ondelete="CASCADE"), nullable=False
    )
    doctor_id: Mapped[str] = mapped_column(String(32), ForeignKey("user.id"), nullable=False)
    original_tier: Mapped[str] = mapped_column(String(10), nullable=False)
    new_tier: Mapped[str] = mapped_column(String(10), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class MedicalDocument(Base):
    """A report the patient uploaded.

    The bytes are stored on disk, not in MySQL: a scanned PDF in a BLOB
    column makes every backup and every replica carry it, and there is no
    good reason for a database row to be four megabytes.

    `extracted_json` holds what the deterministic parser found. `summary_*`
    hold the two audience renderings. Nothing in this table was written by a
    language model without passing the verifier first, and `verified` records
    whether it did.
    """

    __tablename__ = "medical_document"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[str] = mapped_column(String(32), ForeignKey("user.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str | None] = mapped_column(String(500))

    doc_kind: Mapped[str] = mapped_column(String(30), default="report", nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    extracted_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    summary_patient: Mapped[str | None] = mapped_column(Text)
    summary_clinician: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    # An uploaded report showing a test was actually done is what breaks the
    # investigation-gap loop. This links the document to the episode it
    # created, so the two can never disagree about whether a test happened.
    episode_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("episode.id"))

    # "Report uploaded but not reviewed" is one of the care gaps the spec asks
    # AIRA to surface, so the review has to be an explicit, recorded act - not
    # something inferred from the clinician having opened a tab.
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("user.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ClinicianNote(Base):
    """The editable handover note.

    AIRA drafts it from what the rules already decided; the clinician edits
    it and releases it to the patient. Both versions are kept: `draft_text`
    as generated, `final_text` as sent. The difference between them is the
    most honest measure of how good the drafting is, and throwing it away
    would mean never being able to improve.
    """

    __tablename__ = "clinician_note"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doctor_id: Mapped[str] = mapped_column(String(32), ForeignKey("user.id"), nullable=False)
    assessment_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("assessment.id"))
    consent_id: Mapped[str | None] = mapped_column(String(32))

    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    final_text: Mapped[str] = mapped_column(Text, nullable=False)
    investigations: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    follow_up_days: Mapped[int | None] = mapped_column(Integer)
    drafted_by: Mapped[str] = mapped_column(String(20), default="template", nullable=False)

    status: Mapped[str] = mapped_column(String(12), default="draft", nullable=False, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ChatMessage(Base):
    """Every question asked and every answer given, with the guardrail trace.

    Kept because an AI answer nobody can retrieve afterwards cannot be
    audited, complained about, or improved. `trace_json` carries the route
    decision, what was retrieved, and every verification check, so any answer
    can be reconstructed months later without re-running the model.
    """

    __tablename__ = "chat_message"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    audience: Mapped[str] = mapped_column(String(12), nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    subject_patient_id: Mapped[str | None] = mapped_column(String(32))

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    refused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(40))
    citations_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    trace_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Audit - append only, and the application user is not granted DELETE on it
# ─────────────────────────────────────────────────────────────────────────────


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_actor_time", "actor_user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor_user_id: Mapped[str | None] = mapped_column(String(32))
    actor_role: Mapped[str | None] = mapped_column(String(12))
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(32))
    consent_id: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(12), default="ok", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class CareTask(Base):
    """One line on the patient's "what to do now" checklist.

    THE STORY THIS TABLE HOLDS TOGETHER

    Every other symptom checker stops at a risk score. AIRA does not: once a
    pattern is flagged or a doctor sets a plan, there is always a concrete
    next step, and this table is the list of them. The care state (see
    engine/next_action.py) decides WHICH tasks exist; this table stores their
    mutable half - whether the patient has started or finished each one, and
    when it falls overdue.

    TWO RULES

    1. AIRA never marks a task done. `status` moves to `completed` only when
       the patient taps it, or when a hard fact makes it true (a released note
       completes "attend consultation"; an uploaded report completes "upload
       result"). A checklist that ticks itself is a checklist nobody trusts.

    2. Tasks are keyed by (patient_id, key). Regenerating the plan for a new
       state re-emits the same key with its status intact, so progress is
       never lost when the state advances.
    """

    __tablename__ = "care_task"
    __table_args__ = (
        UniqueConstraint("patient_id", "key", name="uq_care_task_patient_key"),
        Index("ix_care_task_patient_status", "patient_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(48), nullable=False)
    # The care state this task belongs to - RISK_FLAGGED, VISIT_REQUIRED,
    # VISIT_COMPLETED, REPORT_UPLOADED, PLAN_RECEIVED, FOLLOW_UP, LOOP_COMPLETE.
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    label_en: Mapped[str] = mapped_column(String(160), nullable=False)
    label_hi: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    label_kn: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    # pending | in_progress | completed | overdue
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    # aira | doctor - who put this task on the list
    source: Mapped[str] = mapped_column(String(12), default="aira", nullable=False)
    note_id: Mapped[str | None] = mapped_column(String(32))
    due_date: Mapped[Date | None] = mapped_column(Date)
    auto_complete_on: Mapped[str | None] = mapped_column(String(32))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class CareResponse(Base):
    """The treatment-response loop: "how are you feeling now?" and "did the
    treatment help?", asked after a doctor's plan has had time to work.

    This is a distinct thing from a CheckBack. A CheckBack is scheduled by the
    clock against one symptom. A CareResponse is the patient's verdict on a
    whole plan of care, and a run of "same / no" verdicts across successive
    plans is exactly the treatment-refractory pattern the Loop Detector needs
    to see.
    """

    __tablename__ = "care_response"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note_id: Mapped[str | None] = mapped_column(String(32))
    # better | same | worse
    feeling: Mapped[str] = mapped_column(String(10), nullable=False)
    # yes | partially | no | not_started
    helped: Mapped[str] = mapped_column(String(12), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


__all__ = [
    "Base",
    "Role",
    "ConsentStatus",
    "SymptomStatus",
    "User",
    "PatientProfile",
    "DoctorProfile",
    "LinkPin",
    "Consent",
    "Symptom",
    "SeverityReading",
    "Episode",
    "CheckBack",
    "Assessment",
    "VoiceNote",
    "MedicalDocument",
    "ClinicianNote",
    "ChatMessage",
    "ClinicianOverride",
    "CareTask",
    "CareResponse",
    "AuditLog",
    "RefreshToken",
]
