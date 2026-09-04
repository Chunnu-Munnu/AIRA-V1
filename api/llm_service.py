"""Shared LLM and retrieval singletons, plus the facts a question is allowed
to be answered against.

Kept out of the routers so that the rule "the model only ever sees what
build_llm_facts returns" is enforced in one readable place rather than
repeated in three endpoints with a chance of drifting.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache

from sqlalchemy.orm import Session

from engine.rules_engine import has_red_flag
from llm.gemini import GeminiClient
from llm.guardrails import age_band

from .config import get_settings
from .service import build_state, rules
from .tables import Assessment, PatientProfile

settings = get_settings()


@lru_cache(maxsize=1)
def gemini() -> GeminiClient:
    return GeminiClient(
        api_key=settings.gemini_api_key,
        mode=settings.gemini_mode,
        model=settings.gemini_model,
        max_calls=settings.gemini_max_calls,
    )


def build_llm_facts(db: Session, patient_id: str, audience: str) -> tuple[dict, list[str]]:
    """The ONLY patient information that may reach the model.

    Returns (facts, names_to_remove). Note what is in it: durations, counts,
    an age BAND and a sex. Note what is not: a name, a phone number, a
    village, an AIRA code, a date of birth, or any date at all. Those are
    stripped again at the adapter, so this is the first of two independent
    barriers rather than the only one.

    A patient asking about their own record gets the trajectory numbers,
    because the whole point is telling them how long this has gone on. They
    do not get the model probability or the tier - those are for the
    clinician, and llm.guardrails.PATIENT bans them from the output anyway.
    """
    prof = db.get(PatientProfile, patient_id)
    if prof is None:
        return {}, []

    latest = (
        db.query(Assessment)
        .filter(Assessment.patient_id == patient_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )

    facts: dict = {"age_band": age_band(_age(prof.dob)), "sex": prof.sex}

    if latest:
        features = json.loads(latest.features_json or "{}")
        for key in (
            "days_elapsed",
            "safe_window_days",
            "duration_ratio",
            "n_episodes",
            "n_investigations",
            "n_failed_treatments",
        ):
            if features.get(key) is not None:
                facts[key] = features[key]

        spec = rules().symptoms.get(latest.anchor_symptom or "", {})
        label = (spec.get("label") or {}).get("en")
        if label:
            facts["symptom_being_tracked"] = label

        if audience != "patient":
            facts["tier"] = latest.tier
            facts["ladder"] = latest.ladder_code
            if latest.model_probability is not None:
                facts["model_probability"] = round(latest.model_probability, 4)

    try:
        state = build_state(db, patient_id, date.today())
        facts["red_flag_present"] = has_red_flag(state, rules())
    except Exception:
        pass

    return facts, [prof.name] if prof.name else []


def _age(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
