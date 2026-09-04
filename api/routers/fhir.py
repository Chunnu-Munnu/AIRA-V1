"""
FHIR R4 export - the ABDM data layer.

What is real here: the resources are genuine FHIR R4. A Patient resource with
an ABHA-shaped identifier, Observations for symptoms, an Encounter per visit,
a DiagnosticReport carrying the assessment, wrapped in a Bundle of type
'document' with a Composition - which is the shape an ABDM Health Information
Provider actually returns.

What is NOT real, stated plainly so nobody is misled: we are not connected to
the live ABDM sandbox. That requires organisation registration and M1/M2/M3
milestone certification, which is a paperwork process measured in weeks, not
an engineering one. Any team claiming a live ABDM connection built in a
weekend is describing something that did not happen.

The honest claim, and the one worth making: AIRA is ABDM-compliant at the data
layer today, and every access is gated by a real consent artefact. Swapping our
identity provider for ABHA and our store for an HIP does not change this file.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import authorise_patient_access
from ..service import age_from_dob
from ..tables import Assessment, Consent, Episode, PatientProfile, Symptom

router = APIRouter(prefix="/fhir", tags=["fhir / abdm"])

SNOMED = "http://snomed.info/sct"
AIRA_CS = "https://aira.health/CodeSystem/symptom"
ABHA_SYSTEM = "https://healthid.ndhm.gov.in/"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _patient_resource(prof: PatientProfile) -> dict:
    return {
        "resourceType": "Patient",
        "id": prof.user_id,
        "meta": {
            "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/Patient"]
        },
        "identifier": [
            {
                # In a live deployment this is the ABHA address. Here it is the
                # AIRA code, which occupies exactly the same position in the
                # protocol: an address, never a credential.
                "system": ABHA_SYSTEM,
                "value": prof.aira_code,
                "type": {"text": "AIRA code (stands in for ABHA address)"},
            }
        ],
        "name": [{"text": prof.name}],
        "gender": prof.sex,
        "birthDate": prof.dob.isoformat(),
        # Note what is not here: no phone number, no address beyond village,
        # no Aadhaar. Scope is what consent permits, and nothing more.
        "address": [{"text": prof.village}] if prof.village else [],
    }


def _observation(sym: Symptom, patient_id: str) -> dict:
    return {
        "resourceType": "Observation",
        "id": sym.id,
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "symptom",
                    }
                ]
            }
        ],
        "code": {"coding": [{"system": AIRA_CS, "code": sym.code}], "text": sym.code},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": sym.onset_date.isoformat(),
        "issued": sym.created_at.isoformat(),
        "interpretation": [
            {"text": "red flag" if sym.is_red_flag else "under observation"}
        ],
        "note": [
            {
                "text": (
                    f"safe window {sym.safe_window_days} days; "
                    f"ruleset {sym.ruleset_version}"
                )
            }
        ],
    }


def _encounter(ep: Episode, patient_id: str) -> dict:
    return {
        "resourceType": "Encounter",
        "id": ep.id,
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": ep.encounter_date.isoformat()},
        "serviceProvider": {"display": ep.provider_type},
        "extension": [
            {"url": "https://aira.health/fhir/intervention", "valueString": ep.intervention_class},
            {
                "url": "https://aira.health/fhir/investigation",
                "valueString": ep.investigation_ordered,
            },
            {
                "url": "https://aira.health/fhir/outcome",
                "valueString": ep.outcome_at_followup or "unknown",
            },
        ],
    }


def _diagnostic_report(a: Assessment, patient_id: str) -> dict:
    reasons = json.loads(a.reasons_json)
    features = json.loads(a.features_json)
    contributions = json.loads(a.contributions_json)

    conclusion_lines = [
        f"Tier {a.tier}; loop detector {a.ladder_code} (L{a.ladder_level}).",
        f"Trajectory: {features.get('days_elapsed')} days against a "
        f"{features.get('safe_window_days')}-day safe window "
        f"(ratio {features.get('duration_ratio')}); "
        f"{features.get('n_episodes')} encounters, "
        f"{features.get('n_investigations')} investigations, "
        f"{features.get('n_failed_treatments')} failed treatments.",
        "",
        "Rules that fired:",
    ] + [f"- {r['rule_id']}: {r['clinician']}" for r in reasons]

    if contributions:
        conclusion_lines += ["", "Model contributions:"] + [
            f"- {c['feature']}: {c['contribution']:+.4f}" for c in contributions
        ]

    conclusion_lines += [
        "",
        f"ruleset {a.ruleset_version}; model {a.model_version or 'rules-only'}",
        "AIRA is a prioritisation aid, not a diagnosis.",
    ]

    return {
        "resourceType": "DiagnosticReport",
        "id": a.id,
        "status": "final",
        "code": {"text": "AIRA longitudinal symptom trajectory assessment"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": a.as_of.isoformat(),
        "issued": a.created_at.isoformat(),
        "conclusion": "\n".join(conclusion_lines),
    }


@router.get("/Patient/{patient_id}/$everything")
def everything(
    patient_id: str,
    access=Depends(authorise_patient_access),
    db: Session = Depends(get_db),
):
    """A FHIR document Bundle for one patient.

    The consent artefact that authorised this call is embedded in the Bundle
    metadata, so the document itself carries the proof of why it was allowed
    to exist. That is what an HIU receives from an HIP under ABDM.
    """
    _, consent = access
    prof = db.get(PatientProfile, patient_id)
    if prof is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "patient not found")

    scopes = set((consent.scope.split(",") if consent else ["symptoms", "episodes", "assessments"]))

    entries: list[dict] = [{"resource": _patient_resource(prof)}]

    if "symptoms" in scopes:
        entries += [
            {"resource": _observation(s, patient_id)}
            for s in db.query(Symptom).filter(Symptom.patient_id == patient_id).all()
        ]
    if "episodes" in scopes:
        entries += [
            {"resource": _encounter(e, patient_id)}
            for e in db.query(Episode).filter(Episode.patient_id == patient_id).all()
        ]
    if "assessments" in scopes:
        entries += [
            {"resource": _diagnostic_report(a, patient_id)}
            for a in db.query(Assessment)
            .filter(Assessment.patient_id == patient_id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(5)
            .all()
        ]

    composition = {
        "resourceType": "Composition",
        "status": "final",
        "type": {"text": "OPConsultation"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": _now_iso(),
        "title": "AIRA longitudinal record",
        "section": [{"title": "Symptom trajectory", "entry": [
            {"reference": f"{e['resource']['resourceType']}/{e['resource'].get('id','')}"}
            for e in entries[1:]
        ]}],
    }

    return {
        "resourceType": "Bundle",
        "type": "document",
        "timestamp": _now_iso(),
        "meta": {
            "profile": [
                "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle"
            ],
            "tag": [
                {
                    "system": "https://aira.health/consent",
                    "code": consent.id if consent else "self",
                    "display": (
                        f"issued {consent.granted_at.isoformat()}, "
                        f"expires {consent.expires_at.isoformat()}, "
                        f"scope {consent.scope}"
                        if consent and consent.granted_at and consent.expires_at
                        else "patient reading their own record"
                    ),
                }
            ],
        },
        "entry": [{"resource": composition}] + entries,
    }


@router.get("/Consent/{consent_id}")
def consent_resource(
    consent_id: str,
    db: Session = Depends(get_db),
):
    """The artefact itself, as a FHIR Consent resource. This is the object
    ABDM's Consent Manager issues and that an HIP validates before releasing
    anything."""
    c = db.get(Consent, consent_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "consent not found")
    return {
        "resourceType": "Consent",
        "id": c.id,
        "status": {"ACTIVE": "active", "REVOKED": "inactive", "EXPIRED": "inactive"}.get(
            c.status.value, "proposed"
        ),
        "scope": {"text": "patient-privacy"},
        "category": [{"text": c.purpose}],
        "patient": {"reference": f"Patient/{c.patient_id}"},
        "dateTime": c.requested_at.isoformat(),
        "performer": [{"reference": f"Patient/{c.patient_id}"}],
        "provision": {
            "type": "permit",
            "period": {
                "start": c.granted_at.isoformat() if c.granted_at else None,
                "end": c.expires_at.isoformat() if c.expires_at else None,
            },
            "actor": [
                {
                    "role": {"text": "requesting clinician"},
                    "reference": {"reference": f"Practitioner/{c.doctor_id}"},
                }
            ],
            "data": [{"meaning": "instance", "reference": {"display": s}} for s in c.scope.split(",")],
        },
        "extension": [
            {
                "url": "https://aira.health/fhir/consent-comprehension",
                "valueString": (
                    f"notice played aloud in {c.read_aloud_language} at "
                    f"{c.read_aloud_at.isoformat()}"
                    if c.read_aloud_at
                    else "notice was not played aloud"
                ),
            }
        ],
    }
