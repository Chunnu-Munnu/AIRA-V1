"""
The gate for Block 1.

These tests are not about code coverage. Each one pins down a clinical or
safety property that AIRA claims on stage. If one of these fails, a sentence
in the pitch has become a lie.

    py -3.11 -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.personas import TODAY, arun, lakshmi, ramesh, sunita  # noqa: E402
from engine import assess, load_ruleset  # noqa: E402
from engine.models import Episode, PatientState, Person, SeverityPoint, SymptomRecord  # noqa: E402

RULES = load_ruleset("rules")
ONSET = date(2026, 1, 1)


def at(day: int) -> date:
    return ONSET + timedelta(days=day)


# ─────────────────────────────────────────────────────────────────────────────
# Ruleset integrity
# ─────────────────────────────────────────────────────────────────────────────


def test_ruleset_loads_and_versions_match():
    assert RULES.version == "1.0.0"
    assert len(RULES.symptoms) >= 40
    assert len(RULES.red_flags) >= 10
    assert len(RULES.levels) == 4


def test_every_symptom_has_a_citation():
    """A rule without a source is an opinion. AIRA does not ship opinions."""
    missing = [c for c, s in RULES.symptoms.items() if not s.get("citation", {}).get("source")]
    assert missing == [], f"symptoms with no citation: {missing}"


def test_every_symptom_has_expected_investigations():
    """investigation_gap - the core signal - is undefined without this."""
    missing = [c for c, s in RULES.symptoms.items() if not s.get("expected_investigations")]
    assert missing == [], f"symptoms with no expected investigations: {missing}"


def test_every_symptom_has_three_languages():
    incomplete = [
        c
        for c, s in RULES.symptoms.items()
        if not all(k in s.get("label", {}) for k in ("en", "hi", "kn"))
    ]
    assert incomplete == [], f"symptoms missing a translation: {incomplete}"


def test_no_forbidden_features_anywhere_in_the_rules():
    """Caste, religion, income and region must not exist in the decision
    surface at all - not as inputs, not as modifiers, not as text."""
    import json

    blob = json.dumps(
        [RULES.symptoms_doc, RULES.redflags_doc, RULES.ladder_doc, RULES.screening_doc]
    ).lower()
    for forbidden in ("caste", "religion", "income_group", '"region"'):
        assert forbidden not in blob, f"forbidden feature present in ruleset: {forbidden}"


# ─────────────────────────────────────────────────────────────────────────────
# The cough question, pinned down
# ─────────────────────────────────────────────────────────────────────────────


def cough_only(age: int, day: int, risk: set[str] | None = None) -> PatientState:
    return PatientState(
        person=Person(age=age, sex="female", risk_factors=risk or set()),
        symptoms=[
            SymptomRecord(
                code="cough",
                onset_date=ONSET,
                severity_log=[SeverityPoint(ONSET, 3), SeverityPoint(at(day), 3)],
            )
        ],
        episodes=[],
    )


def test_new_cough_in_a_young_low_risk_person_is_not_alarming():
    """If a five-day cough came back red, every ASHA would uninstall AIRA in
    a week. Not alarming is a feature, and it is tested."""
    a = assess(cough_only(34, 5), as_of=at(5), rules=RULES)
    assert a.tier == "LOW"
    assert a.ladder_level == 0


def test_cough_crosses_indias_tb_threshold_at_day_14_not_a_cancer_threshold():
    """India screens cough at 14 days for TB, not for cancer. AIRA follows the
    Indian pathway first. The word 'cancer' must not appear."""
    a = assess(cough_only(34, 14), as_of=at(14), rules=RULES)
    assert a.tier == "MODERATE"
    rule_ids = [r.rule_id for r in a.reasons]
    assert "cough@day14" in rule_ids
    joined = " ".join(a.patient_lines()).lower()
    assert "cancer" not in joined


def test_same_cough_same_day_higher_risk_person_reaches_high():
    """Identical symptom, identical duration, different person, different
    answer. This is the whole argument for personalised triage."""
    low = assess(cough_only(34, 14), as_of=at(14), rules=RULES)
    high = assess(
        cough_only(52, 14, risk={"tobacco_smoking"}), as_of=at(14), rules=RULES
    )
    assert low.tier == "MODERATE"
    assert high.tier == "HIGH"
    assert "NG12_LUNG_EVER_SMOKED" in [r.rule_id for r in high.reasons]


def test_untreated_long_cough_triggers_patient_interval_outreach():
    """Never seen a doctor, well past the window: this is a patient-interval
    delay and needs outreach, not referral."""
    a = assess(cough_only(34, 60), as_of=at(60), rules=RULES)
    assert "CF_NEVER_SEEN" in [r.rule_id for r in a.reasons]


# ─────────────────────────────────────────────────────────────────────────────
# The Loop Detector ladder
# ─────────────────────────────────────────────────────────────────────────────


def test_two_visits_zero_investigations_is_l1():
    state = PatientState(
        person=Person(age=45, sex="male", risk_factors=set()),
        symptoms=[SymptomRecord(code="dyspepsia", onset_date=ONSET)],
        episodes=[
            Episode(at(10), "upper_gi", "phc", "antacid", "none", "resolved"),
            Episode(at(20), "upper_gi", "phc", "antacid", "none", "resolved"),
        ],
    )
    a = assess(state, as_of=at(25), rules=RULES)
    assert a.ladder_level == 1
    assert a.ladder_code == "L1_REPEAT_PRESENTATION"


def test_an_investigation_clears_l1():
    """L1 means 'nobody has tested anything'. One test, and that is no longer
    true. AIRA must not nag a clinician who already did the right thing."""
    state = PatientState(
        person=Person(age=45, sex="male", risk_factors=set()),
        symptoms=[SymptomRecord(code="dyspepsia", onset_date=ONSET)],
        episodes=[
            Episode(at(10), "upper_gi", "phc", "antacid", "none", "resolved"),
            Episode(at(20), "upper_gi", "phc", "antacid", "upper_gi_endoscopy", "resolved"),
        ],
    )
    a = assess(state, as_of=at(25), rules=RULES)
    assert a.ladder_level == 0


def test_two_failed_treatments_past_the_window_is_at_least_l2():
    state = PatientState(
        person=Person(age=45, sex="male", risk_factors=set()),
        symptoms=[SymptomRecord(code="dyspepsia", onset_date=ONSET)],
        episodes=[
            Episode(at(10), "upper_gi", "phc", "antacid", "none", "unchanged"),
            Episode(at(40), "upper_gi", "phc", "antacid", "none", "unchanged"),
        ],
    )
    a = assess(state, as_of=at(60), rules=RULES)
    assert a.ladder_level >= 2
    assert a.tier == "HIGH"
    assert "CF_TREATMENT_REFRACTORY" in [r.rule_id for r in a.reasons]


def test_ladder_never_names_a_cancer_to_the_patient():
    """AIRA reports a pattern, never a disease. Every ladder message in every
    language is checked."""
    banned = ["cancer", "कैंसर", "ಕ್ಯಾನ್ಸರ್", "tumour", "malignant"]
    for lvl in RULES.levels:
        for _, text in lvl["patient_message"].items():
            low = text.lower()
            for word in banned:
                assert word.lower() not in low, f"{lvl['code']} says '{word}'"


# ─────────────────────────────────────────────────────────────────────────────
# Safety: rules decide, models rank
# ─────────────────────────────────────────────────────────────────────────────


def test_a_red_flag_beats_a_confident_low_model_score():
    """The most important test in the repository. A red flag sets a floor
    that no model output can go below."""
    state = PatientState(
        person=Person(age=60, sex="male", risk_factors=set()),
        symptoms=[SymptomRecord(code="dysphagia", onset_date=ONSET)],
        episodes=[],
    )
    a = assess(state, as_of=at(1), rules=RULES, model_probability=0.0001)
    assert a.tier == "HIGH"
    assert "RF_DYSPHAGIA" in [r.rule_id for r in a.reasons]


def test_a_model_may_raise_a_tier():
    state = cough_only(34, 3)
    plain = assess(state, as_of=at(3), rules=RULES)
    boosted = assess(state, as_of=at(3), rules=RULES, model_probability=0.09)
    assert plain.tier == "LOW"
    assert boosted.tier == "HIGH"


def test_reported_probability_is_capped():
    """AIRA is a triage aid. Anything claiming near-certainty is a bug."""
    state = cough_only(34, 3)
    a = assess(state, as_of=at(3), rules=RULES, model_probability=0.97)
    assert a.model_probability == pytest.approx(0.40)


def test_every_conclusion_carries_at_least_one_traceable_reason():
    for builder in (sunita, ramesh, lakshmi, arun):
        a = assess(builder(), as_of=TODAY, rules=RULES)
        assert a.reasons, f"{builder.__name__} produced a verdict with no reason"
        assert a.ruleset_version == RULES.version


# ─────────────────────────────────────────────────────────────────────────────
# The four demo personas - these must hold on stage
# ─────────────────────────────────────────────────────────────────────────────


def test_sunita_escalates_with_zero_investigations():
    a = assess(sunita(), as_of=TODAY, rules=RULES)
    assert a.tier == "HIGH"
    assert a.ladder_level == 3
    assert a.features["n_investigations"] == 0
    assert a.features["n_failed_treatments"] == 3
    assert "upper_gi_endoscopy" in a.recommended_investigations


def test_ramesh_the_tb_misdiagnosis_pattern():
    a = assess(ramesh(), as_of=TODAY, rules=RULES)
    assert a.tier == "HIGH"
    assert a.ladder_level == 3
    assert a.features["duration_ratio"] > 4.0
    assert "chest_xray" in a.recommended_investigations


def test_arun_paediatric_fever_without_a_blood_count():
    a = assess(arun(), as_of=TODAY, rules=RULES)
    assert a.tier == "HIGH"
    assert a.features["n_investigations"] == 0
    assert "cbc" in a.recommended_investigations


def test_lakshmi_is_not_over_alarmed():
    """The counterexample. If this one goes HIGH, the tool is crying wolf."""
    a = assess(lakshmi(), as_of=TODAY, rules=RULES)
    assert a.tier == "MODERATE"
    assert a.ladder_level == 0


# ─────────────────────────────────────────────────────────────────────────────
# Screening is a separate track
# ─────────────────────────────────────────────────────────────────────────────


def test_screening_is_offered_but_never_as_an_alert():
    a = assess(lakshmi(), as_of=TODAY, rules=RULES)
    assert any(s["id"] == "SCR_CERVICAL" for s in a.screening_available)
    for s in a.screening_available:
        assert s["cost_to_patient"] == 0
        assert "overdue" not in s["message"].lower()


def test_tobacco_use_shortens_the_oral_screening_interval():
    user = PatientState(
        person=Person(age=40, sex="male", risk_factors={"tobacco_chewing"}),
        symptoms=[],
    )
    clean = PatientState(person=Person(age=40, sex="male", risk_factors=set()), symptoms=[])
    a_user = assess(user, as_of=TODAY, rules=RULES)
    a_clean = assess(clean, as_of=TODAY, rules=RULES)

    oral_user = next(s for s in a_user.screening_available if s["id"] == "SCR_ORAL")
    oral_clean = next(s for s in a_clean.screening_available if s["id"] == "SCR_ORAL")
    assert oral_user["interval_months"] == 12
    assert oral_clean["interval_months"] == 60
    assert oral_user["interval_shortened_by_risk"] is True


def test_male_patients_are_not_offered_cervical_screening():
    male = PatientState(person=Person(age=40, sex="male", risk_factors=set()), symptoms=[])
    a = assess(male, as_of=TODAY, rules=RULES)
    ids = {s["id"] for s in a.screening_available}
    assert "SCR_CERVICAL" not in ids
    assert "SCR_BREAST" not in ids
