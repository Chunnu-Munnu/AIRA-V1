"""
Uploaded medical reports.

The flow, and the order matters:

    upload -> extract text -> PARSE DETERMINISTICALLY -> compare against
    reference intervals from the RAG corpus -> phrase (optional) -> verify

The language model enters at step five, if at all, and only to phrase what
steps three and four already established. It is never shown the document and
asked what it says. See docs_ingest/parse.py for why that ordering is the
anti-hallucination argument.

TWO OUTPUTS, NOT ONE

The same document produces a patient summary and a clinician summary. The
patient's says "below the usual range, which has many causes, show this to
your doctor". The clinician's says "Hb 8.2 [BELOW ref 11.5-15.5]" alongside
the pattern it forms with the other values. Neither is a censored version of
the other.

WHAT AN UPLOAD CAN AND CANNOT CHANGE

It can record that an investigation was actually done, which is the single
fact that breaks the Loop Detector's investigation-gap condition - and it
does so by creating a real Episode, through the same path a clinician uses.
It cannot change a tier by itself, and it cannot make AIRA less concerned
about anything the rules are still concerned about.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from docs_ingest.parse import extract_text, parse_report, summarise
from llm.answer import SYSTEM
from rag.store import retriever
from rag.verify import verify

from datetime import datetime, timezone

from .. import audit
from ..care import sync_care_plan
from ..config import get_settings
from ..db import get_db
from ..deps import authorise_patient_access, current_user, require_patient
from ..llm_service import gemini
from ..service import assess_and_store
from ..tables import Episode, MedicalDocument, PatientProfile, Role, User
from ..ws import notify

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()

STORAGE = Path("storage/documents")

ALLOWED = {
    "text/plain", "text/markdown", "text/csv", "application/json",
    "application/pdf",
    "image/jpeg", "image/png", "image/webp",
}


def _age(dob: date) -> int:
    t = date.today()
    return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))


def _phrase(report, audience: str, deterministic: str) -> tuple[str, dict]:
    """Ask the model to make the deterministic summary readable.

    The retrieved passages here are the reference-interval entries the parser
    already used, so the verifier is checking the phrasing against exactly the
    sources the numbers came from. If it fails, the deterministic summary is
    what ships - which is a perfectly good answer, just a stiffer one.
    """
    client = gemini()
    if not report.findings or not client.available:
        return deterministic, {"llm_called": False, "why": "no findings or model unavailable"}

    r = retriever()
    hits = r.search(
        " ".join(f.analyte for f in report.findings) + " reference interval", k=5
    )
    known = {f"v{i}": f.value for i, f in enumerate(report.findings) if f.value is not None}
    for i, f in enumerate(report.findings):
        if f.reference:
            known[f"lo{i}"], known[f"hi{i}"] = f.reference

    prompt = (
        f"READER: {audience}.\n"
        "TASK: rewrite the FINDINGS below as prose. Do not add a finding, a number, "
        "a cause or a diagnosis. Do not say what the result means clinically. "
        "Two or three sentences.\n\n"
        f"FINDINGS (already established by a parser, all of these numbers are true):\n{deterministic}\n\n"
        "REFERENCE SOURCES:\n"
        + "\n".join(f"[{i}] {h.chunk.text}" for i, h in enumerate(hits, 1))
    )
    result = client.generate(system=SYSTEM, prompt=prompt, task="document")
    draft = result.get("text")
    if not draft:
        return deterministic, {"llm_called": True, "source": result["source"], "reason": result.get("reason")}

    verdict = verify(draft, hits, known_facts=known)
    if verdict.ok:
        client.commit({**result, "text": draft})
        return draft, {"llm_called": True, "verified": True, "checks": verdict.checks}
    return deterministic, {
        "llm_called": True,
        "verified": False,
        "problems": verdict.problems,
        "rejected_draft": draft,
    }


@router.post("", status_code=201)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    note: str = Form(default=""),
    record_as_investigation: bool = Form(default=True),
    cluster_id: str = Form(default=""),
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file is larger than {settings.max_upload_bytes // (1024 * 1024)} MB",
        )
    if file.content_type not in ALLOWED:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"AIRA accepts text, PDF and photographs. It cannot read {file.content_type}.",
        )

    prof = db.get(PatientProfile, user.id)
    digest = hashlib.sha256(data).hexdigest()

    # Content-addressed, so re-uploading the same report does not store it
    # twice and cannot be used to inflate a record.
    STORAGE.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix[:10]
    path = STORAGE / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(data)

    text, how = extract_text(data, file.content_type, file.filename or "")
    report = parse_report(text, age=_age(prof.dob), sex=prof.sex, how=how)

    det_patient = summarise(report, "patient")
    det_clinician = summarise(report, "clinician")
    patient_text, trace = _phrase(report, "patient", det_patient)

    row = MedicalDocument(
        patient_id=user.id,
        uploaded_by=user.id,
        filename=file.filename or "upload",
        content_type=file.content_type,
        size_bytes=len(data),
        sha256=digest,
        storage_path=str(path),
        extraction_method=how,
        # The raw text is kept for the clinician and for audit, capped so a
        # 200-page discharge summary cannot fill the row.
        raw_text=(text or None) and text[:20000],
        extracted_json=json.dumps(report.to_dict(), ensure_ascii=False),
        summary_patient=patient_text,
        summary_clinician=det_clinician,
        verified=bool(trace.get("verified", not trace.get("llm_called"))),
        verification_json=json.dumps(trace, ensure_ascii=False),
    )
    db.add(row)
    db.flush()

    # An uploaded report proving a test was done is the fact that breaks the
    # loop. It goes in as a real Episode so the Loop Detector sees it through
    # the same door as everything else.
    created_episode = None
    tests_present = [f.analyte for f in report.findings] + report.mentioned_tests
    if record_as_investigation and tests_present:
        episode = Episode(
            patient_id=user.id,
            cluster_id=cluster_id or "systemic",
            encounter_date=report.report_date or date.today(),
            provider_type="unknown",
            intervention_class="none",
            investigation_ordered=", ".join(tests_present[:3]),
            outcome_at_followup=None,
            recorded_by=user.id,
            source="patient",
        )
        db.add(episode)
        db.flush()
        row.episode_id = episode.id
        created_episode = episode.id

    db.commit()

    assessment = assess_and_store(db, user.id)
    audit.record(
        db,
        action="DOCUMENT_UPLOADED",
        actor_user_id=user.id,
        actor_role="PATIENT",
        target_type="document",
        target_id=row.id,
        detail={
            "how": how,
            "findings": len(report.findings),
            "abnormal": report.to_dict()["abnormal_count"],
            "episode_created": bool(created_episode),
        },
        request=request,
    )

    return {
        "id": row.id,
        "filename": row.filename,
        "extraction_method": how,
        "findings": report.to_dict()["findings"],
        "abnormal_count": report.to_dict()["abnormal_count"],
        "mentioned_tests": report.mentioned_tests,
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "notes": report.notes,
        "summary": patient_text,
        "verified": row.verified,
        "episode_created": created_episode,
        "tier": assessment.tier,
        "ladder_level": assessment.ladder_level,
        "disclaimer": (
            "AIRA read the typed numbers in this file and compared them with "
            "published reference ranges. It did not interpret them, and a "
            "value outside a range is not a diagnosis."
        ),
    }


@router.get("/mine")
def mine(user: User = Depends(require_patient), db: Session = Depends(get_db)):
    rows = (
        db.query(MedicalDocument)
        .filter(MedicalDocument.patient_id == user.id)
        .order_by(MedicalDocument.created_at.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "at": d.created_at.isoformat(),
            "extraction_method": d.extraction_method,
            "summary": d.summary_patient,
            "abnormal_count": json.loads(d.extracted_json).get("abnormal_count", 0),
            "findings": json.loads(d.extracted_json).get("findings", []),
            "verified": d.verified,
        }
        for d in rows
    ]


@router.post("/{document_id}/review")
def review_document(
    document_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """A clinician records that they have actually reviewed an uploaded
    report. This is an explicit act, not something inferred from opening a
    tab - "report uploaded but never reviewed" is one of the care gaps AIRA
    is meant to surface, and it can only surface it if review is recorded.
    """
    if user.role == Role.PATIENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "clinicians only")

    doc = db.get(MedicalDocument, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")

    authorise_patient_access(patient_id=doc.patient_id, request=request, user=user, db=db)

    doc.reviewed_at = datetime.now(timezone.utc)
    doc.reviewed_by = user.id
    db.commit()

    sync_care_plan(db, doc.patient_id)
    audit.record(
        db,
        action="DOCUMENT_REVIEWED",
        actor_user_id=user.id,
        actor_role=user.role.value,
        target_type="medical_document",
        target_id=doc.id,
        request=request,
    )
    notify(doc.patient_id, "record.updated", {"reason": "document_reviewed"})
    return {"id": doc.id, "reviewed_at": doc.reviewed_at.isoformat()}


@router.get("/patient/{patient_id}")
def for_clinician(
    patient_id: str,
    access=Depends(authorise_patient_access),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """The clinician view: the technical summary, the raw extracted values,
    and the parser's own limitations stated openly."""
    if user.role == Role.PATIENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "use /documents/mine")

    rows = (
        db.query(MedicalDocument)
        .filter(MedicalDocument.patient_id == patient_id)
        .order_by(MedicalDocument.created_at.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "at": d.created_at.isoformat(),
            "content_type": d.content_type,
            "extraction_method": d.extraction_method,
            "summary": d.summary_clinician,
            "extracted": json.loads(d.extracted_json),
            "raw_text": d.raw_text,
            "verification": json.loads(d.verification_json),
            "episode_id": d.episode_id,
            "caveat": (
                "Values were read by a regular-expression parser, not by a model. "
                "Anything it did not recognise is absent rather than guessed. "
                "Photographs are stored but never read."
            ),
        }
        for d in rows
    ]
