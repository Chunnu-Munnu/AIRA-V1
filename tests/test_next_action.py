"""
Next Action engine - the care-state machine.

Offline and pure: these exercise engine.next_action.derive() directly, no DB,
no network. The properties under test are the ones the spec is strict about -
AIRA never diagnoses, never auto-ticks a box the patient must own, and never
lets a flagged pattern sit without a concrete next step.
"""

from __future__ import annotations

from datetime import date, timedelta

from engine import next_action as na


def _plan(**kw):
    base = dict(
        assessment=None,
        episodes=[],
        released_notes=[],
        documents=[],
        care_responses=[],
        consent_active=False,
        today=date(2026, 9, 4),
    )
    base.update(kw)
    return na.derive(**base)


def test_low_risk_patient_gets_no_urgent_checklist():
    plan = _plan(assessment={"tier": "LOW", "ladder_level": 0})
    assert plan.state == na.MONITORING
    assert plan.tasks == []


def test_a_flagged_pattern_always_produces_a_next_step():
    plan = _plan(assessment={"tier": "HIGH", "ladder_level": 2})
    assert plan.state == na.NEEDS_CARE
    assert plan.tasks, "a flagged patient must never be left without a next step"
    assert plan.primary_cta == "find_care"


def test_the_headline_never_names_a_disease():
    for tier, ladder in (("HIGH", 3), ("MODERATE", 1), ("LOW", 0)):
        plan = _plan(assessment={"tier": tier, "ladder_level": ladder})
        blob = " ".join(
            [plan.headline["en"], plan.subhead["en"], *[t.labels["en"] for t in plan.tasks]]
        ).lower()
        for banned in ("cancer", "tumour", "tumor", "malignan", "you have"):
            assert banned not in blob, f"{banned!r} leaked into {tier} copy"


def test_patient_owned_steps_are_never_auto_completed():
    """Every task the patient must physically do carries no auto_complete_on -
    the only tasks that tick themselves are the ones a hard record proves."""
    plan = _plan(assessment={"tier": "HIGH", "ladder_level": 2})
    owned = {"review_flag", "gather_reports", "book_evaluation"}
    for task in plan.tasks:
        if task.key in owned:
            assert task.auto_complete_on is None


def test_a_released_plan_moves_the_state_forward():
    plan = _plan(
        assessment={"tier": "HIGH", "ladder_level": 2},
        released_notes=[{"id": "n1", "released_on": date(2026, 9, 1), "follow_up_days": 14}],
    )
    assert plan.state == na.PLAN_RECEIVED
    assert any(t.key == "return_followup" and t.due_date == date(2026, 9, 15) for t in plan.tasks)


def test_follow_up_window_opens_near_the_due_date():
    note = [{"id": "n1", "released_on": date(2026, 8, 20), "follow_up_days": 14}]  # due 09-03
    plan = _plan(assessment={"tier": "HIGH", "ladder_level": 2}, released_notes=note)
    assert plan.state == na.FOLLOW_UP_DUE
    assert plan.primary_cta == "record_response"


def test_a_no_response_escalates():
    note = [{"id": "n1", "released_on": date(2026, 8, 20), "follow_up_days": 14}]
    plan = _plan(
        assessment={"tier": "HIGH", "ladder_level": 2},
        released_notes=note,
        care_responses=[{"feeling": "same", "helped": "no", "created_on": date(2026, 9, 3)}],
    )
    assert plan.escalated is True


def test_an_unreviewed_report_surfaces_as_its_own_task():
    plan = _plan(
        assessment={"tier": "HIGH", "ladder_level": 2},
        documents=[{"id": "d1", "created_on": date(2026, 9, 2), "reviewed_at": None}],
    )
    assert any(t.key == "get_report_reviewed" for t in plan.tasks)


def test_the_loop_completes_only_when_every_step_is_recorded():
    plan = _plan(
        assessment={"tier": "HIGH", "ladder_level": 2},
        released_notes=[{"id": "n1", "released_on": date(2026, 8, 20), "follow_up_days": 14}],
        episodes=[{"investigation_ordered": "cbc", "source": "clinician"}],
        documents=[{"id": "d1", "created_on": date(2026, 9, 1), "reviewed_at": "2026-09-02"}],
        care_responses=[{"feeling": "better", "helped": "yes", "created_on": date(2026, 9, 3)}],
    )
    assert plan.state == na.LOOP_COMPLETE
