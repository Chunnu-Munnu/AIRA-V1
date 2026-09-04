# AIRA — AI Risk & Awareness Assistant

**Smart Horizon 2026 · SH-HLT-05** — early cancer detection, misdiagnosis
prevention, and screening awareness.

---

## The problem, in one case

A 42-year-old woman in Kolar has acidity. She sees a doctor, who gives her an
antacid. Ten weeks later she sees a different doctor, who gives her an antacid.
Ten weeks after that, a third, who gives her an antacid.

Nine months. Three clinicians. Three correct individual judgements — the base
rate of malignancy in that presentation genuinely is tiny. And **zero tests**,
because no one of them ever learned that the previous two had already failed.

> **Nobody missed the symptom. Everybody missed the pattern.**

Existing symptom checkers answer *"what might this be?"* on the day you ask.
That is the wrong question. The question nobody is answering is:

> **Is this person stuck in a loop that no individual doctor can see, because
> each doctor only ever sees one visit?**

AIRA is the thing that holds the sequence.

---

## The architecture, in one line

```
RULES decide.   Models cannot overturn a rule.
MODELS rank.    They may raise a tier, never lower one.
THE LLM phrases. It never introduces a fact, a number, or a tier.
```

Every layer below is subordinate to the one above it. That ordering is not a
disclaimer — it is enforced in code, and there are tests that fail if it stops
being true.

```
                 ┌──────────────────────────────────────────────┐
   symptoms ───► │ 1. DETERMINISTIC ENGINE   rules/*.json        │
   visits    ───►│    red flags · milestones · combinations      │──► TIER
   treatments───►│    NICE NG12 · NTEP · NP-NCD, each cited      │
                 └──────────────────────────────────────────────┘
                                    │
                 ┌──────────────────▼───────────────────────────┐
                 │ 2. LOOP DETECTOR     7 trajectory features    │──► L0…L3
                 │    duration ratio, failed treatments,         │
                 │    investigation gap, severity slope…         │
                 └──────────────────┬───────────────────────────┘
                                    │
                 ┌──────────────────▼───────────────────────────┐
                 │ 3. MODELS (EBM, glass box)                    │ may RAISE
                 │    monotonic constraints · calibrated         │ the tier
                 └──────────────────┬───────────────────────────┘
                                    │
                 ┌──────────────────▼───────────────────────────┐
                 │ 4. RETRIEVAL + LLM                            │ phrasing
                 │    146 cited passages · verifier · fallback   │ ONLY
                 └──────────────────────────────────────────────┘
```

---

## What is built

| | |
|---|---|
| **Longitudinal engine** | 50 symptoms, 11 red flags, 7 combination rules, 5 screening programmes — all as **data**, in `rules/*.json`, every entry carrying its guideline citation. Changing when an alert fires is a JSON edit that bumps a version, not a code change. |
| **Loop Detector** | The original contribution. Four rungs — observed → repeat presentation → treatment-refractory → escalate — computed from seven trajectory features. Recording that a test was actually done **clears** the loop. |
| **Explainable models** | An Explainable Boosting Machine (a GAM) with monotonic safety constraints, benchmarked head-to-head against XGBoost on the same constraints, with bootstrap confidence intervals on the difference. The per-feature contributions *are* the model — not SHAP estimating a black box afterwards. |
| **RAG chatbot** | 146 cited passages, hybrid retrieval (dense + BM25), Gemini for phrasing, and a verifier that rejects any answer containing a number it cannot trace to a source. A rejected answer falls back to the guideline text. |
| **Document upload** | Blood counts and reports parsed by **regular expression**, compared against reference intervals from the corpus. The LLM only phrases what the parser already found — so it cannot invent a haemoglobin. |
| **ABDM-shaped consent** | AIRA code ≈ ABHA address, link PIN ≈ OTP, and a scoped, purpose-bound, time-bound, revocable consent artefact re-checked on **every** request. FHIR R4 output. |
| **Voice** | Hindi, Kannada and English. Typed Indic text is matched offline against the ruleset's own phrasings; Sarvam speech-to-text is opt-in and credit-capped. |
| **Editable handover note** | AIRA drafts a note from what the rules decided, the clinician edits it in the room, and it lands on the patient's phone in their own language before they leave. |
| **Three interfaces** | A calm patient app, a dense clinician console, and an operations console that deliberately **cannot read a patient record**. |

---

## Running it

**Requirements:** Python 3.11 (not 3.12+ — `interpret` and `xgboost` wheels),
Node 18+, MySQL 8.

