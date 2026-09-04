"""
Reading a medical report.

THE CENTRAL DESIGN DECISION

The numbers are extracted by REGEX, not by a language model. Every value, unit
and date on the page comes out of a deterministic parser whose behaviour can
be read off the source. The reference interval each value is compared against
comes out of the RAG corpus, with a citation. The language model's only job -
if it is available at all - is to turn "haemoglobin 8.2 g/dL, below the
reference interval of 12.0-15.0" into a sentence.

That ordering is the entire anti-hallucination argument for this feature, and
it is stronger than any prompt could be: an LLM cannot invent a lab value it
was never asked to produce. Ask a model to "read this report" and it will
cheerfully return a plausible haemoglobin for a report that does not contain
one. Ask it only to phrase a number the parser already found, and that failure
mode does not exist.

WHAT IT WILL NOT DO

  - It does not read images. A photograph of a report is stored and shown to
    the clinician; nothing is extracted from it and no claim is made about it.
  - It does not diagnose. "Below the reference interval" is a fact about the
    laboratory's range. "Anaemia" is a diagnosis. Only the first is produced.
  - It does not decide the tier. Findings raise a flag for a clinician; the
    rules engine remains the only thing that moves anyone up a ladder.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date

from rag.corpus import LAB_REFERENCE

# ─────────────────────────────────────────────────────────────────────────────
# Text extraction
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_TEXT = {"text/plain", "text/markdown", "text/csv", "application/json"}
SUPPORTED_PDF = {"application/pdf"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}


def extract_text(data: bytes, content_type: str, filename: str = "") -> tuple[str, str]:
    """Returns (text, how). `how` is one of text | pdf | image | unsupported."""
    ct = (content_type or "").split(";")[0].strip().lower()
    name = filename.lower()

    if ct in IMAGE_TYPES or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic")):
        # Deliberate. Optical character recognition on a phone photo of a
        # thermal-printed report is unreliable in exactly the conditions this
        # is used in, and a misread decimal point in a haemoglobin is worse
        # than no reading at all. The file is kept for the clinician to look
        # at with their own eyes.
        return "", "image"

    if ct in SUPPORTED_PDF or name.endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in reader.pages[:20]]
            text = "\n".join(pages).strip()
            # A scanned PDF has pages but no text layer. That is an image in a
            # PDF wrapper and must be treated as one.
            return (text, "pdf") if len(text) > 40 else ("", "image")
        except Exception:
            return "", "unsupported"

    if ct in SUPPORTED_TEXT or name.endswith((".txt", ".md", ".csv", ".json")):
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return data.decode(encoding).strip(), "text"
            except UnicodeDecodeError:
                continue
    return "", "unsupported"


# ─────────────────────────────────────────────────────────────────────────────
# Field extraction
# ─────────────────────────────────────────────────────────────────────────────

# Aliases -> the LAB_REFERENCE entry. Built once from the corpus so there is
# one list of analytes in the project, not two that drift.
ANALYTES: dict[str, dict] = {}
for _entry in LAB_REFERENCE:
    for _alias in _entry["aliases"]:
        ANALYTES[_alias.lower()] = _entry

# Words an Indian lab printout puts between the analyte and its number.
# "Total Leucocyte Count  28,400" is the single commonest CBC line in the
# country, and without this the parser read it as a test that was named but
# not resulted - so a child with a leucocyte count of 28,400 came back with
# nothing abnormal found. Deliberately a CLOSED list: the anchoring is what
# stops "Haemoglobin  Sample ID 4521" being read as a haemoglobin of 4521,
# and a general "skip a couple of words" rule would give that back.
_LABEL_TAIL = (
    r"(?:\s*(?:count|counts|level|levels|value|result|results|total|"
    r"conc|concentration|estimation|test|\(total\)|%))*"
)

_VALUE = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(g\s?/\s?d[lL]|gm?%|mg\s?/\s?d[lL]|cells?\s?/\s?(?:cu ?mm|µ[lL]|ul)|/\s?(?:cu ?mm|µ[lL]|ul)|mm\s?/\s?(?:hr|1st hr)|%|10\^\d+\s?/\s?[µu][lL])?"

DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
]

# Result words that carry meaning without a number.
QUALITATIVE = {
    "positive": "positive",
    "negative": "negative",
    "detected": "positive",
    "not detected": "negative",
    "reactive": "positive",
    "non reactive": "negative",
    "nonreactive": "negative",
    "normal study": "normal",
    "no abnormality": "normal",
    "within normal limits": "normal",
}

IMPRESSION_HEADS = re.compile(
    r"^\s*(impression|conclusion|opinion|comment|advice|summary|findings)\s*[:\-]\s*",
    re.I | re.M,
)


@dataclass
class Finding:
    analyte: str
    raw_label: str
    value: float | None
    text_value: str | None
    unit: str | None
    reference: tuple[float, float] | None
    status: str  # low | normal | high | reported | unknown
    citation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "analyte": self.analyte,
            "raw_label": self.raw_label,
            "value": self.value,
            "text_value": self.text_value,
            "unit": self.unit,
            "reference_low": self.reference[0] if self.reference else None,
            "reference_high": self.reference[1] if self.reference else None,
            "status": self.status,
            "citation": self.citation,
        }


@dataclass
class ParsedReport:
    findings: list[Finding] = field(default_factory=list)
    report_date: date | None = None
    impression: str | None = None
    mentioned_tests: list[str] = field(default_factory=list)
    how: str = "text"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "impression": self.impression,
            "mentioned_tests": self.mentioned_tests,
            "how": self.how,
            "notes": self.notes,
            "abnormal_count": sum(1 for f in self.findings if f.status in ("low", "high")),
        }


def _reference_for(entry: dict, age: int | None, sex: str | None) -> tuple[float, float] | None:
    ranges = entry.get("ranges") or {}
    if not ranges:
        return None
    if age is not None and age < 15 and "child" in ranges:
        return tuple(ranges["child"])
    if sex == "male" and "adult_male" in ranges:
        return tuple(ranges["adult_male"])
    if sex == "female" and "adult_female" in ranges:
        return tuple(ranges["adult_female"])
    for key in ("adult", "all"):
        if key in ranges:
            return tuple(ranges[key])
    # No demographic match: take the widest interval present, so an unknown
    # patient is never flagged abnormal on the strictest possible range.
    lows = [v[0] for v in ranges.values()]
    highs = [v[1] for v in ranges.values()]
    return (min(lows), max(highs))


def _parse_date(text: str) -> date | None:
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            try:
                a, b, c = (int(x) for x in m.groups())
                candidate = date(c, b, a) if c > 31 else date(a, b, c)
            except (ValueError, TypeError):
                continue
            if date(2000, 1, 1) <= candidate <= date.today():
                return candidate
    return None


def parse_report(
    text: str,
    age: int | None = None,
    sex: str | None = None,
    how: str = "text",
) -> ParsedReport:
    report = ParsedReport(how=how)
    if not text.strip():
        if how == "image":
            report.notes.append(
                "This is an image. AIRA does not read images, so nothing was "
                "extracted from it. Your clinician can still open the file."
            )
        else:
            report.notes.append("No readable text was found in this file.")
        return report

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    report.report_date = _parse_date(text)

    seen: set[str] = set()
    for line in lines:
        low = line.lower()
        for alias, entry in ANALYTES.items():
            if alias not in low:
                continue
            if entry["analyte"] in seen:
                continue

            # The value must come immediately after the label, allowing only
            # a colon, a dash, or a short parenthetical like "(Hb)". Anchored
            # at the start of the tail rather than searched, because a loose
            # search reads "Haemoglobin  Sample ID 4521" as a haemoglobin of
            # 4521 - the kind of quiet misparse that ends up on a card.
            tail = low.split(alias, 1)[1]
            m = re.match(
                rf"\s*{_LABEL_TAIL}\s*(?:\([^)]{{0,14}}\))?\s*[:\-=]?\s*{_VALUE}\s*{_UNIT}",
                tail,
            )

            if m:
                raw = m.group(1).replace(",", "")
                try:
                    value = float(raw)
                except ValueError:
                    continue
                ref = _reference_for(entry, age, sex)
                if ref is None:
                    status = "reported"
                elif value < ref[0]:
                    status = "low"
                elif value > ref[1]:
                    status = "high"
                else:
                    status = "normal"
                report.findings.append(
                    Finding(
                        analyte=entry["analyte"],
                        raw_label=line[:120],
                        value=value,
                        text_value=None,
                        unit=(m.group(2) or entry.get("unit") or "").strip() or None,
                        reference=ref,
                        status=status,
                        citation={"source": entry["source"], "quote": entry["text"]},
                    )
                )
                seen.add(entry["analyte"])
                break

            qualitative = next((v for k, v in QUALITATIVE.items() if k in tail), None)
            if qualitative:
                report.findings.append(
                    Finding(
                        analyte=entry["analyte"],
                        raw_label=line[:120],
                        value=None,
                        text_value=qualitative,
                        unit=None,
                        reference=None,
                        status="reported",
                        citation={"source": entry["source"], "quote": entry["text"]},
                    )
                )
                seen.add(entry["analyte"])
                break

            # The test is named but carries no result on this line. Worth
            # recording: "a chest X-ray was done" is itself the fact that
            # breaks the Loop Detector's investigation-gap condition.
            if entry["analyte"] not in report.mentioned_tests:
                report.mentioned_tests.append(entry["analyte"])
            break

    m = IMPRESSION_HEADS.search(text)
    if m:
        tail = text[m.end():].strip()
        report.impression = " ".join(tail.split())[:600] or None

    if not report.findings and not report.mentioned_tests:
        report.notes.append(
            "No laboratory values that AIRA recognises were found. It only "
            "reads a fixed list of common tests, and everything else in the "
            "report is left for a clinician."
        )
    return report


# ─────────────────────────────────────────────────────────────────────────────
# What a finding is allowed to mean
# ─────────────────────────────────────────────────────────────────────────────

STATUS_PATIENT = {
    "low": "below the usual range",
    "high": "above the usual range",
    "normal": "in the usual range",
    "reported": "recorded",
    "unknown": "recorded",
}

STATUS_CLINICIAN = {
    "low": "BELOW reference",
    "high": "ABOVE reference",
    "normal": "within reference",
    "reported": "reported",
    "unknown": "unparsed",
}


def summarise(report: ParsedReport, audience: str = "patient") -> str:
    """A deterministic summary. This is what gets shown when no model is
    available, and it is also the ceiling on what a model is allowed to say -
    the LLM rephrases this, it does not add to it."""
    if not report.findings:
        return (
            "Nothing was read from this document automatically. "
            + (report.notes[0] if report.notes else "")
        ).strip()

    words = STATUS_PATIENT if audience == "patient" else STATUS_CLINICIAN
    parts = []
    for f in report.findings:
        shown = f.text_value if f.value is None else f"{f.value:g}{' ' + f.unit if f.unit else ''}"
        if audience == "clinician" and f.reference:
            parts.append(
                f"{f.analyte} {shown} [{words[f.status]}; ref {f.reference[0]:g}-{f.reference[1]:g}]"
            )
        else:
            parts.append(f"{f.analyte} was {shown}, {words[f.status]}")

    body = "; ".join(parts) + "."
    abnormal = [f for f in report.findings if f.status in ("low", "high")]
    if not abnormal:
        return body + (
            " Nothing here is outside the usual range."
            if audience == "patient"
            else " No values outside reference."
        )
    if audience == "patient":
        return (
            body
            + " A result outside the usual range has many possible causes and is not a "
            "diagnosis. Show this to your doctor, who can say what it means for you."
        )
    return body + f" {len(abnormal)} value(s) outside reference."
