"""
The knowledge corpus.

Every passage AIRA can retrieve lives here or is derived from rules/*.json,
and every one carries a provenance record. There are exactly two kinds:

    kind="quote"    verbatim guideline text. May support a numeric claim.
    kind="summary"  written by us, plain-language. May NEVER support a
                    numeric claim on its own - rag/verify.py enforces that.

That distinction is the whole point. A retrieval system that cannot tell a
guideline from its own paraphrase will eventually put our wording in a
clinician's mouth and attribute it to NICE.

WHERE THE CONTENT COMES FROM

  1. rules/symptoms.json, redflags.json, screening.json - already carry
     `citation` blocks with source, section and quote. Those are lifted
     directly, so the chatbot and the rules engine can never disagree about
     what a guideline says: there is one copy of the text.

  2. LAB_REFERENCE - reference intervals used to interpret an uploaded
     report. Written as summaries with explicit sources, because a value
     outside a reference range is a fact about the lab's range, not a
     diagnosis, and the distinction has to survive into the answer.

  3. PROGRAMME - how the Indian public system actually works: what is free,
     where, who performs it, what to bring. This is the half of the answer
     that decides whether anyone acts on the other half.

  4. SAFETY - the passages the refusal router leans on when it declines.

Nothing here is invented clinical advice. If a passage is our own wording it
says so in its own metadata, and the verifier treats it accordingly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

RULES_DIR = Path("rules")


@dataclass
class Chunk:
    id: str
    text: str
    kind: str  # "quote" | "summary"
    source: str
    section: str | None = None
    topic: str = "general"
    audience: str = "both"  # "patient" | "clinician" | "both"
    languages: list[str] = field(default_factory=lambda: ["en"])
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["languages"] = ",".join(self.languages)
        d["meta"] = json.dumps(self.meta, ensure_ascii=False)
        return d


def _cid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Everything the rules engine already cites
# ─────────────────────────────────────────────────────────────────────────────


def _load(name: str) -> dict:
    path = RULES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def from_rules() -> list[Chunk]:
    """Lift the citation blocks out of the ruleset.

    One copy of the guideline text, shared by the deterministic engine and
    the retrieval layer. If a safe window changes, the chatbot's answer
    changes with it in the same commit.
    """
    out: list[Chunk] = []

    symptoms = _load("symptoms.json")
    for s in symptoms["symptoms"]:
        label = s["label"]["en"]
        cit = s.get("citation") or {}
        quote = (cit.get("quote") or "").strip()
        if quote:
            out.append(
                Chunk(
                    id=_cid("sym", s["code"], "quote"),
                    text=f"{label} ({s['code']}). {quote}",
                    kind="quote",
                    source=cit.get("source", "ruleset"),
                    section=cit.get("section"),
                    topic=s["cluster"],
                    audience="both",
                    meta={
                        "symptom": s["code"],
                        "safe_window_days": s.get("safe_window_days"),
                        "confidence": cit.get("confidence"),
                    },
                )
            )

        # The operational fact a patient actually needs: how long is too long.
        #
        # These fifty passages used to share a long identical preamble, which
        # made them near-indistinguishable to both halves of the retriever: a
        # vague question like "how long is too long" pulled back three random
        # symptoms because the boilerplate matched better than anything
        # specific did. The text is now front-loaded with the symptom's own
        # words and carries no shared filler.
        window = s.get("safe_window_days")
        if window is not None:
            tests = (
                ", ".join(investigation_label(c) for c in s.get("expected_investigations", []))
                or "a clinical assessment"
            )
            phrasing = (s.get("patient_phrasing") or {}).get("en", "")
            out.append(
                Chunk(
                    id=_cid("sym", s["code"], "window"),
                    text=(
                        f"{label}{f' ({phrasing})' if phrasing else ''} lasting more than "
                        f"{window} days has outlasted a self-limiting cause. Next step: {tests}."
                    ),
                    kind="summary",
                    source="AIRA ruleset",
                    section=f"symptoms.json#{s['code']}",
                    topic=s["cluster"],
                    audience="both",
                    meta={"symptom": s["code"], "safe_window_days": window},
                )
            )

        for m in s.get("milestones", []):
            msg = m.get("message", {})
            text_en = msg.get("en") if isinstance(msg, dict) else msg
            if not text_en:
                continue
            out.append(
                Chunk(
                    id=_cid("sym", s["code"], "milestone", str(m["day"])),
                    text=(
                        f"{label}, day {m['day']}: {text_en} "
                        f"(recommended action: {m['action']})"
                    ),
                    kind="quote" if m.get("source") else "summary",
                    source=m.get("source", "AIRA ruleset"),
                    section=f"symptoms.json#{s['code']}@day{m['day']}",
                    topic=s["cluster"],
                    audience="both",
                    meta={"symptom": s["code"], "day": m["day"], "action": m["action"]},
                )
            )

    for c in symptoms.get("combination_rules", []):
        cit = c.get("citation") or {}
        quote = (cit.get("quote") or "").strip()
        if quote:
            out.append(
                Chunk(
                    id=_cid("combo", c["id"]),
                    text=f"{c['id']}: {quote}",
                    kind="quote",
                    source=cit.get("source", "NG12"),
                    section=cit.get("section"),
                    topic=c.get("then", {}).get("site", "general"),
                    audience="clinician",
                    meta={"rule_id": c["id"]},
                )
            )

    flags = _load("redflags.json")
    for f in flags.get("red_flags", []):
        cit = f.get("citation") or {}
        quote = (cit.get("quote") or "").strip()
        body = quote or f.get("clinician") or f.get("patient") or ""
        if not body:
            continue
        out.append(
            Chunk(
                id=_cid("rf", f["id"]),
                text=f"Red flag {f['id']} ({f['symptom']}): {body}",
                kind="quote" if quote else "summary",
                source=cit.get("source", "AIRA ruleset"),
                section=cit.get("section"),
                topic="red_flag",
                audience="both",
                meta={"rule_id": f["id"], "symptom": f["symptom"]},
            )
        )

    screening = _load("screening.json")
    for p in screening.get("programmes", []):
        cit = p.get("citation") or {}
        name = p["name"]["en"] if isinstance(p.get("name"), dict) else p.get("name", p["id"])
        msg = p.get("message", {})
        msg_en = msg.get("en") if isinstance(msg, dict) else msg
        out.append(
            Chunk(
                id=_cid("scr", p["id"]),
                text=(
                    f"{name}. {msg_en} Test: {p.get('test')}. "
                    f"Where: {p.get('location')}. Performed by: {p.get('who_performs')}. "
                    f"Cost to the patient: Rs {p.get('cost', 0)}. "
                    f"Interval: every {p.get('interval_months')} months."
                ),
                kind="summary",
                source="NP-NCD operational guidelines",
                section=p["id"],
                topic="screening",
                audience="patient",
                meta={"programme": p["id"], "cost": p.get("cost", 0)},
            )
        )
        if cit.get("quote"):
            out.append(
                Chunk(
                    id=_cid("scr", p["id"], "quote"),
                    text=cit["quote"],
                    kind="quote",
                    source=cit.get("source", "NP-NCD"),
                    section=cit.get("section"),
                    topic="screening",
                    audience="both",
                    meta={"programme": p["id"]},
                )
            )

    return out


# ─────────────────────────────────────────────────────────────────────────────
# 2. Laboratory reference intervals
#
# Used to interpret an uploaded report. Every entry is a RANGE, never a
# verdict: "below the reference interval" is a fact, "you are anaemic" is a
# diagnosis, and only the first belongs in a retrieved passage.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Investigation codes, in words
# ─────────────────────────────────────────────────────────────────────────────
#
# rules/symptoms.json stores investigations as codes, which is right: a code is
# stable, greppable, and safe to compare. But a code is our filing system, and
# "Next step: upper_gi_endoscopy, h_pylori_test" is our filing system read out
# loud to a woman in Kolar. Worse, it is unusable to the person it is aimed at:
# the whole point of the handoff card is that she can hand it over and be
# understood, and nobody at a district hospital counter reads snake_case.
#
# So: one map, server-side, used by the corpus text, the handoff card and the
# chat. The code stays in the data and travels with the label.

INVESTIGATION_LABEL: dict[str, str] = {
    "biopsy_oral": "biopsy of the mouth",
    "blood_culture": "blood culture",
    "ca125": "CA-125 blood test",
    "cbc": "full blood count",
    "chest_xray": "chest X-ray",
    "clinical_breast_exam": "breast examination",
    "colonoscopy": "colonoscopy (camera test of the large bowel)",
    "ct_abdomen": "CT scan of the abdomen",
    "ct_chest": "CT scan of the chest",
    "cystoscopy": "cystoscopy (camera test of the bladder)",
    "dermatology_exam": "skin specialist examination",
    "dermoscopy": "close examination of the skin lesion",
    "digital_rectal_exam": "rectal examination",
    "endometrial_biopsy": "biopsy of the womb lining",
    "ent_exam": "ear, nose and throat examination",
    "esr": "ESR blood test",
    "fit_test": "stool test for hidden blood",
    "fnac": "needle sample of the lump",
    "h_pylori_test": "test for the stomach bacterium H. pylori",
    "hpv_test": "HPV test",
    "iron_studies": "iron blood tests",
    "laryngoscopy": "examination of the voice box",
    "lft": "liver blood tests",
    "mammogram": "mammogram (breast X-ray)",
    "mri_brain": "MRI scan of the head",
    "neuro_exam": "nervous system examination",
    "opg_xray": "dental X-ray of the whole jaw",
    "oral_visual_exam": "examination of the mouth",
    "pap_smear": "Pap smear",
    "per_rectal_exam": "rectal examination",
    "peripheral_smear": "blood film",
    "psa": "PSA blood test",
    "skin_biopsy": "skin biopsy",
    "speculum_exam": "internal examination",
    "sputum_afb": "sputum test for TB",
    "tumour_markers": "blood markers",
    "ultrasound_abdomen": "ultrasound scan of the abdomen",
    "ultrasound_axilla": "ultrasound scan of the armpit",
    "ultrasound_breast": "ultrasound scan of the breast",
    "ultrasound_kub": "ultrasound scan of the kidneys and bladder",
    "ultrasound_neck": "ultrasound scan of the neck",
    "ultrasound_node": "ultrasound scan of the swollen gland",
    "ultrasound_pelvis": "ultrasound scan of the pelvis",
    "ultrasound_scrotum": "ultrasound scan of the scrotum",
    "upper_gi_endoscopy": "endoscopy (camera test of the food pipe and stomach)",
    "urine_cytology": "urine test for abnormal cells",
    "via": "VIA cervical screening test",
    "xray_local": "X-ray of the affected part",
}


def investigation_label(code: str) -> str:
    """A code with no entry falls back to its own words rather than to
    nothing, so a new investigation added to the ruleset degrades to
    'ct pelvis' and not to a blank."""
    return INVESTIGATION_LABEL.get(code, code.replace("_", " "))


LAB_REFERENCE: list[dict] = [
    {
        "analyte": "haemoglobin",
        "aliases": ["hb", "haemoglobin", "hemoglobin", "hgb"],
        "unit": "g/dL",
        "ranges": {"adult_male": (13.0, 17.0), "adult_female": (12.0, 15.0), "child": (11.5, 15.5)},
        "text": (
            "Haemoglobin reference interval: approximately 13.0-17.0 g/dL in adult men, "
            "12.0-15.0 g/dL in adult women and 11.5-15.5 g/dL in children. The World Health "
            "Organization defines anaemia as haemoglobin below 13 g/dL in men and below 12 g/dL "
            "in non-pregnant women. A low haemoglobin has many causes, the commonest by far in "
            "India being iron deficiency; it is not by itself evidence of cancer. Persistent "
            "unexplained anaemia that does not respond to iron is the finding that warrants "
            "investigation."
        ),
        "source": "WHO haemoglobin thresholds; standard laboratory reference intervals",
    },
    {
        "analyte": "total leucocyte count",
        "aliases": ["tlc", "wbc", "white blood cell", "leucocyte", "leukocyte"],
        "unit": "cells/µL",
        "ranges": {"adult": (4000, 11000), "child": (5000, 15000)},
        "text": (
            "Total leucocyte count reference interval: approximately 4,000-11,000 cells per "
            "microlitre in adults and 5,000-15,000 in young children. A markedly raised or "
            "markedly reduced count, particularly alongside a low haemoglobin and a low platelet "
            "count, is the combination that prompts urgent haematology review in a child with "
            "prolonged fever."
        ),
        "source": "Standard laboratory reference intervals; NICE NG12 haematological cancers",
    },
    {
        "analyte": "platelet count",
        "aliases": ["platelet", "plt", "thrombocyte"],
        "unit": "cells/µL",
        "ranges": {"all": (150000, 450000)},
        "text": (
            "Platelet count reference interval: approximately 150,000-450,000 per microlitre. "
            "A low platelet count together with a low haemoglobin and an abnormal white cell "
            "count is the pattern that requires same-day discussion rather than a repeat test "
            "in a fortnight."
        ),
        "source": "Standard laboratory reference intervals",
    },
    {
        "analyte": "ESR",
        "aliases": ["esr", "erythrocyte sedimentation"],
        "unit": "mm/hr",
        "ranges": {"adult_male": (0, 15), "adult_female": (0, 20)},
        "text": (
            "Erythrocyte sedimentation rate reference interval: approximately 0-15 mm/hr in men "
            "and 0-20 mm/hr in women. ESR is a non-specific marker of inflammation. A raised ESR "
            "narrows nothing on its own and must never be reported as suggestive of cancer."
        ),
        "source": "Standard laboratory reference intervals",
    },
    {
        "analyte": "sputum AFB",
        "aliases": ["afb", "sputum", "acid fast", "cbnaat", "genexpert", "ntep"],
        "unit": "result",
        "ranges": {},
        "text": (
            "Under India's National Tuberculosis Elimination Programme, a cough lasting two weeks "
            "or more defines a presumptive tuberculosis case and triggers sputum examination, now "
            "usually by rapid molecular test. A NEGATIVE sputum result in someone whose cough "
            "persists does not close the question: it removes the commonest explanation and makes "
            "chest imaging the next step. Repeated courses of empirical anti-tuberculosis "
            "treatment without imaging is the specific pattern associated with late-stage lung "
            "cancer presentation in India."
        ),
        "source": "NTEP presumptive TB definition; NICE NG12 1.1.2",
    },
    {
        "analyte": "chest x-ray",
        "aliases": ["chest xray", "chest x-ray", "cxr", "chest radiograph"],
        "unit": "report",
        "ranges": {},
        "text": (
            "NICE NG12 recommends an urgent chest X-ray, to be performed within two weeks, to "
            "assess for lung cancer in people aged 40 and over who have two or more unexplained "
            "symptoms, or who have ever smoked and have one or more unexplained symptoms. A "
            "chest X-ray reported as normal does not exclude lung cancer where symptoms persist."
        ),
        "source": "NICE NG12",
        "section": "1.1.2",
    },
    {
        "analyte": "upper GI endoscopy",
        "aliases": ["endoscopy", "ogd", "upper gi", "gastroscopy"],
        "unit": "report",
        "ranges": {},
        "text": (
            "NICE NG12 recommends urgent direct-access upper gastrointestinal endoscopy for "
            "people with dysphagia, and for people aged 55 and over with weight loss and any of "
            "upper abdominal pain, reflux or dyspepsia. Dyspepsia that has failed to settle on "
            "two courses of acid suppression is the presentation this project was built around."
        ),
        "source": "NICE NG12",
        "section": "1.2.1",
    },
    {
        "analyte": "biopsy",
        "aliases": ["biopsy", "histopathology", "fnac", "cytology"],
        "unit": "report",
        "ranges": {},
        "text": (
            "Histopathology is the only investigation that establishes or excludes a cancer "
            "diagnosis. Imaging, blood tests and clinical examination can raise or lower "
            "suspicion; none of them settles it. Any AIRA output that appears to settle it is a "
            "defect."
        ),
        "source": "General oncology principle",
    },
]


def from_labs() -> list[Chunk]:
    out = []
    for entry in LAB_REFERENCE:
        out.append(
            Chunk(
                id=_cid("lab", entry["analyte"]),
                text=entry["text"],
                kind="quote" if entry.get("section") else "summary",
                source=entry["source"],
                section=entry.get("section"),
                topic="investigation",
                audience="both",
                meta={
                    "analyte": entry["analyte"],
                    "aliases": entry["aliases"],
                    "unit": entry["unit"],
                    "ranges": {k: list(v) for k, v in entry.get("ranges", {}).items()},
                },
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. How the Indian public system actually works
# ─────────────────────────────────────────────────────────────────────────────

PROGRAMME: list[dict] = [
    {
        "topic": "cost",
        "audience": "patient",
        "source": "Ayushman Bharat PM-JAY scheme documents",
        "text": (
            "Ayushman Bharat PM-JAY provides cover of up to Rs 5 lakh per family per year for "
            "secondary and tertiary hospitalisation, including cancer treatment, at empanelled "
            "public and private hospitals. Eligibility is by household, not by individual "
            "application, and is checked against the scheme database. Diagnosis and treatment "
            "at a government hospital under this scheme should not require money at the counter. "
            "If you are asked for money, that is worth questioning."
        ),
    },
    {
        "topic": "cost",
        "audience": "patient",
        "source": "NP-NCD operational guidelines; NTEP",
        "text": (
            "Screening under the National Programme for Prevention and Control of "
            "Non-Communicable Diseases is free at sub-centres and Ayushman Bharat Health and "
            "Wellness Centres. Tuberculosis testing and treatment under the National "
            "Tuberculosis Elimination Programme is free. Cost is one of the largest reasons "
            "people delay presenting; knowing what is free changes what people do."
        ),
    },
    {
        "topic": "pathway",
        "audience": "patient",
        "source": "AIRA design note",
        "text": (
            "If a symptom has lasted longer than expected, the useful thing to say at the health "
            "centre is not 'I think I have cancer'. It is: how long it has lasted, what has "
            "already been tried, and that it has not worked. That is exactly what the AIRA "
            "handoff card puts on one page, so the conversation starts from facts instead of "
            "from fear."
        ),
    },
    {
        "topic": "pathway",
        "audience": "patient",
        "source": "Aarhus Statement on early cancer diagnosis research",
        "text": (
            "The delay between a symptom starting and a diagnosis being made has two parts. The "
            "patient interval runs from noticing a symptom to first seeking care. The diagnostic "
            "interval runs from that first contact to diagnosis. Both matter, and interventions "
            "that address only one of them tend to disappoint. AIRA measures both: it prompts "
            "someone who has not sought care, and it surfaces repeated contacts where nothing "
            "was investigated."
        ),
    },
    {
        "topic": "risk",
        "audience": "patient",
        "source": "IARC monographs; NFHS-5",
        "text": (
            "Smokeless tobacco - gutka, khaini, paan masala, betel quid with tobacco - is a "
            "cause of oral cancer, not merely an association. India carries roughly a quarter of "
            "the world's oral cancer burden, and smokeless tobacco is the dominant reason. "
            "Stopping reduces risk; the reduction accrues over years rather than immediately, "
            "which is an argument for stopping sooner, not for not bothering."
        ),
    },
    {
        "topic": "risk",
        "audience": "patient",
        "source": "WHO / IARC HPV and cervical cancer",
        "text": (
            "Nearly all cervical cancer is caused by persistent infection with high-risk human "
            "papillomavirus. HPV vaccination in girls before exposure, and screening in adult "
            "women, together make cervical cancer one of the most preventable cancers there is. "
            "India's programme offers both."
        ),
    },
    {
        "topic": "screening",
        "audience": "patient",
        "source": "NP-NCD operational guidelines",
        "text": (
            "Screening means testing someone who feels well, to find disease before it causes "
            "symptoms. It is not the same as investigating a symptom. Being invited for "
            "screening does not mean anyone suspects anything is wrong with you, and a screening "
            "test that finds nothing is the expected result, not a wasted trip."
        ),
    },
    {
        "topic": "dignity",
        "audience": "patient",
        "source": "AIRA design note informed by NGO field interviews",
        "text": (
            "You may ask for a female health worker for a breast or cervical examination, and "
            "you may ask for a private room with the door closed. Both are your right and both "
            "are normal requests. Being told a service is unavailable at that moment is a reason "
            "to ask when it will be available, not a reason to go home."
        ),
    },
]


def from_programme() -> list[Chunk]:
    return [
        Chunk(
            id=_cid("prog", p["topic"], p["text"][:40]),
            text=p["text"],
            kind="summary",
            source=p["source"],
            topic=p["topic"],
            audience=p.get("audience", "both"),
        )
        for p in PROGRAMME
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 4. What AIRA is, and what it refuses to be
# ─────────────────────────────────────────────────────────────────────────────

SAFETY: list[dict] = [
    {
        "topic": "scope",
        "text": (
            "AIRA does not diagnose. It cannot tell anyone whether they have cancer, and no "
            "answer it gives should be read that way. What it does is track how long a symptom "
            "has lasted, what has already been tried, and whether anything has ever been "
            "investigated, and then compare that history against published referral guidance. "
            "Only a clinician, with a test, can diagnose."
        ),
    },
    {
        "topic": "scope",
        "text": (
            "AIRA does not recommend medicines, doses, or whether to stop a treatment someone "
            "has been prescribed. Those decisions belong to the prescribing clinician, who knows "
            "things about the patient that this system does not and cannot."
        ),
    },
    {
        "topic": "scope",
        "text": (
            "AIRA cannot interpret an image. It does not read X-rays, scans or photographs, and "
            "it does not accept them as evidence of anything. Where a report has been typed out, "
            "it can read the words in the report and tell you what the reference interval for "
            "that test is - which is a different and much smaller claim."
        ),
    },
    {
        "topic": "emergency",
        "text": (
            "Some things need help today, not an appointment. Heavy bleeding that will not stop, "
            "sudden severe breathlessness, chest pain with sweating, a first seizure, sudden "
            "weakness on one side of the body, or an inability to pass urine at all. If any of "
            "these is happening, go to the nearest hospital emergency department now. Do not "
            "wait for an answer from an application."
        ),
    },
    {
        "topic": "uncertainty",
        "text": (
            "Most people with a long-lasting symptom do not have cancer. Cough, indigestion and "
            "tiredness are overwhelmingly caused by something else, and the base rate of "
            "malignancy in these presentations in primary care is low - typically well under "
            "three in a hundred. The reason to investigate a symptom that has outlasted its "
            "usual course is not that cancer is likely. It is that it is checkable, and being "
            "checked early is what changes the outcome."
        ),
    },
]


def from_safety() -> list[Chunk]:
    return [
        Chunk(
            id=_cid("safe", s["topic"], s["text"][:40]),
            text=s["text"],
            kind="summary",
            source="AIRA safety policy",
            topic=s["topic"],
            audience="both",
        )
        for s in SAFETY
    ]


# ─────────────────────────────────────────────────────────────────────────────


def build() -> list[Chunk]:
    chunks = from_rules() + from_labs() + from_programme() + from_safety()
    seen: dict[str, Chunk] = {}
    for c in chunks:
        seen[c.id] = c
    return list(seen.values())


def stats(chunks: list[Chunk]) -> str:
    by_kind: dict[str, int] = {}
    by_topic: dict[str, int] = {}
    for c in chunks:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        by_topic[c.topic] = by_topic.get(c.topic, 0) + 1
    lines = [f"{len(chunks)} chunks", f"  by kind  {by_kind}", "  by topic"]
    for t, n in sorted(by_topic.items(), key=lambda kv: -kv[1]):
        lines.append(f"    {t:<16} {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    cs = build()
    print(stats(cs))
