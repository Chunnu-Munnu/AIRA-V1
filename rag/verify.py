"""
The grounding verifier.

An LLM answer is a DRAFT until this module passes it. Nothing reaches a
patient or a clinician that has not been through here, and a failed check
produces the template answer instead - never the model's text with a warning
label, because a warning label above a wrong number does not stop anyone
reading the number.

FOUR CHECKS, IN INCREASING ORDER OF HOW BADLY THEY FAIL

  1. BANNED CLAIMS. Diagnosis, exclusion of diagnosis, prognosis, drug and
     dose. These are not phrased-badly problems that a better prompt fixes;
     they are outside what the system is allowed to assert at all, so they
     are matched on the surface and rejected outright.

  2. THE NUMERIC GUARD. Every number in the answer must be traceable: it
     appears in a retrieved passage, or the caller passed it in as a known
     fact about this patient. Fabricated numbers are the single most
     dangerous LLM failure in a clinical setting, because a plausible number
     is indistinguishable from a real one to the reader, and "14 days" versus
     "40 days" is the entire product.

  3. GROUNDING. Each sentence must have meaningful lexical overlap with at
     least one retrieved passage. Crude, and deliberately so: it is a check
     an auditor can run by eye, which a second neural model would not be.

  4. CITATION COVERAGE. At least one retrieved passage must actually have
     been used, or the answer is untethered prose regardless of its content.

WHAT THIS IS NOT

It is not entailment. A sentence can pass all four checks and still be a
subtly wrong reading of the source. What it does guarantee is that every
number came from somewhere we can point at, which is the failure mode that
actually shows up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .store import Hit

# Surface forms that assert something AIRA is not permitted to assert.
# Matched case-insensitively on the rendered answer.
BANNED_PATTERNS: list[tuple[str, str]] = [
    (r"\byou (?:have|are suffering from|are diagnosed with)\b.{0,40}\b(cancer|tumou?r|malignan\w+|carcinoma)\b",
     "asserts a diagnosis"),
    (r"\b(?:you )?(?:do not|don'?t|does not|doesn'?t) have\b.{0,30}\b(cancer|tumou?r|malignan\w+)\b",
     "asserts an exclusion, which no symptom history can support"),
    (r"\b(?:it'?s|it is|this is|that is) (?:definitely|certainly|probably|most likely|clearly|obviously) (?:not )?(?:cancer|malignant|benign)\b",
     "asserts certainty about a diagnosis"),
    (r"\b(?:it is|this is) (?:nothing|harmless|benign)\b",
     "reassures in a way no history can justify"),
    (r"\b(?:stage|grade)\s+(?:[1-4]|i{1,3}v?|iv)\b",
     "assigns a stage, which requires imaging and histology"),
    # A dose, not a concentration. "500 mg twice a day" is a prescription;
    # "8.2 g/dL" is a laboratory result, and the slash is what tells them
    # apart. Without the lookahead this rule rejects every blood report.
    (r"\b\d+\s?(?:mg|ml|mcg|g)\b(?!\s?/)",
     "states a drug dose"),
    (r"\b(?:take|start|stop|increase|reduce)\s+(?:the\s+)?(?:tablet|medicine|dose|drug|antibiotic|chemo\w*)\b",
     "gives a medication instruction"),
    (r"\byou (?:will|are going to) (?:die|be fine|recover|survive)\b",
     "gives a prognosis"),
    (r"\b(?:\d{1,3})\s?%\s+(?:chance|risk|probability) (?:of|that you)\b",
     "states a personal probability of cancer to the reader"),
]

# Numbers that never need a source: small counts, ordinals, years in a date.
ALWAYS_ALLOWED_NUMBERS = {"0", "1", "2", "3", "4", "5", "10", "100"}

# The lookbehind matters more than it looks. Without it, "NG12" yields the
# number 12, the guard cannot find 12 in any source, and a perfectly cited
# answer is rejected for quoting the name of the guideline it is citing.
_NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?")
# A guideline section - "NG12 1.2.1" - is an identifier, not a quantity. It
# has to be lifted out before the numeric guard runs, or the verifier reads
# "1.2" out of "1.2.1" and rejects a correctly cited answer. It gets its own,
# stricter check instead: a section the model cites must be one it was given,
# which catches an invented guideline reference.
_REFERENCE = re.compile(r"\b\d+(?:\.\d+){1,}\b")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "these",
    "those", "you", "your", "we", "our", "they", "them", "has", "have", "had",
    "not", "no", "can", "may", "will", "should", "would", "at", "by", "with",
    "as", "from", "than", "then", "so", "what", "which", "who", "when", "how",
    "more", "most", "any", "all", "one", "two", "there", "their", "about",
}

MIN_SENTENCE_OVERLAP = 0.34
MIN_UNION_OVERLAP = 0.62


@dataclass
class Verdict:
    ok: bool
    problems: list[str] = field(default_factory=list)
    ungrounded_sentences: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    used_citations: list[dict] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "verified": self.ok,
            "problems": self.problems,
            "ungrounded_sentences": self.ungrounded_sentences,
            "unsupported_numbers": self.unsupported_numbers,
            "checks": self.checks,
        }


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")


def _numbers(text: str) -> set[str]:
    out = set()
    # "4,000-11,000" must read as two numbers, not four. Without this the
    # guard splits on the comma and then rejects "000" as unsourced, which
    # is a verifier bug that looks exactly like a model hallucination.
    text = _THOUSANDS.sub("", text)
    for m in _NUMBER.findall(text):
        # Normalise "3.0" and "3" to the same token so a source saying "3%"
        # supports an answer saying "3.0%".
        out.add(m.rstrip("0").rstrip(".") if "." in m else m)
    return out


# Public alias. The translation guard in llm/answer.py needs exactly this
# notion of "what numbers does this text assert" and must not grow a second,
# subtly different one - two number parsers is two number parsers to keep in
# agreement, and they will not stay in agreement.
numbers_in = _numbers


def check_banned(answer: str) -> list[str]:
    found = []
    low = answer.lower()
    for pattern, why in BANNED_PATTERNS:
        if re.search(pattern, low):
            found.append(why)
    return found


def verify(
    answer: str,
    hits: list[Hit],
    known_facts: dict | None = None,
    require_quote_for_numbers: bool = True,
) -> Verdict:
    """`known_facts` carries numbers the CALLER already knows to be true about
    this patient - days elapsed, safe window, visit count - taken from the
    database, not from the model. Those are allowed in the answer without a
    corpus citation, because they did not come from the model in the first
    place."""
    known_facts = known_facts or {}
    problems: list[str] = []

    # ── 1. banned claims ─────────────────────────────────────────────────
    banned = check_banned(answer)
    problems.extend(banned)

    # ── 1b. guideline references must be ones we supplied ────────────────
    allowed_refs: set[str] = set()
    for h in hits:
        if h.chunk.section:
            allowed_refs |= set(_REFERENCE.findall(h.chunk.section))
        allowed_refs |= set(_REFERENCE.findall(h.chunk.text))
    cited_refs = set(_REFERENCE.findall(answer))
    invented_refs = sorted(cited_refs - allowed_refs)
    if invented_refs:
        problems.append(
            "cites guideline section(s) not among the sources: " + ", ".join(invented_refs)
        )
    # Take them out before the numeric guard sees them.
    answer_numeric = _REFERENCE.sub(" ", answer)

    # ── 2. numeric guard ─────────────────────────────────────────────────
    sourced_numbers: set[str] = set()
    for h in hits:
        # Section identifiers are stripped from the source side too, for the
        # same reason they are stripped from the answer.
        if require_quote_for_numbers and h.chunk.kind != "quote":
            # A summary is our own wording. It may explain, but it may not be
            # the sole authority for a figure that ends up in front of a
            # clinician. Numbers ride on quotes.
            continue
        sourced_numbers |= _numbers(_REFERENCE.sub(" ", h.chunk.text))
    for h in hits:
        # Safe-window numbers live in chunk metadata even when the passage is
        # a summary; those come from the ruleset, which is authoritative.
        for key in ("safe_window_days", "day", "cost"):
            if h.chunk.meta.get(key) is not None:
                sourced_numbers.add(str(h.chunk.meta[key]))

    fact_numbers = {str(v) for v in known_facts.values() if isinstance(v, (int, float))}
    fact_numbers |= {str(int(v)) for v in known_facts.values() if isinstance(v, float) and v.is_integer()}

    unsupported = sorted(
        n
        for n in _numbers(answer_numeric)
        if n not in sourced_numbers
        and n not in fact_numbers
        and n not in ALWAYS_ALLOWED_NUMBERS
    )
    if unsupported:
        problems.append(f"numbers with no source: {', '.join(unsupported)}")

    # ── 3. sentence grounding ────────────────────────────────────────────
    passage_words = [_content_words(h.chunk.text) for h in hits]
    union_words: set[str] = set().union(*passage_words) if passage_words else set()
    ungrounded: list[str] = []
    used: set[int] = set()

    for sentence in _SENTENCE.split(answer.strip()):
        s = sentence.strip()
        if len(s) < 25:
            continue
        words = _content_words(s)
        if not words:
            continue
        best, best_i = 0.0, -1
        for i, pw in enumerate(passage_words):
            if not pw:
                continue
            overlap = len(words & pw) / len(words)
            if overlap > best:
                best, best_i = overlap, i
        if best >= MIN_SENTENCE_OVERLAP:
            used.add(best_i)
            continue
        # A terse clinician sentence often compresses two passages into one -
        # "urgent endoscopy for dysphagia, or over 55 with weight loss" draws
        # on two NG12 clauses and matches neither well on its own. The union
        # check catches that, at a materially higher bar so it cannot become
        # a way for unsupported prose to slip through.
        if union_words and len(words & union_words) / len(words) >= MIN_UNION_OVERLAP:
            used.add(best_i if best_i >= 0 else 0)
            continue
        ungrounded.append(s)

    if ungrounded:
        problems.append(f"{len(ungrounded)} sentence(s) not supported by any retrieved passage")

    # ── 4. citation coverage ─────────────────────────────────────────────
    if hits and not used:
        problems.append("no retrieved passage was actually used")

    return Verdict(
        ok=not problems,
        problems=problems,
        ungrounded_sentences=ungrounded,
        unsupported_numbers=unsupported,
        used_citations=[hits[i].cite() for i in sorted(used)],
        checks={
            "banned_claims": len(banned) == 0,
            "citation_authenticity": not invented_refs,
            "numeric_guard": not unsupported,
            "grounding": not ungrounded,
            "citation_coverage": bool(used) if hits else False,
            "passages_retrieved": len(hits),
            "passages_used": len(used),
        },
    )
