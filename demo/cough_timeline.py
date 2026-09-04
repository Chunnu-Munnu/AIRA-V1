"""
"If a user has a continuous cough, will it be flagged, and how long does it
take?"

There is no single answer, and a system that gave one would be wrong. The same
cough, for the same number of days, in two different people, is two different
clinical situations. This script proves that by running the real engine over
the same symptom for two people, day by day.

    python demo/cough_timeline.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import assess, load_ruleset  # noqa: E402
from engine.models import (  # noqa: E402
    Episode,
    PatientState,
    Person,
    SeverityPoint,
    SymptomRecord,
)

ONSET = date(2026, 1, 1)
CHECKPOINTS = [1, 7, 13, 14, 20, 21, 30, 45, 60, 85, 120]


def low_risk_state(day: int) -> PatientState:
    """Lakshmi, 34, never smoked, nothing else wrong."""
    as_of = ONSET + timedelta(days=day)
    return PatientState(
        person=Person(age=34, sex="female", risk_factors=set()),
        symptoms=[
            SymptomRecord(
                code="cough",
                onset_date=ONSET,
                severity_log=[SeverityPoint(ONSET, 3), SeverityPoint(as_of, 3)],
            )
        ],
        episodes=[],
    )


def high_risk_state(day: int) -> PatientState:
    """Ramesh, 52, smoker and tobacco chewer.

    Weight loss appears on day 30. He is treated for TB on day 40 and again on
    day 65, and neither course works. No chest X-ray is ever ordered - which
    is exactly the real-world pattern this project exists to interrupt.
    """
    as_of = ONSET + timedelta(days=day)

    symptoms = [
        SymptomRecord(
            code="cough",
            onset_date=ONSET,
            severity_log=[
                SeverityPoint(ONSET, 4),
                SeverityPoint(as_of, 4 + min(3, day // 30)),
            ],
        )
    ]
    if day >= 30:
        symptoms.append(SymptomRecord(code="weight_loss", onset_date=ONSET + timedelta(days=30)))

    episodes: list[Episode] = []
    if day >= 40:
        episodes.append(
            Episode(ONSET + timedelta(days=40), "respiratory", "phc", "att", "none", "unchanged")
        )
    if day >= 65:
        episodes.append(
            Episode(
                ONSET + timedelta(days=65), "respiratory", "private_clinic", "att", "none", "unchanged"
            )
        )

    return PatientState(
        person=Person(
            age=52, sex="male", risk_factors={"tobacco_smoking", "tobacco_chewing"}
        ),
        symptoms=symptoms,
        episodes=episodes,
    )


def run(label: str, builder) -> None:
    rules = load_ruleset("rules")
    print("=" * 96)
    print(f"  {label}")
    print("=" * 96)
    print(f"  {'DAY':>4} | {'TIER':<8} | {'LADDER':<24} | WHAT CHANGED")
    print("  " + "-" * 92)

    previous = None
    for day in CHECKPOINTS:
        state = builder(day)
        a = assess(state, as_of=ONSET + timedelta(days=day), rules=rules)

        current = (a.tier, a.ladder_code)
        marker = "  " if current == previous else "->"

        newest = ""
        if a.reasons:
            # Show the highest-priority reason: red flag, then combination,
            # then milestone, then ladder.
            order = {"red_flag": 0, "combination": 1, "milestone": 2, "context": 3, "ladder": 4}
            top = sorted(a.reasons, key=lambda r: order.get(r.kind, 9))[0]
            newest = f"{top.rule_id}"

        print(f"{marker}{day:>4} | {a.tier:<8} | L{a.ladder_level} {a.ladder_code:<21} | {newest}")
        previous = current
    print()


if __name__ == "__main__":
    run("LAKSHMI, 34, never smoked, cough only", low_risk_state)
    run("RAMESH, 52, smoker + tobacco chewer, cough -> weight loss -> two failed TB courses", high_risk_state)
