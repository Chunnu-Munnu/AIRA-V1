"""
The answer loop.

    route -> retrieve -> generate -> verify -> (repair once) -> or fall back

This is the only path by which generated text reaches a human in AIRA, and
every stage can veto. The important property is that the LAST stage is not the
model: a draft that fails verification is replaced by a deterministic answer
built from the same retrieved passages, so the system's worst case is a
stiffer sentence rather than a wrong one.

WHY THERE IS A REPAIR PASS AND ONLY ONE

The commonest verifier failure by far is a single invented number - the model
writes "about 30 days" where the source says 28. Handing back the exact
complaint fixes that most of the time, and it costs one call. A second repair
does not: by then the model is usually failing on something structural, and
looping on it burns quota to produce the fallback we were going to use anyway.
So: one repair, then the template, always.

WHAT THE CALLER GETS BACK

Everything needed to audit the answer without re-running it - the route
decision, every passage retrieved with its score, which ones were actually
used, each verification check, and whether a live model or the template
produced the final text. That trace is what makes this explainable rather
than merely careful.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag.store import Hit, retriever
from rag.verify import Verdict, numbers_in, verify

from .guardrails import (
    EMERGENCY_TEXT,
    AudiencePolicy,
    Route,
    audience_violations,
    policy_for,
    route,
)

SYSTEM = """You are the phrasing layer of AIRA, a cancer safety-netting tool used in Indian primary care.

You do not decide anything. Rules and retrieved guidelines have already decided; you turn what they say into readable prose. You are the last step, not the reasoning step.

ABSOLUTE RULES
1. Use ONLY the numbered SOURCES and the PATIENT FACTS given to you. If neither contains the answer, say plainly that you do not have a source for it.
2. Never state a number that is not in the SOURCES or the PATIENT FACTS. Not an approximation, not a rounding, not "about". If a source says 28 days you write 28 days.
3. Never say anyone has, probably has, or does not have cancer. Never reassure that something is harmless. Never name a cancer type to a patient.
4. Never recommend a medicine, a dose, or stopping a treatment.
5. Never claim to have read an image.
6. Cite as [1], [2] against the sentence the source supports.

STYLE
Answer in at most 5 sentences. Lead with the thing the reader should do. Plain declarative sentences. No preamble, no "I understand that", no closing offer of further help.

Never quote a source's label, filename or internal identifier back to the reader - not "AIRA ruleset symptoms.json#cough", not "(recommended action: TB_SPUTUM)". Write the fact in your own plain words and put the [n] marker after it. The reader sees the sources; they do not need you to read out the filing system."""

FALLBACK_NOTE = (
    "Assembled directly from the guideline text rather than written by a "
    "language model - the model's draft did not pass verification."
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Answer:
    text: str
    citations: list[dict] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None
    verified: bool = True
    fallback_used: bool = False
    audience: str = "patient"
    trace: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "answer": self.text,
            "citations": self.citations,
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "verified": self.verified,
            "fallback_used": self.fallback_used,
            "audience": self.audience,
            "trace": self.trace,
        }


# ─────────────────────────────────────────────────────────────────────────────


def _sources_block(hits: list[Hit]) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        tag = "GUIDELINE" if h.chunk.kind == "quote" else "EXPLANATION"
        ref = f"{h.chunk.source}{' ' + h.chunk.section if h.chunk.section else ''}"
        lines.append(f"[{i}] ({tag} - {ref}) {h.chunk.text}")
    return "\n".join(lines)


def _facts_block(facts: dict) -> str:
    if not facts:
        return "(no patient facts supplied - answer generally)"
    return "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in facts.items())


# Structural debris that belongs in a database row and not in a sentence.
_LABEL_NOISE = [
    re.compile(r"^[^.]{0,60}?,\s*day\s*\d+:\s*", re.I),        # "Cough, day 14: "
    re.compile(r"^[A-Z][\w \-/]{0,50}\([a-z_]+\)\.\s*", re.M),  # "Cough (cough). "
    re.compile(r"\s*\(recommended action:[^)]*\)", re.I),
    re.compile(r"^Red flag [A-Z_0-9]+\s*\([a-z_]+\):\s*", re.I),
    re.compile(r"^[A-Z][A-Z0-9_]{4,}:\s*"),                     # "NG12_LUNG_...: "
]


