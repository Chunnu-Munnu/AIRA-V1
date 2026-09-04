"""
Sarvam AI adapter with a hard credit budget.

The account has 100 credits. Burning them during development would be an
entirely self-inflicted demo failure, so this client is built around three
rules:

  1. SARVAM_MODE=mock is the default. Development makes ZERO API calls.
  2. Every fixed phrase - the consent notice, all five check-back options,
     the escalation message - is rendered ONCE into voice/audio/prerendered/
     and replayed from disk forever. The demo therefore plays genuine Sarvam
     audio at a cost of zero credits per run.
  3. A hard counter caps live calls. When it is reached the client degrades to
     the browser's Web Speech API rather than failing.

The only thing that costs credits at showtime is the single live "speak your
symptom" moment, which is about three calls per rehearsal.
"""

from __future__ import annotations

import base64
import json
import hashlib
from pathlib import Path
from typing import Literal

import httpx

Language = Literal["en", "hi", "kn"]

SARVAM_LOCALE = {"en": "en-IN", "hi": "hi-IN", "kn": "kn-IN"}

BASE = "https://api.sarvam.ai"
AUDIO_DIR = Path("voice/audio")
PRERENDERED = AUDIO_DIR / "prerendered"
COUNTER_FILE = AUDIO_DIR / "credit_usage.json"


class SarvamBudgetExceeded(RuntimeError):
    pass


class SarvamClient:
    def __init__(self, api_key: str, mode: str = "mock", max_live_calls: int = 30):
        self.api_key = api_key
        self.mode = mode
        self.max_live_calls = max_live_calls
        PRERENDERED.mkdir(parents=True, exist_ok=True)

    # ── credit accounting ────────────────────────────────────────────────
    def _usage(self) -> dict:
        if COUNTER_FILE.exists():
            try:
                return json.loads(COUNTER_FILE.read_text())
            except json.JSONDecodeError:
                pass
        return {"live_calls": 0, "by_endpoint": {}}

    def _spend(self, endpoint: str) -> None:
        usage = self._usage()
        if usage["live_calls"] >= self.max_live_calls:
            raise SarvamBudgetExceeded(
                f"live call budget of {self.max_live_calls} reached. "
                "falling back to browser speech."
            )
        usage["live_calls"] += 1
        usage["by_endpoint"][endpoint] = usage["by_endpoint"].get(endpoint, 0) + 1
        COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
        COUNTER_FILE.write_text(json.dumps(usage, indent=2))

    def credits_used(self) -> dict:
        return self._usage()

    # ── text to speech ───────────────────────────────────────────────────
    def _cache_path(self, text: str, language: Language, key: str | None) -> Path:
        name = key or hashlib.sha256(f"{language}:{text}".encode()).hexdigest()[:16]
        return PRERENDERED / f"{name}__{language}.wav"

    def speak(
        self, text: str, language: Language = "en", cache_key: str | None = None
    ) -> dict:
        """Returns {audio_base64, source}. `source` is one of
        prerendered | live | mock | unavailable."""
        path = self._cache_path(text, language, cache_key)
        if path.exists():
            return {
                "audio_base64": base64.b64encode(path.read_bytes()).decode(),
                "source": "prerendered",
                "cache_file": str(path),
            }

        if self.mode != "live" or not self.api_key:
            # Mock mode returns no audio at all. The frontend then falls back
            # to the browser's speechSynthesis, which is free and offline.
            return {"audio_base64": None, "source": "mock", "text": text}

        try:
            self._spend("text-to-speech")
        except SarvamBudgetExceeded as exc:
            return {"audio_base64": None, "source": "unavailable", "reason": str(exc)}

        resp = httpx.post(
            f"{BASE}/text-to-speech",
            headers={"api-subscription-key": self.api_key},
            json={
                "inputs": [text],
                "target_language_code": SARVAM_LOCALE[language],
                "speaker": "meera",
                "model": "bulbul:v1",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        audio_b64 = resp.json()["audios"][0]

        # Persist so this phrase is never paid for twice.
        path.write_bytes(base64.b64decode(audio_b64))
        return {"audio_base64": audio_b64, "source": "live", "cache_file": str(path)}

    # ── speech to text ───────────────────────────────────────────────────
    def transcribe(self, audio_bytes: bytes, language: Language = "en") -> dict:
        """Hindi and Kannada speech to text.

        This is the call the browser cannot make well. Chrome's Web Speech API
        supports hi-IN and kn-IN nominally, but it is unreliable on the
        low-end Android devices this is aimed at and needs Google servers
        anyway. Sarvam's Saarika is trained on Indian speech and handles the
        code-mixing that people actually use - "do hafte se khaansi hai" with
        an English number in the middle.

        It is also the only genuinely expensive call in the product, which is
        why the browser path stays the default and this fires only when the
        patient explicitly chooses "record in my language".
        """
        if self.mode != "live" or not self.api_key:
            return {
                "transcript": "",
                "language": language,
                "source": "mock",
                "reason": "SARVAM_MODE is not 'live'. The browser's own speech "
                "recognition is used instead, which costs nothing.",
            }

        try:
            self._spend("speech-to-text")
        except SarvamBudgetExceeded as exc:
            return {"transcript": "", "source": "unavailable", "reason": str(exc)}

        try:
            resp = httpx.post(
                f"{BASE}/speech-to-text",
                headers={"api-subscription-key": self.api_key},
                files={"file": ("audio.wav", audio_bytes, "audio/wav")},
                data={"language_code": SARVAM_LOCALE[language], "model": "saarika:v2.5"},
                timeout=60.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return {
                "transcript": "",
                "source": "unavailable",
                "reason": f"{type(exc).__name__}: {exc}",
            }

        return {
            "transcript": payload.get("transcript", ""),
            "language": payload.get("language_code", SARVAM_LOCALE[language]),
            "source": "live",
        }

    # ── translation ──────────────────────────────────────────────────────
    def translate_to_english(self, text: str, language: Language) -> dict:
        """Indic text to English, for the symptom mapper's benefit.

        Used only as a SECOND pass. The mapper already carries Hindi and
        Kannada phrasings lifted from the ruleset, so the common cases match
        without any network call at all; this exists for the sentence that
        does not match anything, where one credit is a fair price for
        understanding a person who cannot use the tick list.
        """
        if language == "en" or not text.strip():
            return {"text": text, "source": "not-needed"}

        if self.mode != "live" or not self.api_key:
            return {"text": text, "source": "mock"}

        try:
            self._spend("translate")
        except SarvamBudgetExceeded as exc:
            return {"text": text, "source": "unavailable", "reason": str(exc)}

        try:
            resp = httpx.post(
                f"{BASE}/translate",
                headers={"api-subscription-key": self.api_key},
                json={
                    "input": text[:900],
                    "source_language_code": SARVAM_LOCALE[language],
                    "target_language_code": "en-IN",
                    "model": "mayura:v1",
                    "mode": "formal",
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            return {"text": resp.json().get("translated_text", text), "source": "live"}
        except Exception as exc:
            return {"text": text, "source": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
