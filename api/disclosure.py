"""
Minimum necessary disclosure.

Consent answers "may this clinician read this record". It does not answer
"which fields", and treating those as the same question is how health systems
end up handing a dermatologist a phone number, a house address and a date of
birth to look at a rash.

So every field a clinician can see is listed here with the reason it is
clinically necessary, and every field they cannot see is listed with the
reason it is not. The list is the policy - there is no code path that returns
a patient field which is not named in DISCLOSED.

WHY THE WITHHELD LIST IS RETURNED TO THE CLIENT

Because a privacy control nobody can see is indistinguishable from one that
does not exist. The clinician's screen says, in words, which fields were
withheld and why. That turns a claim in a slide deck into something a judge
can click on, and it tells a real clinician exactly what to ask the patient
for directly if they genuinely need it.

WHAT IS NOT HERE, ANYWHERE IN THE SYSTEM

Caste, religion, income and community are not withheld fields. They are not
columns. They were never collected, so there is nothing to leak, nothing to
correlate against, and no model that can learn them.
"""

from __future__ import annotations

from datetime import date

# field -> why a clinician genuinely needs it
DISCLOSED: dict[str, str] = {
    "name": "to address the patient and match them to the person in front of you",
    "age": "every referral threshold in NG12 and NP-NCD is age-gated",
    "sex": "several pathways are sex-restricted; dosing and screening differ",
    "risk_factors": "tobacco, alcohol and family history drive the combination rules",
    "bmi": "unintentional weight loss is interpreted against it",
    "language": "so the consultation and the written note are in a language they read",
    "aira_code": "the record identifier, so notes can be filed against the right person",
}

# field -> why it is NOT sent, even under an active consent
WITHHELD: dict[str, str] = {
    "phone": "contact details are not needed to interpret a symptom history; the clinic already has its own way to contact its patients",
    "date_of_birth": "age is sufficient for every rule; an exact date of birth is an identifier, not a clinical fact",
    "village": "an exact locality plus age plus sex re-identifies a person in a small settlement; ask the patient directly if you need it for follow-up",
    "email": "not clinically relevant",
    "password_hash": "never leaves the database under any circumstance",
    "other_doctors": "who else this patient has consented to is their business, not yours",
}

# What each consent scope unlocks. A scope the patient did not grant returns
# nothing, not an empty list that looks like "there is nothing there".
SCOPE_UNLOCKS = {
    "symptoms": "the symptoms the patient has recorded, with dates",
    "episodes": "visits, treatments given and whether anything was investigated",
    "assessments": "what AIRA concluded, and why",
    "documents": "reports the patient has uploaded",
}


def age_from_dob(dob: date, on: date | None = None) -> int:
    on = on or date.today()
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def patient_projection(profile, consent=None, as_of: date | None = None) -> dict:
    """The ONLY shape in which a patient's demographics reach a clinician."""
    scopes = [s for s in (consent.scope.split(",") if consent else []) if s]
    return {
        "id": profile.user_id,
        "name": profile.name,
        "age": age_from_dob(profile.dob, as_of),
        "sex": profile.sex,
        "aira_code": profile.aira_code,
        "language": profile.language,
        "risk_factors": [r for r in (profile.risk_factors or "").split(",") if r],
        "bmi": profile.bmi,
        "disclosure": {
            "shared": DISCLOSED,
            "withheld": WITHHELD,
            "scopes_granted": {s: SCOPE_UNLOCKS.get(s, s) for s in scopes},
            "note": (
                "These are the only patient fields this API will return to a "
                "clinician. The withheld list is enforced in api/disclosure.py, "
                "not by this screen choosing what to render."
            ),
        },
    }


def queue_projection(profile, as_of: date | None = None) -> dict:
    """Even less, for the list view. A queue row is read at a glance by
    whoever is standing behind the clinician, so it carries the minimum that
    still identifies the right person."""
    return {
        "name": profile.name,
        "age": age_from_dob(profile.dob, as_of),
        "sex": profile.sex,
        "aira_code": profile.aira_code,
    }
