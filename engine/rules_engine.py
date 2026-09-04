"""
The deterministic layer: red flags, duration milestones, combination rules,
screening entitlements and check-back scheduling.

Nothing in this module is learned. Every output is traceable to a line in a
JSON file with a citation attached. This is roughly 60% of AIRA's decision
surface and it required no training data at all - which is exactly why we
could build it honestly in a country with no public dataset of primary-care
symptom trajectories.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import PatientState, Person, Reason, SymptomRecord, Tier, higher_tier
from .rules_loader import Ruleset


# ─────────────────────────────────────────────────────────────────────────────
# Eligibility helpers
# ─────────────────────────────────────────────────────────────────────────────


def _applies(conditions: dict, person: Person) -> bool:
    """Shared age/sex gate used by symptoms, red flags and screening."""
    min_age = conditions.get("min_age")
    max_age = conditions.get("max_age")
    sex = conditions.get("sex")

    if min_age is not None and person.age < min_age:
        return False
    if max_age is not None and person.age > max_age:
        return False
    if sex not in (None, "any") and person.sex != sex:
        return False
    return True


def _has_risk_factor(person: Person, token: str | None) -> bool:
    if not token:
        return True
    if token == "ever_smoked":
        return person.ever_smoked()
    if token == "tobacco_any":
        return person.uses_tobacco_any()
    return token in person.risk_factors


# ─────────────────────────────────────────────────────────────────────────────
# Red flags - fire on the day reported, override everything downstream
# ─────────────────────────────────────────────────────────────────────────────


def evaluate_red_flags(
    state: PatientState, rules: Ruleset, as_of: date
) -> tuple[Tier, list[Reason], list[str]]:
    """Returns (tier_floor, reasons, recommended_investigations).

    A red flag sets a floor. No model output and no LLM text may take the
    tier below this floor. That single constraint is the most important
    safety property in the system.
    """
    tier: Tier = "LOW"
    reasons: list[Reason] = []
    investigations: list[str] = []

    active = {s.code for s in state.active_symptoms()}
    lang = state.person.language

    for flag in rules.red_flags:
        if flag["symptom"] not in active:
            continue
        if not _applies(flag.get("conditions", {}), state.person):
            continue

        tier = higher_tier(tier, flag["tier"])
        pm = flag.get("patient_message", {})
        reasons.append(
            Reason(
                kind="red_flag",
                rule_id=flag["id"],
                message_clinician=flag["clinician_message"],
                message_patient=pm.get(lang) or pm.get("en", ""),
                citation=flag.get("citation", {}),
            )
        )
        investigations.extend(
            rules.symptom(flag["symptom"]).get("expected_investigations", [])
        )

    return tier, reasons, investigations


def has_red_flag(state: PatientState, rules: Ruleset) -> bool:
    active = {s.code for s in state.active_symptoms()}
    return any(
        f["symptom"] in active and _applies(f.get("conditions", {}), state.person)
        for f in rules.red_flags
    )


# ─────────────────────────────────────────────────────────────────────────────
# Duration milestones - the clock
#
# This is the part that answers "if a user has a continuous cough, will it be
# flagged, and when?". A cough carries two milestones: day 14 (India's
# presumptive TB definition) and day 21 (NG12 chest X-ray). Neither of them
# says the word cancer.
# ─────────────────────────────────────────────────────────────────────────────


SAFE_WINDOW_BREACH = {
    "en": "This has been going on for {days} days. For this kind of problem, more than {window} days is longer than expected.",
    "hi": "यह {days} दिनों से चल रहा है। इस तरह की समस्या के लिए {window} दिन से ज्यादा होना अपेक्षा से अधिक है।",
    "kn": "ಇದು {days} ದಿನಗಳಿಂದ ಇದೆ. ಈ ರೀತಿಯ ಸಮಸ್ಯೆಗೆ {window} ದಿನಕ್ಕಿಂತ ಹೆಚ್ಚು ಎಂದರೆ ನಿರೀಕ್ಷೆಗಿಂತ ದೀರ್ಘ.",
}


def _localise(value, lang: str) -> str:
    """Rule messages may be a bare string (clinician-facing) or a
    {en, hi, kn} object (patient-facing). Patient-facing text must never fall
    back to English silently - if a translation is missing that is a ruleset
    bug, and the loader rejects it at startup."""
    if isinstance(value, dict):
        return value.get(lang) or value.get("en", "")
    return value or ""


def evaluate_milestones(
    state: PatientState, rules: Ruleset, as_of: date
) -> tuple[Tier, list[Reason], list[str]]:
    tier: Tier = "LOW"
    reasons: list[Reason] = []
    investigations: list[str] = []
    lang = state.person.language

    for sym in state.active_symptoms():
        spec = rules.symptom(sym.code)
        if not _applies(spec.get("applies", {}), state.person):
            continue

        elapsed = sym.days_elapsed(as_of)

        for ms in spec.get("milestones", []):
            if elapsed < ms["day"]:
                continue
            tier = higher_tier(tier, ms.get("tier_floor", "MODERATE"))
            reasons.append(
                Reason(
                    kind="milestone",
                    rule_id=f"{sym.code}@day{ms['day']}",
                    message_clinician=(
                        f"{spec['label']['en']} at day {elapsed} "
                        f"(milestone {ms['day']}, action {ms['action']}). "
                        f"{_localise(ms['message'], 'en')}"
                    ),
                    message_patient=_localise(ms["message"], lang),
                    citation={"source": ms.get("source", "")},
                )
            )
            investigations.extend(spec.get("expected_investigations", []))

        # Safe-window breach, separate from named milestones.
        window = rules.safe_window(sym.code)
        if window > 0 and elapsed > window:
            tier = higher_tier(tier, "MODERATE")
            reasons.append(
                Reason(
                    kind="milestone",
                    rule_id=f"{sym.code}@safe_window",
                    message_clinician=(
                        f"{spec['label']['en']} has persisted {elapsed} days against a "
                        f"{window}-day safe window (ratio {elapsed / window:.2f})."
                    ),
                    message_patient=SAFE_WINDOW_BREACH.get(
                        lang, SAFE_WINDOW_BREACH["en"]
                    ).format(days=elapsed, window=window),
                    citation=spec.get("citation", {}),
                )
            )
            investigations.extend(spec.get("expected_investigations", []))

    return tier, reasons, investigations


# ─────────────────────────────────────────────────────────────────────────────
# Combination rules - the ones where no single symptom is alarming
# ─────────────────────────────────────────────────────────────────────────────

COMBINATION_MESSAGE = {
    "en": "These problems together are worth getting checked, even though each one on its own is common.",
    "hi": "ये समस्याएं एक साथ होने पर जांच कराने लायक हैं, भले ही अलग-अलग आम हों।",
    "kn": "ಈ ಸಮಸ್ಯೆಗಳು ಒಟ್ಟಿಗೆ ಇದ್ದಾಗ ಪರೀಕ್ಷಿಸಿಕೊಳ್ಳುವುದು ಒಳ್ಳೆಯದು, ಪ್ರತ್ಯೇಕವಾಗಿ ಸಾಮಾನ್ಯವಾಗಿದ್ದರೂ.",
}


def evaluate_combinations(
    state: PatientState, rules: Ruleset, as_of: date
) -> tuple[Tier, list[Reason], list[str]]:
    tier: Tier = "LOW"
    reasons: list[Reason] = []
    investigations: list[str] = []

    active = {s.code: s for s in state.active_symptoms()}

    for combo in rules.combinations:
        when = combo["when"]

        if not _applies(when, state.person):
            continue
        if not _has_risk_factor(state.person, when.get("requires_risk_factor")):
            continue

        required = when.get("all_of", [])
        if any(code not in active for code in required):
            continue

        pool = when.get("any_of", [])
        matched = [c for c in pool if c in active] if pool else []
        if pool and len(matched) < when.get("min_count", 1):
            continue

        companions = when.get("companion_any_of", [])
        if companions and not any(c in active for c in companions):
            continue

        # At least one contributing symptom must have persisted long enough.
        # Without this, someone who coughed yesterday and is tired today would
        # trip a lung-cancer rule, which would be both wrong and cruel.
        min_days = when.get("anchor_persisted_days", 0)
        contributing = matched + required + [c for c in companions if c in active]
        if min_days and not any(
            active[c].days_elapsed(as_of) >= min_days for c in contributing if c in active
        ):
            continue

        then = combo["then"]
        tier = higher_tier(tier, then.get("tier_floor", "MODERATE"))
        names = ", ".join(sorted(set(contributing)))
        reasons.append(
            Reason(
                kind="combination",
                rule_id=combo["id"],
                message_clinician=(
                    f"{combo['label']}. Present: {names}. Action: {then['action']}."
                ),
                message_patient=COMBINATION_MESSAGE.get(
                    state.person.language, COMBINATION_MESSAGE["en"]
                ),
                citation=combo.get("citation", {}),
            )
        )
        for code in contributing:
            if code in active:
                investigations.extend(
                    rules.symptom(code).get("expected_investigations", [])
                )

    return tier, reasons, investigations


# ─────────────────────────────────────────────────────────────────────────────
# Screening - a separate track, never mixed with symptom alerts
# ─────────────────────────────────────────────────────────────────────────────


def evaluate_screening(state: PatientState, rules: Ruleset, as_of: date) -> list[dict]:
    out: list[dict] = []
    person = state.person
    lang = person.language

    for prog in rules.programmes:
        if not _applies(prog.get("eligibility", {}), person):
            continue

        interval = prog.get("interval_months")
        shortened = False
        risk_tokens = set(prog.get("risk_factors_shortening_interval", []))
        if risk_tokens & person.risk_factors and prog.get("interval_months_if_risk"):
            interval = prog["interval_months_if_risk"]
            shortened = True

        last = state.last_screening.get(prog["id"])
        if prog.get("one_time"):
            status = "done" if last else "available"
            due_on = None
        elif last is None:
            status = "available"
            due_on = None
        else:
            due_on = last + timedelta(days=int(interval * 30.44))
            status = "available" if as_of >= due_on else "up_to_date"

        pm = prog.get("patient_message", {})
        out.append(
            {
                "id": prog["id"],
                "name": prog["name"].get(lang) or prog["name"]["en"],
                "status": status,
                "test": prog["test"],
                "where": prog["where"],
                "who_performs": prog["who_performs"],
                "cost_to_patient": prog["cost_to_patient"],
                "interval_months": interval,
                "interval_shortened_by_risk": shortened,
                "last_done": last.isoformat() if last else None,
                "next_due": due_on.isoformat() if due_on else None,
                "message": pm.get(lang) or pm.get("en", ""),
                "dignity_note": prog.get("dignity_note"),
                "citation": prog.get("citation", {}),
            }
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Check-back scheduling
#
# Scheduled by the clock, not by the user opening the app. Someone who stops
# opening the app is exactly the person we most need to hear from.
# ─────────────────────────────────────────────────────────────────────────────


def next_checkback(
    sym: SymptomRecord, rules: Ruleset, as_of: date, high_risk: bool = False
) -> date | None:
    window = rules.safe_window(sym.code)
    if window <= 0:
        # Red-flag symptom: there is no watchful waiting. Follow up tomorrow.
        return as_of + timedelta(days=1)

    key = "checkback_fractions_high_risk" if high_risk else "checkback_fractions"
    fractions = rules.defaults.get(key, [0.33, 0.66, 1.0])

    for frac in sorted(fractions):
        candidate = sym.onset_date + timedelta(days=int(round(window * frac)))
        if candidate > as_of:
            return candidate

    # Past the window entirely: keep checking every two weeks. We never stop.
    return as_of + timedelta(days=14)
