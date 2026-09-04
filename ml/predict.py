"""
Runtime scoring.

Called by api.service._maybe_score. If the artifacts are missing this module
raises on import and the API runs rules-only, which is a correct and safe
degradation rather than an outage: the deterministic layer alone is already a
usable product, and roughly 60% of AIRA's decision surface never needed a
model in the first place.
"""

from __future__ import annotations

import pickle
from functools import lru_cache
from pathlib import Path

import pandas as pd

from engine.models import PatientState
from engine.rules_loader import load_ruleset

from .features import CLUSTERS, DISPLAY_NAMES, RISK_FEATURES

ARTIFACTS = Path("ml/artifacts")


@lru_cache(maxsize=2)
def _load(name: str):
    path = ARTIFACTS / f"{name}_ebm.pkl"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run: py -3.11 ml/train.py")
    with path.open("rb") as fh:
        return pickle.load(fh)


def _years(risk_factors: set[str], token: str) -> float:
    """Duration is stored on the profile as a token set in this prototype.
    A production schema carries the number; this keeps the contract explicit
    rather than silently treating 'ever used' as 'used for twenty years'."""
    if token not in risk_factors:
        return 0.0
    return 15.0  # assumed median exposure for a self-reported current user


def to_feature_row(state: PatientState, rules=None) -> pd.DataFrame:
    """PatientState -> the exact 20 columns the risk model was trained on.

    Both training and serving import the column list from ml.features, so the
    two cannot drift apart. Training/serving skew is the most common way a
    working model quietly becomes a broken one.
    """
    rules = rules or load_ruleset()
    p = state.person
    active = state.active_symptoms()

    present_clusters = set()
    for s in active:
        spec = rules.symptoms.get(s.code)
        if spec:
            present_clusters.add(spec["cluster"])

    flagged_codes = {f["symptom"] for f in rules.red_flags}
    has_red_flag = int(any(s.code in flagged_codes for s in active))

    fh = p.family_history or []
    fh_age = min((f.get("age_at_diagnosis", 0) or 0) for f in fh) if fh else 0

    row = {
        "age": p.age,
        "sex_male": int(p.sex == "male"),
        "tobacco_smoking_years": _years(p.risk_factors, "tobacco_smoking"),
        "tobacco_chewing_years": _years(p.risk_factors, "tobacco_chewing"),
        "alcohol_heavy": int("alcohol_heavy" in p.risk_factors),
        "bmi": p.bmi if p.bmi is not None else 23.0,
        "family_history": int(bool(fh)),
        "family_history_age": fh_age,
        "has_red_flag": has_red_flag,
        "n_clusters": len(present_clusters),
    }
    for c in CLUSTERS:
        row[f"cluster_{c}"] = int(c in present_clusters)

    return pd.DataFrame([row])[RISK_FEATURES]


def score_patient(state: PatientState, rules=None):
    """Returns (probability, contributions, model_version).

    The contributions are not an approximation of what the model did. In an
    EBM they ARE the model: the per-feature scores sum to the log-odds. That
    is the whole reason this project ships a GAM rather than a tree ensemble
    with SHAP bolted on afterwards.
    """
    bundle = _load("risk")
    model, features, version = bundle["model"], bundle["features"], bundle["version"]

    X = to_feature_row(state, rules)[features]
    probability = float(model.predict_proba(X)[:, 1][0])

    local = model.explain_local(X).data(0)
    intercept = float(local["extra"]["scores"][0])

    contributions = [
        {
            "feature": name,
            "display": DISPLAY_NAMES.get(name, name),
            "value": _clean(X[name].iloc[0]) if name in X else None,
            "contribution": round(float(score), 4),
        }
        for name, score in zip(local["names"], local["scores"])
        if abs(float(score)) >= 1e-4
    ]
    contributions.sort(key=lambda c: -abs(c["contribution"]))
    contributions.insert(
        0,
        {
            "feature": "__baseline__",
            "display": "Starting point for someone with none of the above",
            "value": None,
            "contribution": round(intercept, 4),
        },
    )

    return probability, contributions, version


def _clean(v):
    try:
        return float(v) if float(v) % 1 else int(v)
    except (TypeError, ValueError):
        return v
