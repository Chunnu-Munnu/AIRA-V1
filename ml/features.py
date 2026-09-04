"""
The feature contract.

One file, imported by the generator, both trainers and the runtime scorer, so
that training-time and serving-time features cannot silently drift apart.
Training/serving skew is the most common way a working model quietly becomes
a broken one, and it is entirely preventable by never writing the column list
down twice.
"""

from __future__ import annotations

CLUSTERS = [
    "respiratory",
    "oral",
    "head_neck",
    "upper_gi",
    "lower_gi",
    "breast",
    "gynae",
    "urological",
    "systemic",
    "skin",
]

# ── Model 1: case-finding risk ───────────────────────────────────────────────
RISK_FEATURES = [
    "age",
    "sex_male",
    "tobacco_smoking_years",
    "tobacco_chewing_years",
    "alcohol_heavy",
    "bmi",
    "family_history",
    "family_history_age",
    *[f"cluster_{c}" for c in CLUSTERS],
    "has_red_flag",
    "n_clusters",
]

# Monotonic constraints are a SAFETY property, not a performance tweak.
# Enforcing them in the model makes certain wrong behaviours structurally
# impossible rather than merely unlikely: AIRA cannot become less concerned
# because someone smoked for longer, or because a red flag appeared.
#   +1  risk must not decrease as this rises
#   -1  risk must not increase as this rises
#    0  unconstrained
RISK_MONOTONE = {
    "age": 1,
    "tobacco_smoking_years": 1,
    "tobacco_chewing_years": 1,
    "alcohol_heavy": 1,
    "family_history": 1,
    "has_red_flag": 1,
    "n_clusters": 1,
}

# ── Model 2: trajectory concern ──────────────────────────────────────────────
TRAJECTORY_FEATURES = [
    "duration_ratio",
    "n_episodes",
    "n_investigations",
    "n_failed_treatments",
    "severity_slope",
    "breadth_creep",
    "provider_switches",
]

TRAJECTORY_MONOTONE = {
    "duration_ratio": 1,
    "n_episodes": 1,
    "n_failed_treatments": 1,
    # The one negative constraint, and the most important line in this file.
    # More investigations must never raise concern. Without it a model trained
    # on data where sick people eventually get tested would learn that being
    # tested is dangerous, and would then penalise clinicians for doing the
    # right thing.
    "n_investigations": -1,
    "severity_slope": 1,
    "breadth_creep": 1,
    "provider_switches": 0,
}

TARGET = "cancer"


def monotone_list(features: list[str], constraints: dict[str, int]) -> list[int]:
    """EBM and XGBoost both want constraints positionally aligned to columns."""
    return [constraints.get(f, 0) for f in features]


# Human-readable names for the explanation panel. A contribution breakdown a
# patient cannot read is not an explanation.
DISPLAY_NAMES = {
    "age": "Age",
    "sex_male": "Sex",
    "tobacco_smoking_years": "Years of smoking",
    "tobacco_chewing_years": "Years of chewing tobacco",
    "alcohol_heavy": "Regular alcohol use",
    "bmi": "Body mass index",
    "family_history": "Family history of cancer",
    "family_history_age": "Age of relative at diagnosis",
    "has_red_flag": "A red-flag symptom is present",
    "n_clusters": "Number of body systems involved",
    "duration_ratio": "How long this has lasted, against what is expected",
    "n_episodes": "Doctor visits for this problem",
    "n_investigations": "Tests ever ordered",
    "n_failed_treatments": "Treatments that did not work",
    "severity_slope": "Whether it is getting worse",
    "breadth_creep": "New symptoms appearing",
    "provider_switches": "Different providers seen",
    **{f"cluster_{c}": f"Symptoms in: {c.replace('_', ' ')}" for c in CLUSTERS},
}
