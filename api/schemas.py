"""Request and response models. Every request body is validated here, which
is also what keeps hand-built SQL out of the codebase entirely."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ── auth ────────────────────────────────────────────────────────────────────


class PatientSignup(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=10, max_length=15)
    password: str = Field(min_length=8, max_length=128)
    dob: date
    sex: Literal["male", "female", "other"]
    language: Literal["en", "hi", "kn"] = "en"
    village: str | None = Field(default=None, max_length=120)
    risk_factors: list[str] = []
    bmi: float | None = None

    @field_validator("phone")
    @classmethod
    def digits_only(cls, v: str) -> str:
        cleaned = "".join(ch for ch in v if ch.isdigit())
        if len(cleaned) < 10:
            raise ValueError("phone must contain at least 10 digits")
        return cleaned


class DoctorSignup(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    reg_no: str = Field(min_length=3, max_length=60)
    facility: str = Field(min_length=2, max_length=160)
    specialty: str | None = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    identifier: str  # phone for patients, email for doctors and admins
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    display_name: str
    aira_code: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


# ── consent ─────────────────────────────────────────────────────────────────


class LinkPinResponse(BaseModel):
    aira_code: str
    pin: str
    expires_at: datetime
    valid_for_minutes: int


class ConsentRequestBody(BaseModel):
    aira_code: str
    pin: str = Field(min_length=6, max_length=6)
    purpose: Literal["CAREMGT", "SECOND_OPINION", "SCREENING"] = "CAREMGT"
    scope: list[str] = ["symptoms", "episodes", "assessments"]
    days: int = Field(default=90, ge=1, le=365)


class ConsentDecision(BaseModel):
    decision: Literal["allow", "deny"]
    read_aloud_language: str | None = None


class ConsentOut(BaseModel):
    id: str
    status: str
    purpose: str
    scope: list[str]
    doctor_name: str | None = None
    doctor_facility: str | None = None
    patient_name: str | None = None
    aira_code: str | None = None
    requested_at: datetime
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    read_aloud_at: datetime | None = None


class LanguageChange(BaseModel):
    language: Literal["en", "hi", "kn"]


class TreatmentResponse(BaseModel):
    feeling: Literal["better", "same", "worse"]
    helped: Literal["yes", "partially", "no", "not_started"]
    note: str | None = Field(default=None, max_length=500)


# ── clinical ────────────────────────────────────────────────────────────────


class SymptomCreate(BaseModel):
    code: str
    onset_date: date
    severity: int | None = Field(default=None, ge=1, le=10)
    source: Literal["text", "voice", "clinician"] = "text"

    @field_validator("onset_date")
    @classmethod
    def not_in_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("onset_date cannot be in the future")
        return v


class EpisodeCreate(BaseModel):
    cluster_id: str
    encounter_date: date
    provider_type: str = "unknown"
    intervention_class: str = "none"
    investigation_ordered: str = "none"
    outcome_at_followup: str | None = None


class CheckBackAnswer(BaseModel):
    response: Literal["same", "better", "gone", "worse", "new_problem"]
    severity: int | None = Field(default=None, ge=1, le=10)
    note: str | None = Field(default=None, max_length=2000)
    new_symptom_code: str | None = None


class OverrideCreate(BaseModel):
    new_tier: Literal["LOW", "MODERATE", "HIGH"]
    rationale: str = Field(min_length=10, max_length=2000)


# ── voice ───────────────────────────────────────────────────────────────────


class TranscribeRequest(BaseModel):
    audio_base64: str | None = None
    language: Literal["en", "hi", "kn"] = "en"
    demo_key: str | None = None  # replays a pre-rendered clip, costs 0 credits


class SpeakRequest(BaseModel):
    text: str = Field(max_length=1000)
    language: Literal["en", "hi", "kn"] = "en"
    cache_key: str | None = None


# ── chat ────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    language: Literal["en", "hi", "kn"] = "en"
    # Optional, and only meaningful for a clinician asking about a patient
    # they hold live consent for. A patient's own questions ignore it - the
    # subject of a patient's question is always the patient.
    patient_id: str | None = Field(default=None, max_length=32)


class Citation(BaseModel):
    source: str
    section: str | None = None
    quote: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    refused: bool = False
    refusal_reason: str | None = None
    verified: bool = True
    fallback_used: bool = False
