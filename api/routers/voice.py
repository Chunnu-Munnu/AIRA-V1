"""Voice input and read-aloud. Every route here is credit-aware."""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import current_user, require_patient
from ..schemas import SpeakRequest, TranscribeRequest
from ..tables import PatientProfile, User, VoiceNote
from voice.sarvam import SarvamClient
from voice.symptom_mapper import parse

router = APIRouter(prefix="/voice", tags=["voice"])
settings = get_settings()

client = SarvamClient(
    api_key=settings.sarvam_api_key,
    mode=settings.sarvam_mode,
    max_live_calls=settings.sarvam_max_live_calls,
)


@router.get("/status")
def status_(user: User = Depends(current_user)):
    """Shown in the admin console so nobody discovers the budget is spent
    thirty seconds before the demo."""
    usage = client.credits_used()
    return {
        "mode": settings.sarvam_mode,
        "live_calls_used": usage["live_calls"],
        "live_calls_budget": settings.sarvam_max_live_calls,
        "by_endpoint": usage["by_endpoint"],
        "fallback": "browser Web Speech API",
    }


@router.post("/speak")
def speak(body: SpeakRequest, user: User = Depends(current_user)):
    """Text to speech. Pre-rendered phrases come from disk and cost nothing;
    only genuinely novel text ever reaches the API."""
    return client.speak(body.text, body.language, cache_key=body.cache_key)


@router.post("/transcribe")
def transcribe(
    body: TranscribeRequest,
    request: Request,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """Speech to symptom candidates.

    The result is never written to the clinical record here. It returns
    SUGGESTIONS which the patient confirms with a tap, and only that
    confirmation creates a symptom row.
    """
    if body.audio_base64:
        try:
            audio = base64.b64decode(body.audio_base64)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "audio is not valid base64") from exc
        result = client.transcribe(audio, body.language)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "audio_base64 is required")

    transcript = result.get("transcript", "")
    parsed = parse(transcript)

    # Second pass, and only if the first found nothing. The mapper carries
    # Hindi and Kannada phrasings from the ruleset, so most Indic speech is
    # matched with no network call; translation is what happens when someone
    # says it a way nobody anticipated, which is exactly when a credit is
    # worth spending.
    if transcript and not parsed["candidates"] and body.language != "en":
        translated = client.translate_to_english(transcript, body.language)
        if translated.get("source") == "live":
            retry = parse(translated["text"], translated_from=body.language)
            if retry["candidates"]:
                parsed = retry

    prof = db.get(PatientProfile, user.id)
    db.add(
        VoiceNote(
            patient_id=user.id,
            language=body.language,
            transcript=transcript,
            mapped_codes=json.dumps([c["code"] for c in parsed["candidates"]]),
            provider=result.get("source", "mock"),
        )
    )
    db.commit()

    audit.record(
        db,
        action="VOICE_NOTE",
        actor_user_id=user.id,
        actor_role="PATIENT",
        detail={"source": result.get("source"), "language": body.language},
        request=request,
    )

    return {
        "transcript": transcript,
        "source": result.get("source"),
        "language": body.language,
        **parsed,
    }


@router.post("/parse-text")
def parse_text(body: SpeakRequest, user: User = Depends(require_patient)):
    """The same mapper, for typed input. Same guarantee: suggestions only.

    Typed Hindi and Kannada work here without any API call at all, because
    the mapper folds in every label and patient phrasing from the ruleset.
    """
    parsed = parse(body.text)
    if not parsed["candidates"] and body.language != "en":
        translated = client.translate_to_english(body.text, body.language)
        if translated.get("source") == "live":
            retry = parse(translated["text"], translated_from=body.language)
            if retry["candidates"]:
                return retry
    return parsed
