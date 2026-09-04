"""
The chatbot.

One endpoint, two audiences, and the audience is taken from the AUTHENTICATED
ROLE rather than from the request body - so a patient cannot ask for the
clinician rendering by editing a field, and a curious front-end cannot do it
by accident.

Everything else lives in llm/answer.py. This module's whole job is to decide
who is asking, assemble the facts they are entitled to, and write down what
happened.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from llm.answer import answer_question
from rag.store import retriever

from .. import audit
from ..db import get_db
from ..deps import authorise_patient_access, current_user
from ..llm_service import build_llm_facts, gemini
from ..schemas import ChatRequest
from ..tables import ChatMessage, Role, User

router = APIRouter(prefix="/chat", tags=["chat"])

# Audience is derived, never supplied. An admin reads the clinician rendering
# because the technical layer is what an operations console is for - but note
# that an admin still cannot name a patient to ask about, because the facts
# lookup below is gated on consent.
AUDIENCE_FOR_ROLE = {
    Role.PATIENT: "patient",
    Role.DOCTOR: "clinician",
    Role.ADMIN: "clinician",
}


@router.get("/status")
def status_(user: User = Depends(current_user)):
    r = retriever()
    return {
        "llm": gemini().status(),
        "retrieval": r.stats(),
        "audience": AUDIENCE_FOR_ROLE.get(user.role, "patient"),
        "guarantees": [
            "Rules and retrieved guidelines decide; the model only phrases.",
            "Every number in an answer must appear in a cited source or in the patient's own record.",
            "No name, phone, code, village or date reaches the model.",
            "A draft that fails verification is replaced by the guideline text, not shown with a warning.",
            "Hindi and Kannada are translated only AFTER an English answer has passed verification, "
            "and the translation is rejected if a number changes.",
        ],
    }


@router.post("")
def ask(
    body: ChatRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    audience = AUDIENCE_FOR_ROLE.get(user.role, "patient")

    facts: dict = {}
    names: list[str] = []
    subject: str | None = None

    if user.role == Role.PATIENT:
        subject = user.id
        facts, names = build_llm_facts(db, user.id, audience)
    elif body.patient_id:
        # A clinician may ask about a specific patient, but only through the
        # same consent gate as every other read. There is no separate,
        # friendlier path to a record just because the question is phrased
        # in English.
        authorise_patient_access(
            patient_id=body.patient_id, request=request, user=user, db=db
        )
        subject = body.patient_id
        facts, names = build_llm_facts(db, body.patient_id, audience)

    result = answer_question(
        body.question,
        gemini(),
        audience=audience,
        language=body.language,
        facts=facts,
        names_to_remove=names,
    )

    row = ChatMessage(
        user_id=user.id,
        audience=audience,
        language=body.language,
        subject_patient_id=subject,
        question=body.question,
        answer=result.text,
        refused=result.refused,
        verified=result.verified,
        fallback_used=result.fallback_used,
        model_used=(result.trace.get("llm") or {}).get("model_used"),
        citations_json=json.dumps(result.citations, ensure_ascii=False),
        trace_json=json.dumps(result.trace, ensure_ascii=False, default=str),
    )
    db.add(row)
    db.commit()

    audit.record(
        db,
        action="CHAT_ANSWERED",
        actor_user_id=user.id,
        actor_role=user.role.value,
        target_type="chat",
        target_id=row.id,
        detail={
            "audience": audience,
            "refused": result.refused,
            "fallback": result.fallback_used,
            "route": result.trace.get("route"),
        },
        request=request,
    )

    payload = result.as_dict()
    payload["id"] = row.id
    if audience == "patient":
        # The full trace names guideline sections, retrieval scores and the
        # model's rejected drafts. That is a clinician's and an auditor's
        # view of the machinery, not something to put under a patient's
        # answer, so they get the short version.
        payload["trace"] = {
            "route": result.trace.get("route"),
            "sources_used": len(result.citations),
            "written_by": "guideline text"
            if result.fallback_used
            else "AI, checked against the sources",
        }
    return payload


@router.get("/history")
def history(
    limit: int = 20,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(min(limit, 100))
        .all()
    )
    audience = AUDIENCE_FOR_ROLE.get(user.role, "patient")
    return [
        {
            "id": r.id,
            "at": r.created_at.isoformat(),
            "question": r.question,
            "answer": r.answer,
            "refused": r.refused,
            "fallback_used": r.fallback_used,
            "citations": json.loads(r.citations_json),
            "trace": json.loads(r.trace_json) if audience != "patient" else None,
        }
        for r in reversed(rows)
    ]


@router.get("/{message_id}/trace")
def trace(
    message_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """The full guardrail record for one answer, including any draft that was
    rejected. Clinicians and admins only - this is the audit view."""
    if user.role == Role.PATIENT:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "the technical trace is a clinician view",
        )
    row = db.get(ChatMessage, message_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    return {
        "id": row.id,
        "question": row.question,
        "answer": row.answer,
        "citations": json.loads(row.citations_json),
        "trace": json.loads(row.trace_json),
    }
