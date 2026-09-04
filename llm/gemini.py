"""
Gemini adapter.

The LLM in this system has exactly one job: PHRASING. It receives facts that
have already been decided by the rules engine and passages that have already
been retrieved, and it turns them into a sentence a person can read. It is
never asked what is wrong with anyone, never asked what to do, and never
given a number it did not receive in its input.

That is not a limitation we are apologising for. It is the design. An LLM
that can change a tier is an LLM that can lower one.

FIVE THINGS THIS MODULE ENFORCES

  1. MODE. `mock` is the default and makes zero API calls, so development and
     CI never touch the network or the quota. `live` is opt-in per deployment.

  2. BUDGET. A hard call counter on disk, same pattern as the Sarvam client.
     When it is spent the system degrades to templates rather than failing.

  3. NO PII EGRESS. Every prompt goes through llm.guardrails.scrub before it
     leaves. Names, phones, AIRA codes, hospital numbers and exact dates are
     removed; the model sees an age band and a sex. Verified by test.

  4. LOW TEMPERATURE, CAPPED LENGTH. Phrasing tasks do not need creativity,
     and a 600-token cap makes a runaway generation impossible.

  5. SAFETY SETTINGS. Google's own filters stay at their defaults; we do not
     relax them. A refusal from the platform lands in the same fallback path
     as every other failure.

Every call returns a dict with `source` in {live, mock, unavailable}, so the
caller - and the audit log - can always tell whether a real model was used.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .guardrails import scrub, scrub_names

USAGE_FILE = Path("llm/usage.json")
CACHE_DIR = Path("llm/cache")

# The free tier grants 20 requests per day PER MODEL. That is not a budget you
# can run a demo on with one model, and finding out live on stage is not the
# way to learn it. So: a chain. Each entry has its own daily quota, so a
# rate-limited primary costs one failed call and then the next model answers.
#
# The order is deliberate. The lite models are FASTER - measured at ~0.8s
# against ~25s for the full flash model under quota pressure - and phrasing a
# sentence from supplied facts is exactly the task a lite model is for. We are
# not settling for the small model; it is the right one for the job.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
]

# Errors worth trying the next model for. A malformed request will fail the
# same way on every model, so only capacity and availability errors retry.
RETRYABLE = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "404", "NOT_FOUND")


class BudgetExceeded(RuntimeError):
    pass


class GeminiClient:
    def __init__(
        self,
        api_key: str = "",
        mode: str = "mock",
        model: str = DEFAULT_MODEL,
        max_calls: int = 200,
        timeout: float = 20.0,
        use_cache: bool = True,
    ) -> None:
        self.api_key = api_key
        self.mode = mode
        self.model = model
        self.max_calls = max_calls
        self.timeout = timeout
        self.use_cache = use_cache
        self._client = None
        self.chain = [model] + [m for m in FALLBACK_MODELS if m != model]

    # ── response cache ───────────────────────────────────────────────────
    # A cache is not an optimisation here, it is a quota strategy. The demo
    # asks the same six questions every rehearsal; without this, the fourth
    # rehearsal of the day is a template. Keyed on the exact prompt, so a
    # changed corpus or a changed patient produces a miss, never a stale hit.
    # Deliberately NOT keyed on the model name: a cached answer that already
    # passed verification is just as good whichever model in the chain wrote
    # it, and keying on the model would halve the hit rate every time the
    # primary is rate-limited - exactly when the cache matters most.
    def _cache_key(self, system: str, prompt: str) -> str:
        return hashlib.sha256(f"{system}\x00{prompt}".encode()).hexdigest()[:24]

    def _cache_get(self, system: str, prompt: str) -> dict | None:
        if not self.use_cache:
            return None
        path = CACHE_DIR / f"{self._cache_key(system, prompt)}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        payload["source"] = "cache"
        return payload

    def commit(self, payload: dict) -> None:
        """Write a response to the cache. Called by the ANSWER LOOP, and only
        after verification has passed.

        Caching inside generate() was a bug we shipped for about ten minutes:
        a draft that failed the numeric guard got stored, and every later ask
        of the same question replayed the rejected draft straight back into
        the verifier. A cache must only ever hold text that was good enough
        to send.
        """
        key = payload.get("cache_key")
        if not self.use_cache or not key or not payload.get("text"):
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(
            json.dumps(
                {k: v for k, v in payload.items() if k not in ("prompt_sent", "cache_key")},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # ── budget ───────────────────────────────────────────────────────────
    def _usage(self) -> dict:
        if USAGE_FILE.exists():
            try:
                return json.loads(USAGE_FILE.read_text())
            except json.JSONDecodeError:
                pass
        return {"calls": 0, "failures": 0, "by_task": {}, "tokens_in": 0, "tokens_out": 0}

    def _write(self, usage: dict) -> None:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(json.dumps(usage, indent=2))

    def _spend(self, task: str) -> None:
        usage = self._usage()
        if usage["calls"] >= self.max_calls:
            raise BudgetExceeded(f"Gemini call budget of {self.max_calls} reached")
        usage["calls"] += 1
        usage["by_task"][task] = usage["by_task"].get(task, 0) + 1
        self._write(usage)

    def _record(self, ok: bool, tokens_in: int = 0, tokens_out: int = 0) -> None:
        usage = self._usage()
        if not ok:
            usage["failures"] += 1
        usage["tokens_in"] += tokens_in
        usage["tokens_out"] += tokens_out
        self._write(usage)

    def status(self) -> dict:
        u = self._usage()
        return {
            "mode": self.mode,
            "model": self.model if self.mode == "live" else None,
            "configured": bool(self.api_key),
            "calls_used": u["calls"],
            "call_budget": self.max_calls,
            "failures": u["failures"],
            "by_task": u["by_task"],
            "fallback": "deterministic template composed from the same facts",
        }

    @property
    def available(self) -> bool:
        return self.mode == "live" and bool(self.api_key)

    # ── the call ─────────────────────────────────────────────────────────
    def _sdk(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate(
        self,
        system: str,
        prompt: str,
        task: str = "phrase",
        names_to_remove: list[str] | None = None,
        max_output_tokens: int = 1200,
        temperature: float = 0.2,
        thinking: bool = False,
    ) -> dict:
        """Returns {text, source, removed, latency_ms, reason?}.

        The prompt is scrubbed here rather than by the caller. Callers forget;
        an adapter that scrubs unconditionally cannot.
        """
        cleaned = scrub_names(prompt, names_to_remove or [])
        cleaned, removed = scrub(cleaned)

        cached = self._cache_get(system, cleaned)
        if cached:
            cached["removed"] = removed
            return cached

        if not self.available:
            return {
                "text": None,
                "source": "mock",
                "removed": removed,
                "reason": "mock mode: GEMINI_MODE is not 'live' or no key is set",
                "prompt_sent": cleaned,
            }

        try:
            self._spend(task)
        except BudgetExceeded as exc:
            return {"text": None, "source": "unavailable", "removed": removed, "reason": str(exc)}

        from google.genai import types

        cfg = dict(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            candidate_count=1,
        )
        # Gemini 3.x reasons before it answers, and those thinking tokens come
        # out of the same output budget - which silently truncated our answers
        # mid-sentence until we noticed. Phrasing a sentence from supplied
        # facts needs no reasoning, so it is switched off: cheaper, faster,
        # and the whole budget goes to the answer.
        if not thinking:
            try:
                cfg["thinking_config"] = types.ThinkingConfig(thinking_level="minimal")
            except Exception:
                pass

        attempts: list[str] = []
        for model_name in self.chain:
            started = time.perf_counter()
            try:
                resp = self._sdk().models.generate_content(
                    model=model_name,
                    contents=cleaned,
                    config=types.GenerateContentConfig(**cfg),
                )
                text = (resp.text or "").strip()
                usage = getattr(resp, "usage_metadata", None)
                self._record(
                    ok=bool(text),
                    tokens_in=getattr(usage, "prompt_token_count", 0) or 0,
                    tokens_out=getattr(usage, "candidates_token_count", 0) or 0,
                )
                if not text:
                    attempts.append(f"{model_name}: empty response (possible safety block)")
                    continue
                payload = {
                    "text": text,
                    "source": "live",
                    "model_used": model_name,
                    "removed": removed,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "fallback_chain": attempts,
                    "prompt_sent": cleaned,
                    # The loop hands this back to commit() once the answer has
                    # passed verification. Nothing is cached before then.
                    "cache_key": self._cache_key(system, cleaned),
                }
                return payload
            except Exception as exc:
                self._record(ok=False)
                message = f"{type(exc).__name__}: {exc}"
                attempts.append(f"{model_name}: {message[:120]}")
                if not any(token in message for token in RETRYABLE):
                    break

        # Every failure - network, quota, safety, SDK - lands in the same
        # place: the caller falls back to a template. A chatbot outage must
        # never become a clinical outage.
        return {
            "text": None,
            "source": "unavailable",
            "removed": removed,
            "reason": attempts[-1] if attempts else "no model in the chain answered",
            "fallback_chain": attempts,
        }