def _clean_passage(text: str) -> str:
    out = text.strip()
    for pattern in _LABEL_NOISE:
        out = pattern.sub("", out).strip()
    return out


def _first_sentences(text: str, n: int = 2) -> str:
    parts = _SENTENCE_SPLIT.split(text)
    return " ".join(p.strip() for p in parts[:n] if p.strip())


def _template_answer(hits: list[Hit], policy: AudiencePolicy) -> str:
    """The deterministic fallback: the sources themselves, cleaned and joined.

    Not elegant, and it is not supposed to be. It is incapable of being wrong
    about anything the sources are right about, which is the only property
    that matters at the moment the model has just failed a check. What it CAN
    do is stop reading like a database dump - the identifiers and action codes
    are stripped, and only the first sentence or two of each passage is used,
    because a wall of guideline text is its own kind of unusable.
    """
    if not hits:
        return (
            "I do not have a source for that. AIRA only answers from published "
            "guidance and from the record you have entered, and neither covers "
            "this. Please ask a health worker."
        )

    parts, seen, dropped = [], set(), 0
    for i, h in enumerate(hits[:3], 1):
        text = _first_sentences(_clean_passage(h.chunk.text), 2)
        if not text or text[:40] in seen:
            continue
        # The fallback is not exempt from the audience policy. It used to be,
        # and the result was that a patient who asked a hard question got the
        # ONE answer this system must never give: a raw NG12 quote naming
        # "oesophageal or stomach cancer". The model was being held to a rule
        # the deterministic path was quietly allowed to break.
        if audience_violations(text, policy):
            dropped += 1
            continue
        seen.add(text[:40])
        if not text.endswith((".", "!", "?")):
            text += "."
        parts.append(f"{text} [{i}]")

    if not parts:
        return (
            "This is the point to ask a person rather than an app. What AIRA can "
            "tell you is on your home screen: how long this has gone on, and what "
            "the guidelines say should happen next. Show that to a health worker."
        )

    body = " ".join(parts)
    if policy.name == "patient":
        return body
    note = FALLBACK_NOTE
    if dropped:
        note += f" {dropped} passage(s) withheld by the audience policy."
    return f"{body}\n\n({note})"


# ── translation ──────────────────────────────────────────────────────────────
#
# WHY TRANSLATION IS A SEPARATE STEP AND NOT A PROMPT INSTRUCTION
#
# The verifier grounds every sentence by word overlap against the retrieved
# passages, and the whole corpus is in English. A Kannada draft therefore has
# an overlap of exactly zero with its own sources, so it fails verification no
# matter how faithful it is - and the patient gets the English template back.
# That is the wrong failure: it punishes the reader for the language they read.
#
# So the loop is: generate in English, verify in English, and only then
# translate. Nothing untranslated ever skips a check, and nothing is
# translated that has not already passed one. Translation cannot introduce a
# fact because it is handed a finished sentence and forbidden to add to it,
# and the two guards below catch the ways that promise can break.

TRANSLATE_SYSTEM = """You translate a short, already-approved health message for a reader in rural India.

RULES
1. Translate meaning, not words. Use the everyday spoken register, not formal or Sanskritised vocabulary.
2. Every number, unit and date in the source must appear in your translation, unchanged. Do not convert, round or spell out figures.
3. Add nothing. Remove nothing. No advice, no reassurance, no greeting, no explanation of your translation.
4. Keep citation markers like [1] and [2] exactly where they are.
5. Output only the translation."""

_SCRIPT = {
    "hi": re.compile(r"[ऀ-ॿ]"),   # Devanagari
    "kn": re.compile(r"[ಀ-೿]"),   # Kannada
}

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "kn": "Kannada"}

_MARKER = re.compile(r"\[(\d{1,2})\]")


