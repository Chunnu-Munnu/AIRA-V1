"""
AIRA domain models.

These are deliberately plain dataclasses with no database or web framework
imports. The rules engine and the loop detector must be testable without a
database, a server, or a network connection. Persistence adapters live
elsewhere and convert to and from these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Tier = Literal["LOW", "MODERATE", "HIGH"]
TIER_ORDER: dict[str, int] = {"LOW": 0, "MODERATE": 1, "HIGH": 2}


def higher_tier(a: Tier, b: Tier) -> Tier:
    """Tiers only ever go up. This function is the only way a tier changes."""
    return a if TIER_ORDER[a] >= TIER_ORDER[b] else b


@dataclass
class Person:
    """Who the patient is. No caste, religion, income or region fields exist
    here by design - see rules/ and TECHNICAL.md on forbidden features."""

    age: int
    sex: Literal["male", "female", "other"]
    risk_factors: set[str] = field(default_factory=set)
    family_history: list[dict] = field(default_factory=list)
    bmi: float | None = None
    language: str = "en"

    def ever_smoked(self) -> bool:
        return bool(self.risk_factors & {"tobacco_smoking", "tobacco_smoking_past"})

    def uses_tobacco_any(self) -> bool:
        return bool(
            self.risk_factors
            & {
                "tobacco_smoking",
                "tobacco_smoking_past",
                "tobacco_chewing",
                "areca_nut",
            }
        )


@dataclass
class SeverityPoint:
    on: date
    score: int  # 1-10 as reported by the patient


@dataclass
class SymptomRecord:
    """One symptom, tracked from onset. onset_date is mandatory - it starts
    the clock, and without it there is no trajectory and no product."""

    code: str
    onset_date: date
    severity_log: list[SeverityPoint] = field(default_factory=list)
    status: Literal["watching", "resolved", "escalated"] = "watching"
    source: Literal["text", "voice", "clinician"] = "text"

    def days_elapsed(self, as_of: date) -> int:
        return max(0, (as_of - self.onset_date).days)


@dataclass
class Episode:
    """One healthcare encounter. This is the table that makes AIRA
    longitudinal. Without episodes there is no loop to detect."""

    encounter_date: date
    cluster_id: str
    provider_type: str = "unknown"  # asha | phc | private_clinic | chemist | chc | hospital
    intervention_class: str = "none"  # none | symptomatic | antibiotic | antacid | att | analgesic
    investigation_ordered: str = "none"  # none | cbc | chest_xray | ultrasound | endoscopy | ...
    outcome_at_followup: str | None = None  # resolved | unchanged | worse | unknown

    def is_failed_treatment(self) -> bool:
        return (
            self.intervention_class != "none"
            and self.outcome_at_followup not in (None, "resolved")
        )

    def has_investigation(self) -> bool:
        return self.investigation_ordered not in ("none", "", None)


@dataclass
class PatientState:
    """Everything AIRA knows about one person at one moment in time."""

    person: Person
    symptoms: list[SymptomRecord] = field(default_factory=list)
    episodes: list[Episode] = field(default_factory=list)
    missed_checkbacks: int = 0
    last_screening: dict[str, date] = field(default_factory=dict)  # programme_id -> date

    def active_symptoms(self) -> list[SymptomRecord]:
        return [s for s in self.symptoms if s.status != "resolved"]


@dataclass
class Reason:
    """Every conclusion AIRA reaches carries one of these. A conclusion
    without a Reason is a bug, not a feature."""

    kind: Literal["red_flag", "milestone", "combination", "ladder", "context", "model"]
    rule_id: str
    message_clinician: str
    message_patient: str = ""
    citation: dict = field(default_factory=dict)


@dataclass
class Assessment:
    """The output. Stored verbatim in the assessment table, including the
    ruleset_version, so any decision can be replayed exactly as it was made."""

    as_of: date
    tier: Tier
    ladder_level: int
    ladder_code: str
    anchor_symptom: str | None
    features: dict = field(default_factory=dict)
    reasons: list[Reason] = field(default_factory=list)
    recommended_investigations: list[str] = field(default_factory=list)
    screening_available: list[dict] = field(default_factory=list)
    next_checkback: date | None = None
    ruleset_version: str = ""
    model_version: str | None = None
    model_probability: float | None = None
    model_contributions: list[dict] = field(default_factory=list)

    def patient_lines(self) -> list[str]:
        return [r.message_patient for r in self.reasons if r.message_patient]

    def clinician_lines(self) -> list[str]:
        return [r.message_clinician for r in self.reasons if r.message_clinician]