```bash
# 1. Python
py -3.11 -m venv .venv
py -3.11 -m pip install -r requirements.txt

# 2. Database — create the schema, then copy .env.example to .env and fill it in
mysql -u root -p -e "CREATE DATABASE aira CHARACTER SET utf8mb4;"

# 3. Train the models (~3 minutes; writes ml/artifacts/)
py -3.11 ml/train.py
py -3.11 ml/evaluate.py          # optional: writes ml/figures/

# 4. Build the retrieval index (~30 seconds, downloads a 90 MB embedding model)
py -3.11 rag/store.py --rebuild

# 5. API
py -3.11 -m uvicorn api.main:app --reload --port 8000

# 6. Demo data — four patients, one clinician, one admin
py -3.11 demo/seed.py

# 7. Front end
cd web && npm install && npm run dev
```

Then open **http://localhost:5173**.

| Role | Sign in | |
|---|---|---|
| Patient | `9000000001` | Sunita, 42 — nine months of acidity, three doctors, no tests |
| Patient | `9000000004` | Arun, 7 — forty days of fever, three antibiotics, no blood count |
| Clinician | `meera@kolarchc.gov.in` | Dr Meera Rao, Kolar CHC |
| Admin | `admin@aira.health` | Operations — and no clinical read access |

Password for all: `aira-demo-2026`

### Tests

```bash
py -3.11 -m pytest tests/test_rules.py tests/test_guardrails.py -q   # 67, offline
py -3.11 tests/smoke_api.py     # security, consent, FHIR, revocation
py -3.11 tests/smoke_ai.py      # chat, documents, the handover note
```

---

## The demo, in four minutes

1. **Sign in as Sunita.** Home says *Needs a doctor now*, in Kannada. Two
   progress rings: 190 days against a 42-day window.
2. **Your story.** Three visits, three antacids, `NO TEST ORDERED` on every
   one. That is the whole pitch, and no one before AIRA could see this page.
3. **Ask** — *"Is it safe to wait another month?"* A cited answer. Then ask
   *"Do I have cancer?"* and watch it refuse, and say what it can do instead.
4. **Sign in as Dr Meera.** The queue is sorted by concern, not by name. Three
   HIGH. The `Tests` column is red.
5. **Why this tier.** Nine rules with their NG12 and NTEP quotes on the left;
   the model's per-feature contributions on the right; the boundary between
   them stated in words.
6. **Note to patient.** One click drafts it in Kannada from the record. Edit
   it, send it.
7. **Back on Sunita's phone** — it is already there.
8. **Access → Take it back.** The doctor's next click is a 403.

---

## Being honest about what this is

This is a 48-hour prototype, and the following are stated openly rather than
waiting to be found:

- **The models are trained on a synthetic cohort.** No public dataset of
  Indian primary-care symptom trajectories with linked cancer outcomes exists.
  `ml/cohort.py` is an explicit probabilistic model built from published
  epidemiology, and its own header says at length what it does and does not
  demonstrate. **No number from it is evidence of clinical accuracy.**
- **The ruleset has not been signed off by a clinician.** Every safe-window
  value is derived from published guidance, but `needs_clinical_review` is
  `true` in `rules/symptoms.json` and the admin console says so on screen.
- **AIRA is compliant with the ABDM data model, not certified against the
  sandbox.** M1/M2/M3 certification is weeks of paperwork, not a weekend.
- **On the risk model, XGBoost genuinely beats the glass box** — 0.374 vs
  0.320 AUPRC, and the bootstrap interval excludes zero. We ship the glass box
  anyway and state the price. See `TECHNICAL.md` for why that is the right
  call here.

`TECHNICAL.md` covers all of it: the rules format, ABDM/ABHA/FHIR from zero,
EBM vs XGBoost, the RAG verifier, the guardrails, the schema, and the
security model.

---

## Repository map

```
rules/          the clinical knowledge, as data. Start here.
engine/         the deterministic core — no framework imports, no DB
  assess.py       the orchestrator. If you read one file, read this one.
  loop_detector.py the original contribution
ml/             cohort generator, features, training, metrics, figures
rag/            corpus, hybrid retrieval, the grounding verifier
llm/            Gemini adapter, guardrails, the answer loop
docs_ingest/    deterministic report parsing
voice/          Sarvam adapter, multilingual symptom mapping
api/            FastAPI, MySQL, consent, WebSockets, FHIR
web/            React + Vite + Tailwind — patient, clinician, admin
demo/           the four personas, and the seeding script
tests/          67 offline tests plus two end-to-end walks
```

---

**AIRA is a triage aid, not a diagnostic device.** It never tells anyone they
have cancer, and it never tells anyone they do not. It tells them how long
something has gone on, what has already been tried, and what the guidelines
say should happen next — and it makes that visible to the clinician who is
about to make the fourth decision.