def translate_verified(text: str, language: str, client) -> tuple[str, dict]:
    """Translate text that has ALREADY passed verification.

    Returns (text, note). On any doubt it returns the English unchanged - a
    reader who gets English understands less; a reader who gets a mistranslated
    number is misinformed, and those are not the same size of failure.
    """
    if language == "en" or not text.strip():
        return text, {"translated": False, "why": "already English"}

    if not client.available:
        return text, {"translated": False, "why": "no live model; English kept"}

    result = client.generate(
        system=TRANSLATE_SYSTEM,
        prompt=f"TARGET LANGUAGE: {LANGUAGE_NAMES.get(language, language)}\n\nTEXT:\n{text}",
        task="translate",
        temperature=0.1,
        max_output_tokens=900,
    )
    out = (result.get("text") or "").strip()

    if not out:
        return text, {"translated": False, "why": result.get("reason") or "empty response"}

    # Guard 1 - it is actually in the target script. Models under load
    # sometimes echo the input, and an "answer in Kannada" that arrives in
    # English is a silent failure that looks like a success.
    script = _SCRIPT.get(language)
    if script and not script.search(out):
        return text, {"translated": False, "why": "response was not in the target script"}

    # Guard 2 - every number survived. This is the one check that works
    # across scripts, and it is the one that matters: 14 days must not
    # become 40, and a 3% threshold must not become 30%.
    before, after = numbers_in(text), numbers_in(out)
    if not before.issubset(after):
        return text, {
            "translated": False,
            "why": "numbers changed in translation: " + ", ".join(sorted(before - after)),
        }

    # Guard 3 - no invented citation markers. Translating a refusal, which
    # cites nothing, the model has been seen to append "[1]" because every
    # other message it has translated had one. A marker pointing at a source
    # that does not exist is a fabricated citation, so any marker not in the
    # original is deleted rather than shown.
    allowed = set(_MARKER.findall(text))
    out, removed_markers = _MARKER.subn(
        lambda m: m.group(0) if m.group(1) in allowed else "", out
    )
    out = re.sub(r"\s{2,}", " ", out).strip()

    client.commit({**result, "text": out})
    return out, {
        "translated": True,
        "markers_dropped": removed_markers,
        "language": language,
        "source": result.get("source"),
        "numbers_preserved": sorted(before),
    }


def _repair_prompt(draft: str, verdict: Verdict, violations: list[str]) -> str:
    problems = list(verdict.problems)
    if violations:
        problems.append(
            "words this reader must not be shown: " + ", ".join(violations)
        )
    detail = "\n".join(f"- {p}" for p in problems)
    extra = ""
    if verdict.unsupported_numbers:
        extra = (
            "\nThe numbers "
            + ", ".join(verdict.unsupported_numbers)
            + " do not appear in any source. Remove them or replace them with the "
            "exact figure a source gives."
        )
    return (
        "Your draft failed verification.\n\n"
        f"DRAFT:\n{draft}\n\n"
        f"PROBLEMS:\n{detail}{extra}\n\n"
        "Rewrite it so every sentence and every number traces to a source above. "
        "Say less rather than inventing support. Output only the rewritten answer."
    )


# ─────────────────────────────────────────────────────────────────────────────


