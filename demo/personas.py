"""
The four demo patients.

These are hard-coded on purpose. You cannot enter nine months of symptom
history live on a stage in front of judges, and a demo that depends on typing
is a demo that fails. Three of these four are reconstructed from patterns that
NGOs described to us directly in field interviews.
"""

from __future__ import annotations

from datetime import date, timedelta

from engine.models import Episode, PatientState, Person, SeverityPoint, SymptomRecord

TODAY = date(2026, 9, 3)


def _d(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Sunita, 42, Kolar district, Karnataka
#    Nine months of "acidity". Three visits. Three antacids. Zero tests.
#    This is the deck's opening scenario.
# ─────────────────────────────────────────────────────────────────────────────
def sunita() -> PatientState:
    return PatientState(
        person=Person(
            age=42,
            sex="female",
            risk_factors={"tobacco_chewing"},
            family_history=[],
            bmi=21.4,
            language="kn",
        ),
        symptoms=[
            SymptomRecord(
                code="dyspepsia",
                onset_date=_d(190),
                severity_log=[
                    SeverityPoint(_d(190), 3),
                    SeverityPoint(_d(120), 4),
                    SeverityPoint(_d(60), 6),
                    SeverityPoint(_d(5), 7),
                ],
            ),
            SymptomRecord(code="weight_loss", onset_date=_d(70)),
        ],
        episodes=[
            Episode(_d(185), "upper_gi", "private_clinic", "antacid", "none", "unchanged"),
            Episode(_d(110), "upper_gi", "phc", "antacid", "none", "unchanged"),
            Episode(_d(40), "upper_gi", "private_clinic", "antacid", "none", "unchanged"),
        ],
        missed_checkbacks=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Ramesh, 52, tobacco user
#    Chronic cough treated twice as tuberculosis. No chest X-ray, ever.
#    In India this is the single most lethal misdiagnosis pattern in lung
#    cancer: empirical anti-TB therapy, no imaging, presentation at stage IV.
# ─────────────────────────────────────────────────────────────────────────────
def ramesh() -> PatientState:
    return PatientState(
        person=Person(
            age=52,
            sex="male",
            risk_factors={"tobacco_smoking", "tobacco_chewing", "alcohol_heavy"},
            family_history=[],
            bmi=19.1,
            language="hi",
        ),
        symptoms=[
            SymptomRecord(
                code="cough",
                onset_date=_d(85),
                severity_log=[
                    SeverityPoint(_d(85), 4),
                    SeverityPoint(_d(50), 5),
                    SeverityPoint(_d(10), 7),
                ],
            ),
            SymptomRecord(code="weight_loss", onset_date=_d(55)),
            SymptomRecord(code="fatigue", onset_date=_d(30)),
        ],
        episodes=[
            Episode(_d(78), "respiratory", "phc", "antibiotic", "none", "unchanged"),
            Episode(_d(60), "respiratory", "phc", "att", "none", "unchanged"),
            Episode(_d(20), "respiratory", "private_clinic", "att", "none", "unchanged"),
        ],
        missed_checkbacks=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Lakshmi, 34, no risk factors
#    Sixteen days of cough. This persona exists to prove AIRA does NOT
#    over-alarm. If every cough came back red, the tool would be useless and
#    every ASHA would stop opening it within a week.
# ─────────────────────────────────────────────────────────────────────────────
def lakshmi() -> PatientState:
    return PatientState(
        person=Person(
            age=34,
            sex="female",
            risk_factors=set(),
            family_history=[],
            bmi=23.0,
            language="kn",
        ),
        symptoms=[
            SymptomRecord(
                code="cough",
                onset_date=_d(16),
                severity_log=[SeverityPoint(_d(16), 3), SeverityPoint(_d(2), 3)],
            )
        ],
        episodes=[],
        missed_checkbacks=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Arun, 7
#    Forty days of intermittent fever. Three courses of antibiotics. No full
#    blood count. Reconstructed directly from what CanKids KidsCan described
#    to us: repeated anti-typhoid and anti-malarial treatment with a CBC never
#    performed.
# ─────────────────────────────────────────────────────────────────────────────
def arun() -> PatientState:
    return PatientState(
        person=Person(
            age=7,
            sex="male",
            risk_factors=set(),
            family_history=[],
            bmi=14.2,
            language="hi",
        ),
        symptoms=[
            SymptomRecord(
                code="fever_prolonged",
                onset_date=_d(40),
                severity_log=[
                    SeverityPoint(_d(40), 5),
                    SeverityPoint(_d(20), 5),
                    SeverityPoint(_d(3), 7),
                ],
            ),
            SymptomRecord(code="pallor", onset_date=_d(25)),
            SymptomRecord(code="bone_pain", onset_date=_d(12)),
        ],
        episodes=[
            Episode(_d(36), "systemic", "chemist", "antibiotic", "none", "unchanged"),
            Episode(_d(24), "systemic", "phc", "antibiotic", "none", "unchanged"),
            Episode(_d(9), "systemic", "private_clinic", "antibiotic", "none", "unchanged"),
        ],
        missed_checkbacks=0,
    )


ALL = {
    "sunita": ("Sunita, 42, Kolar - nine months of acidity", sunita),
    "ramesh": ("Ramesh, 52, smoker - cough treated twice as TB", ramesh),
    "lakshmi": ("Lakshmi, 34, no risk factors - 16 days of cough", lakshmi),
    "arun": ("Arun, 7 - forty days of fever, three antibiotic courses", arun),
}
