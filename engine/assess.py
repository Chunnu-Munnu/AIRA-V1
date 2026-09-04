"""
The orchestrator. This function is where AIRA's central architectural
principle is enforced in code:

    RULES decide.   Models cannot overturn a rule.
    MODELS rank.    They may raise a tier, never lower one.
    THE LLM phrases. It never introduces a fact, a number or a tier.

If you read one file to understand this project, read this one.
"""

from __future__ import annotations

from datetime import date

from .loop_detector import (
    evaluate_contextual_flags,
    evaluate_ladder,
    extract_features,
)
from .models import Assessment, PatientState, Reason, SymptomRecord, Tier, higher_tier
from .rules_engine import (
    _applies,
    evaluate_combinations,
    evaluate_milestones,
    evaluate_red_flags,
    evaluate_screening,
    has_red_flag,
    next_checkback,
)
from .rules_loader import Ruleset, load_ruleset

# AIRA is a triage aid, not a diagnostic device. No output may claim
# near-certainty; anything above this is treated as a bug, not a finding.
MAX_REPORTED_PROBABILITY = 0.40


def _pick_anchor(
    state: PatientState, rules: Ruleset, as_of: date
) -> SymptomRecord | None:
    """The anchor is the symptom the trajectory is measured against.

    Red-flag symptoms win outright. Otherwise the symptom furthest past its
    own safe window wins, because that is the one the system has been most
    wrong about for longest.
    """
    active = [
        s
        for s in state.active_symptoms()
        if _applies(rules.symptom(s.code).get("applies", {}), state.person)
    ]
    if not active:
        return None

    flagged_codes = {
        f["symptom"]
        for f in rules.red_flags
        if _applies(f.get("conditions", {}), state.person)
    }

    def score(s: SymptomRecord) -> tuple[int, float]:
        window = max(rules.safe_window(s.code), 1)
        return (
            1 if s.code in flagged_codes else 0,
            s.days_elapsed(as_of) / window,
        )

    return max(active, key=score)


def assess(
    state: PatientState,
    as_of: date | None = None,
    rules: Ruleset | None = None,
    model_probability: float | None = None,
    model_contributions: list[dict] | None = None,
    model_version: str | None = None,
) -> Assessment:
    """Produce a full assessment for one patient at one moment in time."""
    as_of = as_of or date.today()
    rules = rules or load_ruleset()

    tier: Tier = "LOW"
    reasons: list[Reason] = []
    investigations: list[str] = []

    # ── 1. Deterministic layer ───────────────────────────────────────────
    for evaluator in (evaluate_red_flags, evaluate_milestones, evaluate_combinations):
        t, r, inv = evaluator(state, rules, as_of)
        tier = higher_tier(tier, t)
        reasons.extend(r)
        investigations.extend(inv)

    red_flag_present = has_red_flag(state, rules)

    # ── 2. Model layer - may RAISE the tier, never lower it ──────────────
    model_tier: Tier = "LOW"
    if model_probability is not None:
        capped = min(model_probability, MAX_REPORTED_PROBABILITY)
        # NG12's 3% positive-predictive-value threshold is the referral
        # convention this project adopts. It is a policy choice, stated
        # openly, not a number the model invented.
        if capped >= 0.03:
            model_tier = "HIGH"
        elif capped >= 0.01:
            model_tier = "MODERATE"
        tier = higher_tier(tier, model_tier)
        model_probability = capped

    # ── 3. Trajectory layer - the Loop Detector ─────────────────────────
    anchor = _pick_anchor(state, rules, as_of)
    features: dict = {}
    ladder_level, ladder_code = 0, "L0_OBSERVED"

    if anchor is not None:
        features = extract_features(state, anchor, rules, as_of)

        new_flag_after_onset = any(
            s.onset_date > anchor.onset_date
            and any(
                f["symptom"] == s.code and _applies(f.get("conditions", {}), state.person)
                for f in rules.red_flags
            )
            for s in state.active_symptoms()
        )

        lang = state.person.language
        ladder_level, ladder_code, ladder_reason = evaluate_ladder(
            features,
            rules,
            risk_tier=tier,
            new_red_flag_since_onset=new_flag_after_onset,
            lang=lang,
        )
        reasons.append(ladder_reason)
        reasons.extend(
            evaluate_contextual_flags(
                features, rules, has_red_flag=red_flag_present, lang=lang
            )
        )

        # The ladder itself can raise the tier. L2 and L3 are, by definition,
        # situations where the working diagnosis has already failed.
        if ladder_level >= 2:
            tier = higher_tier(tier, "HIGH")
        elif ladder_level == 1:
            tier = higher_tier(tier, "MODERATE")

        # The anchor's investigations go FIRST. A clinician reads the top of
        # the Handoff Card and stops; putting a peripheral symptom's blood
        # test above the endoscopy the trajectory actually calls for would
        # quietly defeat the whole point of the card.
        investigations = (
            rules.symptom(anchor.code).get("expected_investigations", [])
            + investigations
        )

    # ── 4. Screening - a separate track ─────────────────────────────────
    screening = evaluate_screening(state, rules, as_of)

    # ── 5. Next check-back ──────────────────────────────────────────────
    upcoming = None
    if anchor is not None:
        upcoming = next_checkback(anchor, rules, as_of, high_risk=(tier == "HIGH"))

    # Deduplicate investigations while preserving the order they were added,
    # so the most urgent rule's suggestion appears first on the Handoff Card.
    seen: set[str] = set()
    ordered_investigations = [
        i for i in investigations if not (i in seen or seen.add(i))
    ]

    return Assessment(
        as_of=as_of,
        tier=tier,
        ladder_level=ladder_level,
        ladder_code=ladder_code,
        anchor_symptom=anchor.code if anchor else None,
        features=features,
        reasons=reasons,
        recommended_investigations=ordered_investigations,
        screening_available=[s for s in screening if s["status"] == "available"],
        next_checkback=upcoming,
        ruleset_version=rules.version,
        model_version=model_version,
        model_probability=model_probability,
        model_contributions=model_contributions or [],
    )