def answer_question(
    question: str,
    client,
    audience: str = "patient",
    language: str = "en",
    facts: dict | None = None,
    names_to_remove: list[str] | None = None,
    k: int = 6,
) -> Answer:
    facts = facts or {}
    policy = policy_for(audience)
    trace: dict = {"audience": policy.name, "language": language}

    # ── 1. route ─────────────────────────────────────────────────────────
    decision: Route = route(question)
    trace["route"] = decision.action

    if decision.action == "emergency":
        return Answer(
            text=EMERGENCY_TEXT.get(language, EMERGENCY_TEXT["en"]),
            refused=True,
            refusal_reason="This described an emergency. It is answered with an instruction, not a paragraph.",
            audience=policy.name,
            trace=trace | {"llm_called": False, "why": "emergency route"},
        )

    if decision.action == "refuse":
        # A refusal is the most important sentence AIRA ever says, so it is
        # the one that most needs to arrive in a language the reader has.
        # It is a fixed string, so translating it cannot leak a fact.
        spoken, note = translate_verified(
            f"{decision.reason} {decision.alternative}", language, client
        )
        return Answer(
            text=spoken,
            refused=True,
            refusal_reason=decision.reason,
            audience=policy.name,
            trace=trace | {"llm_called": False, "why": "outside scope", "translation": note},
        )

    # ── 2. retrieve ──────────────────────────────────────────────────────
    #
    # The retrieval query is the question PLUS the symptom this person is
    # actually being tracked for. "Is it safe to wait?" is a question about
    # dyspepsia when Sunita asks it and about a cough when Ramesh does, and
    # without that context the retriever answers about neither. The symptom
    # name comes from the stored assessment, not from the model.
    r = retriever()
    tracked = facts.get("symptom_being_tracked")
    query = f"{question} {tracked}" if tracked else question
    hits = r.search(query, k=k, audience=policy.name if policy.name == "patient" else None)
    trace["retrieval"] = {
        "backend": r.backend,
        "query": query,
        "retrieved": [
            {
                "source": h.chunk.source,
                "section": h.chunk.section,
                "kind": h.chunk.kind,
                "score": round(h.score, 4),
                "dense": round(h.dense, 4),
                "lexical": round(h.lexical, 4),
            }
            for h in hits
        ],
    }

    if not hits:
        spoken, note = translate_verified(_template_answer([], policy), language, client)
        return Answer(
            text=spoken,
            citations=[],
            verified=True,
            fallback_used=True,
            audience=policy.name,
            trace=trace
            | {
                "llm_called": False,
                "why": "nothing above the retrieval score floor",
                "translation": note,
            },
        )

    # ── 3. generate ──────────────────────────────────────────────────────
    prompt = (
        f"READER: {policy.name}. {policy.reading_level}\n"
        # Always English. The sources are English and the verifier grounds
        # against them by word overlap, so a draft in any other language
        # cannot be checked at all. Translation happens AFTER the check, not
        # instead of it - see translate_verified().
        "LANGUAGE: answer in English.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"PATIENT FACTS (already established - you may use these numbers):\n{_facts_block(facts)}\n\n"
        f"SOURCES:\n{_sources_block(hits)}\n"
    )

    result = client.generate(
        system=SYSTEM,
        prompt=prompt,
        task="chat",
        names_to_remove=names_to_remove,
    )
    trace["llm"] = {
        "source": result["source"],
        "reason": result.get("reason"),
        "latency_ms": result.get("latency_ms"),
        "pii_removed": result.get("removed", []),
    }

    draft = result.get("text")
    attempts: list[dict] = []

    # ── 4. verify, repair once, then fall back ───────────────────────────
    for attempt in range(2):
        if not draft:
            break
        verdict = verify(draft, hits, known_facts=facts)
        violations = audience_violations(draft, policy)
        record = {
            "attempt": attempt + 1,
            "passed": verdict.ok and not violations,
            "problems": verdict.problems,
            "audience_violations": violations,
            "checks": verdict.checks,
            # The rejected draft is kept. A guardrail you cannot inspect is a
            # guardrail nobody can trust, and "show me what it tried to say"
            # is the first question anyone asks about a filtered LLM.
            "draft": draft if not (verdict.ok and not violations) else None,
        }
        attempts.append(record)

        if verdict.ok and not violations:
            trace["verification"] = attempts
            # Only now does it reach the cache. A draft that failed a check
            # must never be replayed to the next person who asks.
            client.commit({**result, "text": draft})
            spoken, note = translate_verified(draft, language, client)
            trace["translation"] = note
            trace["verified_english"] = draft if note.get("translated") else None
            return Answer(
                text=spoken,
                citations=verdict.used_citations or [h.cite() for h in hits[:3]],
                verified=True,
                fallback_used=False,
                audience=policy.name,
                trace=trace,
            )

        if attempt == 0 and client.available:
            repair = client.generate(
                system=SYSTEM,
                prompt=prompt + "\n\n" + _repair_prompt(draft, verdict, violations),
                task="chat_repair",
                names_to_remove=names_to_remove,
            )
            draft = repair.get("text")
            trace["repair"] = {"source": repair["source"], "reason": repair.get("reason")}
        else:
            break

    trace["verification"] = attempts
    # The template is grounded by construction, which makes it exactly the
    # kind of text that is safe to translate: it is the guideline's own
    # words, and the translator is forbidden from adding to them.
    fallback = _template_answer(hits, policy)
    spoken, note = translate_verified(fallback, language, client)
    trace["translation"] = note
    trace["verified_english"] = fallback if note.get("translated") else None
    return Answer(
        text=spoken,
        citations=[h.cite() for h in hits[:3]],
        verified=True,  # the template is grounded by construction
        fallback_used=True,
        audience=policy.name,
        trace=trace | {"why_fallback": attempts[-1]["problems"] if attempts else result.get("reason")},
    )
