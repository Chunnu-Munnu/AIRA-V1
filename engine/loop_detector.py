"""
The Loop Detector.

This is AIRA's original contribution and the thing no competing product does.

It does not ask "does this person have cancer". It asks a question that only
becomes answerable when you hold the whole history in one place:

    Is this person stuck in a loop that no individual doctor can see,
    because each doctor only ever sees one visit?

A single clinician prescribing an antacid for indigestion is making a correct
probabilistic judgement - the base rate of malignancy in that presentation is
genuinely tiny. The failure is not the first benign explanation. It is the
second and the third, offered by people who never learn that the first one
failed. This module makes that failure visible.
"""

from __future__ import annotations

import operator
from datetime import date
from typing import Any, Callable

from .models import Episode, PatientState, Reason, SymptomRecord
from .rules_loader import Ruleset

OPS: dict[str, Callable[[Any, Any], bool]] = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


# ─────────────────────────────────────────────────────────────────────────────
# Feature extraction
#
# These seven numbers are the entire input to the trajectory model. We do NOT
# feed raw visit sequences to a recurrent network: with 2-6 irregularly spaced
# episodes there is nothing for an LSTM to learn that these features do not
# already state explicitly, and the features can be printed on a card that a
# doctor reads in twenty seconds. See TECHNICAL.md, "why not an LSTM".
# ─────────────────────────────────────────────────────────────────────────────


def _severity_slope(sym: SymptomRecord) -> float:
    """Least-squares slope of severity over time, expressed per 30 days.

    Positive means getting worse. Returns 0.0 when there are fewer than two
    readings, because 'we do not know' must not look like 'it is improving'.
    """
    pts = sorted(sym.severity_log, key=lambda p: p.on)
    if len(pts) < 2:
        return 0.0

    t0 = pts[0].on
    xs = [(p.on - t0).days for p in pts]
    ys = [float(p.score) for p in pts]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    slope_per_day = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    return round(slope_per_day * 30.0, 3)


def episodes_for_cluster(state: PatientState, cluster_id: str) -> list[Episode]:
    return [e for e in state.episodes if e.cluster_id == cluster_id]


