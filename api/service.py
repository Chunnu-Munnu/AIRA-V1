"""
The bridge between the database and the pure decision engine.

The engine knows nothing about SQLAlchemy, FastAPI or MySQL, and that is
deliberate: every clinical rule in this project can be tested in 90
milliseconds with no database running. This module is the only place that
translates between the two worlds.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from engine import assess as run_assessment
from engine.models import Episode as EngineEpisode
from engine.models import PatientState, Person, SeverityPoint
from engine.models import SymptomRecord as EngineSymptom
from engine.rules_engine import next_checkback
from engine.rules_loader import Ruleset, load_ruleset
from rag.corpus import investigation_label

from .config import get_settings
from .tables import (
    Assessment,
    CheckBack,
    Episode,
    PatientProfile,
    SeverityReading,
    Symptom,
    SymptomStatus,
)

settings = get_settings()


def rules() -> Ruleset:
    return load_ruleset(settings.ruleset_dir)


def age_from_dob(dob: date, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    return as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))


def build_state(db: Session, patient_id: str, as_of: date | None = None) -> PatientState:
    """Assemble everything AIRA knows about one person into the engine's
    input type. This is the only query path the assessment ever takes."""
    as_of = as_of or date.today()
    profile = db.get(PatientProfile, patient_id)
    if profile is None:
        raise ValueError(f"no patient profile for {patient_id}")

    person = Person(
        age=age_from_dob(profile.dob, as_of),
        sex=profile.sex,  # type: ignore[arg-type]
        risk_factors={r for r in profile.risk_factors.split(",") if r},
        family_history=json.loads(profile.family_history or "[]"),
        bmi=profile.bmi,
        language=profile.language,
    )

    rows = db.query(Symptom).filter(Symptom.patient_id == patient_id).all()
    symptoms: list[EngineSymptom] = []
    for row in rows:
        readings = (
            db.query(SeverityReading)
            .filter(SeverityReading.symptom_id == row.id)
            .order_by(SeverityReading.reading_date)
            .all()
        )
        symptoms.append(
            EngineSymptom(
                code=row.code,
                onset_date=row.onset_date,
                severity_log=[SeverityPoint(r.reading_date, r.score) for r in readings],
                status=row.status.value,  # type: ignore[arg-type]
                source=row.source,  # type: ignore[arg-type]
            )
        )

    episodes = [
        EngineEpisode(
            encounter_date=e.encounter_date,
            cluster_id=e.cluster_id,
            provider_type=e.provider_type,
            intervention_class=e.intervention_class,
            investigation_ordered=e.investigation_ordered,
            outcome_at_followup=e.outcome_at_followup,
        )
        for e in db.query(Episode).filter(Episode.patient_id == patient_id).all()
    ]

    missed = (
        db.query(CheckBack)
        .filter(
            CheckBack.patient_id == patient_id,
            CheckBack.responded_at.is_(None),
            CheckBack.scheduled_for < as_of,
        )
        .count()
    )

    return PatientState(
        person=person,
        symptoms=symptoms,
        episodes=episodes,
        missed_checkbacks=missed,
    )


def assess_and_store(
    db: Session, patient_id: str, as_of: date | None = None
) -> Assessment:
    """Run the engine and persist the result verbatim.

    The stored row includes the ruleset_version and the model contributions.
    A model retrained tomorrow cannot change what we told a patient today.
    """
    as_of = as_of or date.today()
    state = build_state(db, patient_id, as_of)
    rs = rules()

    # Model wiring point. When ml/artifacts/risk_ebm.pkl exists the loader
    # supplies a probability and a contribution breakdown here; until then the
    # deterministic layer runs alone, which is a correct and safe degradation.
    probability, contributions, model_version = _maybe_score(state)

    result = run_assessment(
        state,
        as_of=as_of,
        rules=rs,
        model_probability=probability,
        model_contributions=contributions,
        model_version=model_version,
    )

    row = Assessment(
        patient_id=patient_id,
        as_of=as_of,
        tier=result.tier,
        ladder_level=result.ladder_level,
        ladder_code=result.ladder_code,
        anchor_symptom=result.anchor_symptom,
        features_json=json.dumps(result.features, default=str),
        reasons_json=json.dumps(
            [
                {
                    "kind": r.kind,
                    "rule_id": r.rule_id,
                    "clinician": r.message_clinician,
                    "patient": r.message_patient,
                    "citation": r.citation,
                }
                for r in result.reasons
            ],
            default=str,
        ),
        investigations_json=json.dumps(result.recommended_investigations),
        model_version=result.model_version,
        model_probability=result.model_probability,
        contributions_json=json.dumps(result.model_contributions, default=str),
        ruleset_version=result.ruleset_version,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _maybe_score(state: PatientState):
    """Load the EBM if it has been trained, otherwise run rules only."""
    try:
        from ml.predict import score_patient  # local import: optional dependency
    except Exception:
        return None, None, None
    try:
        return score_patient(state)
    except Exception:
        # A broken model must degrade to rules-only, never to a 500. The
        # deterministic layer alone is already a safe product.
        return None, None, None


def schedule_checkbacks(db: Session, patient_id: str, as_of: date | None = None) -> int:
    """Create the next pending check-back for every watched symptom.

    Scheduled by the clock, not by the user opening the app. Someone who stops
    opening the app is exactly the person we most need to hear from.
    """
    as_of = as_of or date.today()
    rs = rules()
    state = build_state(db, patient_id, as_of)
    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == patient_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )
    high_risk = bool(latest and latest.tier == "HIGH")

    created = 0
    for row in (
        db.query(Symptom)
        .filter(Symptom.patient_id == patient_id, Symptom.status == SymptomStatus.watching)
        .all()
    ):
        pending = (
            db.query(CheckBack)
            .filter(CheckBack.symptom_id == row.id, CheckBack.responded_at.is_(None))
            .count()
        )
        if pending:
            continue

        engine_symptom = next((s for s in state.symptoms if s.code == row.code), None)
        if engine_symptom is None:
            continue

        due = next_checkback(engine_symptom, rs, as_of, high_risk=high_risk)
        if due is None:
            continue

        db.add(
            CheckBack(
                patient_id=patient_id,
                symptom_id=row.id,
                scheduled_for=due,
            )
        )
        created += 1

    db.commit()
    return created


_CARD_DISCLAIMER = {
    "en": (
        "AIRA is a prioritisation aid, not a diagnosis. It reports a pattern in "
        "this patient's history. Clinical judgement remains entirely with the "
        "treating doctor."
    ),
    "hi": (
        "AIRA प्राथमिकता तय करने में मदद के लिए है, कोई निदान नहीं। यह इस मरीज़ के "
        "इतिहास में एक पैटर्न बताता है। अंतिम चिकित्सकीय फ़ैसला इलाज करने वाले "
        "डॉक्टर का ही है।"
    ),
    "kn": (
        "AIRA ಆದ್ಯತೆ ನಿಗದಿಪಡಿಸಲು ಸಹಾಯಕ, ರೋಗನಿರ್ಣಯವಲ್ಲ. ಇದು ಈ ರೋಗಿಯ ಇತಿಹಾಸದಲ್ಲಿನ "
        "ಒಂದು ಮಾದರಿಯನ್ನು ವರದಿ ಮಾಡುತ್ತದೆ. ಅಂತಿಮ ವೈದ್ಯಕೀಯ ತೀರ್ಮಾನ ಸಂಪೂರ್ಣವಾಗಿ "
        "ಚಿಕಿತ್ಸೆ ನೀಡುವ ವೈದ್ಯರದ್ದೇ."
    ),
}


def handoff_card(db: Session, patient_id: str, lang: str = "en") -> dict:
    """The artefact the patient carries to the clinic.

    A doctor has a few minutes. This has to be readable in twenty seconds and
    has to contain the one thing a doctor cannot get from the patient: what
    has already been tried, and what has never been tested.
    """
    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == patient_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )
    if latest is None:
        raise ValueError("no assessment yet")

    profile = db.get(PatientProfile, patient_id)
    features = json.loads(latest.features_json)
    reasons = json.loads(latest.reasons_json)

    episodes = (
        db.query(Episode)
        .filter(Episode.patient_id == patient_id)
        .order_by(Episode.encounter_date)
        .all()
    )

    return {
        "generated_on": date.today().isoformat(),
        "patient": {
            "name": profile.name,
            "age": age_from_dob(profile.dob),
            "sex": profile.sex,
            "aira_code": profile.aira_code,
            "village": profile.village,
            "risk_factors": [r for r in profile.risk_factors.split(",") if r],
        },
        "headline": {
            "tier": latest.tier,
            "ladder": latest.ladder_code,
            "anchor": latest.anchor_symptom,
        },
        "the_numbers": {
            "days_elapsed": features.get("days_elapsed"),
            "safe_window_days": features.get("safe_window_days"),
            "duration_ratio": features.get("duration_ratio"),
            "encounters": features.get("n_episodes"),
            "investigations_ever_ordered": features.get("n_investigations"),
            "failed_treatments": features.get("n_failed_treatments"),
            "new_symptoms_since_onset": features.get("breadth_creep"),
            "provider_switches": features.get("provider_switches"),
        },
        "history": [
            {
                "date": e.encounter_date.isoformat(),
                "provider": e.provider_type,
                "given": e.intervention_class,
                "investigated": e.investigation_ordered,
                "outcome": e.outcome_at_followup,
            }
            for e in episodes
        ],
        # Two renderings of the same reasons. The clinician console shows the
        # technical line; the patient's own copy of the card shows the plain
        # sentence, already in their language (it was localised when the
        # assessment was stored).
        "why": [r["clinician"] for r in reasons],
        "why_patient": [r.get("patient") or r["clinician"] for r in reasons],
        # The code AND the words. The clinician's console wants the code
        # because it is what the ruleset and the audit log speak; the patient's
        # card wants the words because it is going to be handed across a desk.
        # Sending both means neither side has to invent the other.
        "suggested_investigations": json.loads(latest.investigations_json),
        "suggested_investigation_labels": [
            {"code": c, "label": investigation_label(c)}
            for c in json.loads(latest.investigations_json)
        ],
        "contributions": json.loads(latest.contributions_json),
        "ruleset_version": latest.ruleset_version,
        "model_version": latest.model_version,
        "disclaimer": _CARD_DISCLAIMER.get(lang, _CARD_DISCLAIMER["en"]),
    }