def extract_features(
    state: PatientState,
    anchor: SymptomRecord,
    rules: Ruleset,
    as_of: date,
) -> dict:
    """Build the seven-number trajectory vector for one anchor symptom."""
    spec = rules.symptom(anchor.code)
    cluster = spec["cluster"]
    safe_window = rules.safe_window(anchor.code)
    days_elapsed = anchor.days_elapsed(as_of)

    eps = episodes_for_cluster(state, cluster)
    eps = [e for e in eps if e.encounter_date >= anchor.onset_date]

    # A safe window of 0 means "red flag, do not wait". Guard the division but
    # keep the ratio meaningful: 1 day past a 0-day window is already breached.
    denom = max(safe_window, 1)

    later_symptoms = [
        s
        for s in state.symptoms
        if s.code != anchor.code and s.onset_date > anchor.onset_date
    ]

    return {
        "anchor_symptom": anchor.code,
        "cluster": cluster,
        "days_elapsed": days_elapsed,
        "safe_window_days": safe_window,
        "duration_ratio": round(days_elapsed / denom, 3),
        "n_episodes": len(eps),
        "n_investigations": sum(1 for e in eps if e.has_investigation()),
        "n_failed_treatments": sum(1 for e in eps if e.is_failed_treatment()),
        "severity_slope": _severity_slope(anchor),
        "breadth_creep": len(later_symptoms),
        "provider_switches": len({e.provider_type for e in eps if e.provider_type}),
        "missed_checkbacks": state.missed_checkbacks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ladder evaluation
#
# The conditions live in rules/ladder.json, not here. This function is a small
# interpreter for that schema. Changing when L2 fires is a JSON edit, not a
# code change, and it bumps ruleset_version so every past decision made under
# the old thresholds stays identifiable.
# ─────────────────────────────────────────────────────────────────────────────


def _check(cond: dict, ctx: dict) -> bool:
    if cond.get("always"):
        return True
    field = cond["field"]
    if field not in ctx:
        return False
    op = OPS.get(cond["op"])
    if op is None:
        raise ValueError(f"unknown operator in ladder rule: {cond['op']}")
    return bool(op(ctx[field], cond["value"]))


def _conditions_met(conditions: dict, ctx: dict) -> bool:
    if conditions.get("always"):
        return True
    all_ok = all(_check(c, ctx) for c in conditions.get("all", []))
    any_conds = conditions.get("any", [])
    any_ok = True if not any_conds else any(_check(c, ctx) for c in any_conds)
    return all_ok and any_ok


def _fmt(template: str, ctx: dict) -> str:
    """Format a rule message with the feature values, leaving unknown
    placeholders visible rather than crashing."""
    out = template
    for key, value in ctx.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def evaluate_ladder(
    features: dict,
    rules: Ruleset,
    risk_tier: str = "LOW",
    new_red_flag_since_onset: bool = False,
    lang: str = "en",
) -> tuple[int, str, Reason]:
    """Return (level, code, reason).

    Levels 0-2 are evaluated first to establish a base. Level 3 is then
    evaluated with that base in scope, because L3 is defined as 'L2 plus
    something is actively getting worse'.
    """
    ctx = dict(features)
    ctx["risk_tier"] = risk_tier
    ctx["new_red_flag_since_onset"] = new_red_flag_since_onset

    base_level = 0
    for lvl in rules.levels:
        if lvl["level"] > 2:
            continue
        if _conditions_met(lvl["conditions"], ctx):
            base_level = max(base_level, lvl["level"])

    ctx["ladder_level_base"] = base_level

    final_level = base_level
    l3 = rules.level(3)
    if _conditions_met(l3["conditions"], ctx):
        final_level = 3

    lvl = rules.level(final_level)

    # Name the specific reason L3 fired, so the clinician message is concrete.
    escalation_reason = "no additional escalation trigger"
    if final_level == 3:
        triggers = []
        if ctx.get("severity_slope", 0) > 0:
            triggers.append(f"severity rising ({ctx['severity_slope']}/30d)")
        if ctx.get("new_red_flag_since_onset"):
            triggers.append("a new red-flag symptom has appeared")
        if ctx.get("risk_tier") == "HIGH":
            triggers.append("baseline risk model in HIGH tier")
        if ctx.get("breadth_creep", 0) >= 2:
            triggers.append(f"{ctx['breadth_creep']} new symptoms since onset")
        escalation_reason = "; ".join(triggers) or escalation_reason
    ctx["escalation_reason"] = escalation_reason

    spec = rules.symptom(features["anchor_symptom"])
    ctx["expected_investigations"] = ", ".join(spec.get("expected_investigations", []))

    reason = Reason(
        kind="ladder",
        rule_id=lvl["code"],
        message_clinician=_fmt(lvl["clinician_message"], ctx),
        message_patient=_fmt(
            lvl["patient_message"].get(lang) or lvl["patient_message"].get("en", ""), ctx
        ),
        citation={"source": "rules/ladder.json", "level": lvl["level"]},
    )
    return final_level, lvl["code"], reason


def evaluate_contextual_flags(
    features: dict, rules: Ruleset, has_red_flag: bool, lang: str = "en"
) -> list[Reason]:
    """The three cross-cutting patterns that are not tied to one symptom."""
    out: list[Reason] = []
    ctx = dict(features)

    for cf in rules.contextual_flags:
        fired = False
        if cf["id"] == "CF_INVESTIGATION_GAP":
            fired = has_red_flag and features["n_investigations"] == 0 and features["n_episodes"] >= 1
        elif cf["id"] == "CF_TREATMENT_REFRACTORY":
            fired = features["n_failed_treatments"] >= 2 and features["duration_ratio"] > 1.0
        elif cf["id"] == "CF_NEVER_SEEN":
            fired = features["duration_ratio"] > 2.0 and features["n_episodes"] == 0
        elif cf["id"] == "CF_MISSED_CHECKBACKS":
            fired = features.get("missed_checkbacks", 0) >= 2

        if fired:
            pm = cf.get("patient_message", {})
            out.append(
                Reason(
                    kind="context",
                    rule_id=cf["id"],
                    message_clinician=_fmt(cf["clinician_message"], ctx),
                    message_patient=_fmt(pm.get(lang) or pm.get("en", ""), ctx) if pm else "",
                    citation=cf.get("citation", {}),
                )
            )
    return out
