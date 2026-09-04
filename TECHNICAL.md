# AIRA — technical reference

Written for someone who has not seen the codebase and does not already know
what ABDM, an EBM or a decision curve is. Every concept is introduced before
it is used.

---

## Contents

1. [The one architectural rule](#1-the-one-architectural-rule)
2. [The deterministic engine](#2-the-deterministic-engine)
3. [The Loop Detector](#3-the-loop-detector)
4. [ABDM, ABHA and FHIR, from zero](#4-abdm-abha-and-fhir-from-zero)
5. [The models: why a GAM, and what it cost](#5-the-models-why-a-gam-and-what-it-cost)
6. [Retrieval and the grounding verifier](#6-retrieval-and-the-grounding-verifier)
7. [The LLM, and every guardrail on it](#7-the-llm-and-every-guardrail-on-it)
8. [Reading an uploaded report without hallucinating](#8-reading-an-uploaded-report-without-hallucinating)
9. [Voice, and three languages](#9-voice-and-three-languages)
10. [The database schema](#10-the-database-schema)
11. [The security model](#11-the-security-model)
12. [What we know is wrong with this](#12-what-we-know-is-wrong-with-this)

---

## 1. The one architectural rule

```
RULES decide.    Models cannot overturn a rule.
MODELS rank.     They may raise a tier, never lower one.
THE LLM phrases. It never introduces a fact, a number, or a tier.
```

Read `engine/assess.py` and you can see it enforced in about forty lines. The
model layer is a single `higher_tier(tier, model_tier)` call — a function that
is mathematically incapable of returning something lower than its first
argument. The LLM never touches `assess()` at all; it is downstream of a
decision that has already been made and stored.

**Why this way round.** The failure everyone worries about with medical AI is
a confident wrong answer. The failure that actually kills people in this
problem space is a *reassuring* wrong answer — being told the thing that has
been going on for six months is probably nothing. A system where a model can
lower a tier can produce that. A system where it structurally cannot, cannot.

The price is real: AIRA over-refers relative to an unconstrained model. We
think that is the correct direction to be wrong in for a safety-netting tool,
and we say so rather than hiding it.

---

## 2. The deterministic engine

### Rules as data

`rules/` holds four JSON files, versioned together. `engine/rules_loader.py`
refuses to boot if their `ruleset_version` values disagree, if a rule
references a symptom that does not exist, or if any patient-facing string is
missing a Hindi or Kannada translation. A server that starts with a broken
ruleset is far more dangerous than one that refuses to.

```jsonc
{
  "code": "cough",
  "label":  { "en": "Cough", "hi": "खांसी", "kn": "ಕೆಮ್ಮು" },
  "cluster": "respiratory",
  "safe_window_days": 21,
  "milestones": [
    { "day": 14, "action": "TB_SPUTUM", "tier_floor": "MODERATE",
      "message": { "en": "…", "hi": "…", "kn": "…" },
      "source": "NTEP presumptive TB definition: cough of 2 weeks or more" },
    { "day": 21, "action": "CHEST_XRAY", "tier_floor": "MODERATE", … }
  ],
  "expected_investigations": ["sputum_afb", "chest_xray"],
  "citation": { "source": "NG12", "section": "1.1.2", "quote": "…",
                "confidence": "high" }
}
```

### The four independent clocks

A symptom is evaluated against four things at once, and any of them can raise
the tier:

| Clock | Fires | Example |
|---|---|---|
| **Red flag** | day 0 | Haemoptysis. `safe_window_days: 0` — there is no safe window for coughing blood. |
| **Milestone** | a fixed day | Cough at day 14 → sputum test. This is **India's NTEP TB threshold**, not a cancer threshold, and the message says so. |
| **Combination** | when a set co-occurs | NG12: age 40+, ever smoked, one qualifying symptom → urgent chest X-ray. |
| **Safe window** | when duration ÷ window > 1 | 190 days against a 42-day window = 4.5×. |

### Why "safe window" and not "risk score"

A patient is never shown a probability. They are shown a **clock**: this
usually settles in 21 days, yours has run 85. That is a fact about their
history, checkable by them, and it does not require them to understand what a
7% risk means — which almost nobody does, including clinicians.

---

## 3. The Loop Detector

The part no competing product has.

### Seven features

Computed in `engine/loop_detector.py` from the patient's whole history,
anchored on one symptom:

| Feature | Meaning | Monotonic |
|---|---|---|
| `duration_ratio` | days elapsed ÷ that symptom's safe window | ↑ |
| `n_episodes` | visits for this cluster since onset | ↑ |
| `n_investigations` | tests ever ordered | **↓** |
| `n_failed_treatments` | treatment courses that did not resolve it | ↑ |
| `severity_slope` | least-squares slope of severity, per 30 days | ↑ |
| `breadth_creep` | new symptoms appearing since onset | ↑ |
| `provider_switches` | distinct providers seen | — |

**`n_investigations` is the most important line in the project.** It is the
one negatively-constrained feature. More tests must *never* raise concern. A
model trained on data where sick people eventually get tested would otherwise
learn that being tested is dangerous, and would then penalise clinicians for
doing the right thing. The constraint makes that structurally impossible.

### The ladder

| Rung | Condition | Meaning |
|---|---|---|
| **L0** OBSERVED | default | recorded, being watched |
| **L1** REPEAT_PRESENTATION | ≥2 visits **and** 0 investigations | seen twice, nothing tested |
| **L2** TREATMENT_REFRACTORY | ≥2 failed treatments **and** ratio > 1.0 | the working diagnosis has failed twice |
| **L3** ESCALATE_NOW | L2 **and** (rising severity **or** new red flag **or** HIGH risk **or** breadth creep ≥ 2) | escalate today |

The conditions live in `rules/ladder.json` and are interpreted at runtime, so
changing when L2 fires is a JSON edit that bumps a version — and every stored
assessment records the version it was made under, so past decisions stay
replayable.

### The four contextual flags

Rungs describe a loop. Some situations are not loops:

- `CF_NEVER_SEEN` — `duration_ratio > 2.0` **and** `n_episodes == 0`. Lakshmi
  has had a cough for months and has never been to a doctor. There is no loop
  to detect, and the answer is outreach, not escalation. This maps to the
  **Aarhus Statement's patient interval**.
- `CF_INVESTIGATION_GAP`, `CF_TREATMENT_REFRACTORY`, `CF_MISSED_CHECKBACKS`.

### What breaks a loop

Recording that a test was actually done. Through the clinician's "Record what
I did", or through a patient uploading a report. AIRA then stops nagging —
which is exactly what a clinician who did the right thing deserves, and is why
the tool does not become something people learn to ignore.

---

## 4. ABDM, ABHA and FHIR, from zero

### What these things are

**ABDM** — Ayushman Bharat Digital Mission, India's national health data
architecture. Its central idea is *federation*: there is no national database
of everyone's records. Records stay where they were created, and a patient
grants scoped, time-limited access.

**ABHA** — Ayushman Bharat Health Account. A person's health identity: a
14-digit number and a human-readable address like `sunita@abdm`. Crucially it
is an **identifier, not a key** — knowing someone's ABHA address grants you
nothing at all.

**HIP / HIU** — Health Information Provider (holds records) and Health
Information User (wants to read them). A clinic is usually both.

**Consent Manager** — the broker. A HIU asks it for access, it asks the
patient, the patient decides, and it issues a **consent artefact**: a signed
object naming who, what, why, for how long, and revocable at any moment.

**FHIR R4** — the interchange format. Data as *resources* — `Patient`,
`Observation`, `Encounter`, `Consent` — with defined fields, so two systems
that have never met can exchange records. India's NRCeS publishes
India-specific profiles.

### How AIRA maps onto it

| ABDM concept | AIRA today | File |
|---|---|---|
| ABHA address | `AIRA-XXXX-XXXX` code | `api/security.py` |
| OTP challenge | 6-digit link PIN, 10-minute TTL, 3 attempts | `api/routers/consent.py` |
| Consent artefact | `Consent` row: purpose, scope, expiry, revocation | `api/tables.py` |
| Consent Manager | the patient's own phone | `web/…/patient/Access.jsx` |
| HIP data push | `GET /fhir/Patient/{id}/$everything` | `api/routers/fhir.py` |
| Audit | append-only `audit_log`, no DELETE grant | `api/audit.py` |

### The consent handshake, and what each step guarantees

```
patient taps "Generate a PIN"      → 6 digits, 10 minutes, 3 attempts
doctor enters code + PIN           → creates a REQUEST. Grants nothing.
patient reads/hears the notice     → in their own language; the fact that it
                                     was shown is recorded separately
patient allows or denies           → the artefact is issued, or it is not
doctor reads the record            → re-checked on EVERY request
patient revokes                    → dead on the doctor's very next call
```

**The single most important property:** submitting a valid code and a correct
PIN grants **zero** access. Authentication is not authorisation. The smoke
test asserts this — after a correct PIN, the doctor's read is still a 403.

**Enumeration resistance:** an unknown code and a wrong PIN return the
*identical* error, so this form cannot be used to discover who is registered.

### Being honest about certification

AIRA is built to the ABDM **data model**. It is not registered with a live
Consent Manager and is not sandbox-certified — M1/M2/M3 certification is weeks
of paperwork and a registered entity, not a weekend. The parts that would have
to change are the parts we would expect to change: swap the AIRA code for a
real ABHA address, and swap our consent screen for the national Consent
Manager's callback. The artefact model, the scoping, the expiry, the
revocation semantics and the audit trail are already the right shape.

---

## 5. The models: why a GAM, and what it cost

### The two models

**Risk (case-finding)** — 20 features: age, sex, tobacco years, alcohol, BMI,
family history, which symptom clusters are present, red flag, cluster count.

**Trajectory (loop concern)** — the seven Loop Detector features.

### What an EBM is

An **Explainable Boosting Machine** is a Generalised Additive Model:

```
log-odds(cancer) = intercept + f₁(age) + f₂(smoking years) + f₃(BMI) + …
```

Each `fᵢ` is a learned curve for one feature, fitted by gradient boosting in a
round-robin so no feature can hide inside another. The prediction is the sum.

This matters because **the explanation is not an approximation**. SHAP on a
black box answers "what would a simpler model have done here?" An EBM's
per-feature contributions *are the model*, and they sum exactly to the
prediction. `ml/figures/risk_shape_functions.png` plots them — and the age
curve shows visible steps at 40 and 50, which is the age-band structure of the
underlying incidence data being recovered, not imposed.

### Monotonic constraints as a safety property

```python
RISK_MONOTONE = {"age": 1, "tobacco_smoking_years": 1, "has_red_flag": 1, …}
TRAJECTORY_MONOTONE = {"n_investigations": -1, …}
```

`+1` means risk may not *decrease* as this rises. Enforced inside the fitting
procedure, these make certain wrong behaviours structurally impossible rather
than merely unlikely. AIRA cannot become less concerned because someone smoked
for longer, or because a red flag appeared.

### The benchmark, and the result

We trained XGBoost on the same features with the **same monotonic
constraints**, gave it the validation set for early stopping (which the EBM
does not use, so if anything the black box is favoured), and scored both once
on a held-out test set.

| | AUPRC | AUROC | ECE | Sens @3% | PPV | NNI |
|---|---|---|---|---|---|---|
| **Risk — EBM (shipped)** | 0.3195 | 0.898 | 0.0012 | 0.701 | 0.105 | 9.5 |
| Risk — XGBoost | **0.3740** | 0.911 | 0.0010 | 0.701 | 0.123 | 8.1 |
| **Trajectory — EBM (shipped)** | **0.9254** | 0.997 | 0.0009 | 0.965 | 0.431 | 2.3 |
| Trajectory — XGBoost | 0.9239 | 0.997 | 0.0006 | 0.963 | 0.479 | 2.1 |

Bootstrap, 2,000 paired resamples of the test set:

- **Risk:** EBM − XGBoost = **−0.054** AUPRC, 95% CI [−0.070, −0.038].
  The interval excludes zero. **The black box genuinely wins here.**
- **Trajectory:** EBM − XGBoost = **+0.0015**, 95% CI [−0.0012, +0.0043].
  Not distinguishable.

**We ship the glass box on both, and state the price.** The honest framing:

> On trajectory — the model that drives the Loop Detector — interpretability
> costs nothing measurable. On risk it costs about 0.05 AUPRC. We pay it,
> because a clinician who cannot see why a number moved cannot disagree with
> it, and a system nobody can disagree with gets switched off. We measured
> the price rather than assuming it was zero.

That is a materially stronger position than "we used explainable AI", and it
took ninety seconds of extra compute to be able to say it.

### Metrics, and one that is deliberately absent

**Accuracy is not in this repository.** At 1.8% prevalence, a model that
outputs "no" for everyone scores 98.2% and finds nobody. What we report:

- **AUPRC**, not AUROC. With a rare positive class the huge true-negative
  count flatters ROC.
- **Calibration (ECE, Brier).** When we say 5%, is it 5%? A miscalibrated
  model cannot be used with a fixed referral threshold, which makes it
  unusable in a guideline-driven system.
- **Sensitivity and PPV at NG12's 3% threshold** — the operating point that
  actually determines who gets referred.
- **NNI** — number needed to investigate. What a health system budgets for.
- **Net benefit (decision curve, Vickers & Elkin).** The only figure a health
  administrator can act on: is using this better than investigating everyone,
  or nobody?

### Why not an LSTM

Two to six irregularly spaced encounters. There is nothing a sequence model
could learn from that which the seven features do not already state
explicitly, and the seven features fit on a card a clinician reads in twenty
seconds. Complexity we cannot justify is complexity we do not add.

### The cohort, and its limits

`ml/cohort.py` — 200,000 rows, 1.76% prevalence, generated from an explicit
four-stage model:

```
P(person) × P(cancer | person) × P(site | cancer, person)
          × P(symptoms | site) × P(trajectory | cancer, symptoms)
```

Every parameter is a published figure, cited inline. Cancers have a **site**,
sampled per person and shifted by their exposures, so a chewer's cases are
half oral (matching IARC) and symptom co-occurrence is structured the way a
real presentation is. Children are included from age 2, with a paediatric site
mix dominated by haematological malignancy.

Implied PPVs land in the published band — chewer prevalence 4.70% against
1.31% baseline (RR ≈ 3.6), two failed treatments 9.75%, past safe window 6.84%.

**And none of it is evidence of clinical accuracy.** The trajectory model in
particular carries a circularity caveat: the generator encodes "cancer cases
accumulate failed treatments", so a model recovering that relationship proves
the machinery works, not that the claim is true. The claim's evidence is the
NGO field research and the diagnostic-interval literature. Real validation
needs a retrospective chart review, which is item one on the roadmap.

---

## 6. Retrieval and the grounding verifier

### The corpus

146 passages in `rag/corpus.py`, each with provenance and exactly one of two
kinds:

- `kind="quote"` — verbatim guideline text. **May support a number.**
- `kind="summary"` — our own plain-language wording. **May never be the sole
  authority for a number.**

That distinction is the point. A retrieval system that cannot tell a guideline
from its own paraphrase will eventually put our wording in a clinician's mouth
and attribute it to NICE.

Most of the corpus is lifted directly out of `rules/*.json`, so the chatbot
and the rules engine cannot disagree about what a guideline says — there is
one copy of the text, and changing a safe window changes both in one commit.

### Hybrid retrieval

`0.65 × dense + 0.35 × lexical`, on min-max normalised scores.

- **Dense** (`all-MiniLM-L6-v2`, ChromaDB, cosine): handles *"my stomach burns
  after eating"* → dyspepsia. Keyword search cannot.
- **BM25**: handles `CBNAAT`, `PM-JAY`, `NG12 1.2.1`. A 384-dimensional
  sentence embedding will return something adjacent and wrong for those, and
  they are exactly the tokens a clinician types.

**A score floor of 0.28.** Ranking is relative — it tells you which passage is
closest, never whether the closest is any good. Below the floor a passage is
dropped even if that leaves nothing, because *"I do not have a source for
that"* is a correct answer and the nearest unrelated paragraph is not.

**Query augmentation.** The retrieval query is the question plus the symptom
this patient is actually tracked for. *"Is it safe to wait?"* is a question
about dyspepsia when Sunita asks it and about a cough when Ramesh does. The
symptom comes from the stored assessment, never from the model.

### The verifier — `rag/verify.py`

An LLM answer is a **draft** until it passes four checks:

1. **Banned claims.** Diagnosis, exclusion, prognosis, staging, drug doses,
   personal probabilities. Matched on the surface and rejected outright —
   these are outside what the system may assert, not phrasing problems a
   better prompt fixes.
2. **The numeric guard.** Every number must appear in a retrieved **quote**,
   or in the patient's own record as passed in by the caller. A fabricated
   number is the most dangerous LLM failure in a clinical setting, because a
   plausible number is indistinguishable from a real one — and "14 days"
   versus "40 days" is the entire product.
3. **Grounding.** Each sentence must overlap meaningfully with a retrieved
   passage, or with the union of them at a higher bar (a terse clinician
   sentence often compresses two clauses).
4. **Citation authenticity.** A guideline section the answer cites must be one
   it was given. This catches an invented `NG12 9.9.9`.

Three bugs this file has already caught in its own logic, each now a test:
`NG12` being read as the number 12; `1.2.1` being split into `1.2`;
`4,000-11,000` being split into `000`. A verifier that rejects correct answers
is as bad as one that passes wrong ones.

**What it is not:** entailment. A sentence can pass all four and still be a
subtly wrong reading. What it guarantees is that every number came from
somewhere we can point at — which is the failure mode that actually shows up.

---

## 7. The LLM, and every guardrail on it

`gemini-3.5-flash-lite` for phrasing. Never for deciding.

### The loop

```
route → retrieve → generate → verify → (repair once) → or fall back
```

Every stage can veto, and **the last stage is not the model**. A draft that
fails verification is replaced by a deterministic answer built from the same
passages, so the worst case is a stiffer sentence rather than a wrong one.

**One repair pass, not more.** The commonest failure is a single invented
number; handing back the exact complaint fixes it most of the time and costs
one call. A second repair does not — by then the model is failing on something
structural, and looping burns quota to produce the fallback anyway.

### The guardrails, in order

| # | Guardrail | Where |
|---|---|---|
| 1 | **Emergency routing.** Heavy bleeding, retention, seizure, chest pain with sweating → an instruction and the number 108. Never reaches the model. | `llm/guardrails.py` |
| 2 | **Refusal routing.** Diagnosis, medication, prognosis, image reading, staging → declined, with what AIRA *can* do instead. A refusal that offers nothing teaches people to stop asking. | `llm/guardrails.py` |
| 3 | **PII scrubbing at the adapter.** Names, phones, AIRA codes, ABHA numbers, Aadhaar, emails, hospital IDs, and every exact date. The model sees an **age band** and a sex. Enforced in `generate()`, not by asking callers to remember. | `llm/gemini.py` |
| 4 | **Fact whitelisting.** `api/llm_service.build_llm_facts` is the only thing that assembles patient facts for a prompt — durations, counts, an age band. There is one such function, so there is one place to audit. | `api/llm_service.py` |
| 5 | **Audience policy.** A patient rendering may not contain a probability, a cancer type, a staging term or a tier label. A clinician's may. Derived from the **authenticated role**, never from the request body. | `llm/guardrails.py` |
| 6 | **The verifier.** Section 6. | `rag/verify.py` |
| 7 | **Template fallback.** Grounded by construction. | `llm/answer.py` |
| 8 | **Call budget + model chain.** A hard on-disk counter, and a chain of four models each with its own daily quota. | `llm/gemini.py` |
| 9 | **Response cache.** Only verified answers are cached. Caching inside `generate()` was a real bug for ten minutes: a rejected draft got stored and replayed. | `llm/gemini.py` |
| 10 | **Full trace persisted.** Route, retrieval scores, every check, and the rejected draft, in `chat_message.trace_json`. | `api/routers/chat.py` |

Guardrail 10 is what makes this *explainable* rather than merely careful.
"Show me what it wanted to say and why you stopped it" is the first question
anyone serious asks about a filtered model, and the clinician's Ask tab
answers it on screen.

### Two audiences, not one redacted

The same facts render twice, and neither is a censored version of the other:

| | Patient | Clinician |
|---|---|---|
| Probability | never | yes, with the NG12 threshold |
| Site vocabulary | never | yes |
| Tier / ladder | in plain words | as labels |
| Guideline sections | source name only | section numbers and quotes |
| Model internals | no | contributions, retrieval scores, rejected drafts |

Telling a patient *"your profile scores 10.9%, consistent with a lung primary"*
is a harm: a number they cannot act on attached to a word they will not stop
thinking about, delivered by software that cannot examine them.

### The quota discovery

The free tier gives **20 requests per day per model**. Finding that out on
stage would have been fatal. The response: a four-model fallback chain (each
with its own bucket), a verified-only response cache, and templates underneath
everything. The lite models also turned out to be **30× faster** — 0.8s versus
25s under quota pressure — so the chain is not a compromise, it is the right
ordering anyway.

---

## 8. Reading an uploaded report without hallucinating

The order is the whole argument:

```
upload → extract text → PARSE BY REGEX → compare against reference intervals
       from the corpus → phrase (optional) → verify
```

The LLM enters at step five, if at all, and only to phrase what steps three
and four established. **It is never shown the document and asked what it
says.** Ask a model to "read this report" and it will cheerfully return a
plausible haemoglobin for a report that does not contain one. Ask it only to
phrase a number the parser already found, and that failure mode does not
exist.

### What it will not do

- **Read images.** OCR on a phone photo of a thermal-printed report is
  unreliable in exactly the conditions this is used in, and a misread decimal
  point in a haemoglobin is worse than no reading. The file is stored for the
  clinician's own eyes.
- **Diagnose.** *"Below the reference interval"* is a fact about the
  laboratory's range. *"Anaemia"* is a diagnosis. Only the first is produced.
- **Change a tier by itself.** It records that an investigation happened —
  which does break the loop, through a real `Episode` created via the same
  path a clinician uses.

Reference intervals follow the patient: 12.5 g/dL is *low* for an adult man
and *normal* for a seven-year-old, and there is a test for exactly that.

---

## 9. Voice, and three languages

Three languages everywhere: English, Hindi, Kannada. Not as an afterthought —
`engine/rules_loader.py` **refuses to boot** if any patient-facing string is
missing a translation.

| Path | Cost | When |
|---|---|---|
| Tick from a list | free | the default. Recognition beats production, and a tick cannot be misheard. |
| Type in any of the three | free | the mapper folds in every label and phrasing from `rules/symptoms.json`, so all 50 symptoms match in all three languages offline. |
| Browser Web Speech API | free | English, and Hindi/Kannada where the device supports it. |
| **Sarvam Saarika** | 1 credit | opt-in, for the person the tick list does not reach. Trained on Indian speech and code-mixing — *"do hafte se khaansi hai"*. |
| **Sarvam Mayura** (translate) | 1 credit | second pass only, when the offline mapper found nothing. |
| Sarvam Bulbul (TTS) | 1 credit, once | fixed phrases rendered to disk and replayed forever. |

The account has 100 credits. `SARVAM_MODE=mock` is the default so development
makes zero calls; a hard counter caps live calls; and everything degrades to
the browser rather than failing.

Speech output is **always** a suggestion the patient confirms with a tap.
AIRA never silently decides what someone said.

---

## 10. The database schema

MySQL 8, SQLAlchemy 2.0, no hand-built SQL anywhere — every request body is a
Pydantic model, which is also what keeps injection out of the codebase.

```
user ─┬─ patient_profile (aira_code, dob, sex, language, village, risk_factors, bmi)
      └─ doctor_profile  (reg_no, facility, specialty)

symptom ── severity_reading
episode                     visits, treatment, investigation, outcome
checkback                   the safety net, scheduled and answered
assessment                  tier, ladder, features_json, reasons_json,
                            contributions_json, ruleset_version, model_version
medical_document            uploads: extracted_json, both summaries, verification
clinician_note              draft_text AND final_text, status, released_at
chat_message                question, answer, citations_json, trace_json
consent / link_pin          the ABDM artefact and its OTP
clinician_override          when a clinician disagrees — never discarded
audit_log                   append-only; the app user has no DELETE grant
refresh_token               rotating, hashed
```

Three decisions worth defending:

**Assessments store their explanation.** `features_json`, `reasons_json` and
`contributions_json` are written at decision time. A model retrained tomorrow
must not be able to change what we told a patient today.

**Symptoms snapshot their safe window and ruleset version.** A rule change
does not retroactively rewrite why an old alert fired.

**Notes keep both versions.** `draft_text` as AIRA generated it and
`final_text` as the clinician sent it. The difference is the only honest
measure of whether the drafting is any good, and discarding it would mean
never being able to improve.

### A bug worth recording

MySQL `DATETIME` defaults to whole seconds. Two assessments written in the
same second therefore carried the same `created_at`, and `ORDER BY created_at
DESC` became an arbitrary choice between them. Since "the latest assessment"
drives the dashboard, the queue and the Handoff Card, a tie meant a patient
who had reached HIGH could be shown MODERATE. `api/db.py` now migrates every
datetime column to `DATETIME(6)` on startup, and every ordering carries an id
tiebreak.

---

## 11. The security model

### Authentication ≠ authorisation

```
AUTHENTICATION  proves who you are.        the JWT
AUTHORISATION   proves you may see THIS.   the consent artefact
```

A doctor logging in successfully grants access to precisely zero records.
Access exists only while a consent artefact is live, and it is re-checked on
**every request** rather than cached in the session — which is what makes
revocation instant rather than "instant at next login".

### Controls

| Control | Implementation |
|---|---|
| Password hashing | argon2id |
| Access token | JWT, 15 minutes |
| Refresh token | hashed at rest, **rotates** on use — a stolen token is usable at most once, and its use invalidates the legitimate holder's, which is detectable |
| Lockout | 5 failed logins → 15 minutes |
| Enumeration | unknown code and wrong PIN return the identical error |
| Admin clinical access | **denied explicitly** in `api/deps.py`, and audited when attempted |
| Audit | append-only; the app DB user holds no DELETE grant on `audit_log` |
| Revocation | dead on the next request |
| PII to the LLM | blocked at the adapter; age band and sex only |
| Forbidden features | caste, religion, income, region — **not columns** |

### Minimum necessary disclosure

Consent answers *"may this clinician read this record"*. It does not answer
*"which fields"*. `api/disclosure.py` lists every field a clinician can see
with the reason it is clinically necessary, and every field they cannot with
the reason it is not:

- **Shared:** name, age, sex, risk factors, BMI, language, AIRA code.
- **Withheld:** phone, exact date of birth, village, email, and which other
  doctors this patient has consented to.

Village is withheld because an exact locality plus age plus sex re-identifies
a person in a small settlement. If a clinician needs it for follow-up they can
ask the patient, who is standing in front of them.

**The withheld list is returned to the client and rendered on screen.** A
privacy control nobody can see is indistinguishable from one that does not
exist.

### The features that do not exist

Caste, religion, income and community are not withheld — they are not columns.
Never collected, so nothing to leak, nothing to correlate against, and no
model that can learn them. `tests/test_rules.py` asserts none of these words
appears anywhere in the ruleset; `tests/test_guardrails.py` asserts the same
of the retrieval corpus.

---

## 12. What we know is wrong with this

Stated here rather than waiting to be found.

1. **The ruleset has not been clinically signed off.** `needs_clinical_review`
   is `true`, the admin console says so on screen, and every assessment
   records the version it was made under so pre-review decisions are
   identifiable and replayable.
2. **The models are trained on synthetic data.** Nothing they output is
   evidence of clinical accuracy. The trajectory model additionally carries a
   circularity caveat — see §5.
3. **On the risk model the black box wins**, by 0.054 AUPRC with a CI
   excluding zero. We ship the glass box and state the price.
4. **Not ABDM sandbox-certified.** Compliant at the data layer; see §4.
5. **The corpus is 146 passages, not thousands.** Every one is real and cited.
   A padded corpus retrieves worse and lies more.
6. **No OCR.** A phone photo of a report is stored, not read. This is a
   limitation, and it is the right one.
7. **The Gemini free tier is 20 requests per day per model.** Mitigated with a
   model chain, a cache and templates — but at scale this needs a paid tier.
8. **Retrieval is lexical + embedding, with no reranker.** A cross-encoder
   would improve precision. It would also add a second neural model to a
   system whose selling point is that you can audit every step by eye.
9. **The grounding check is token overlap, not entailment.** Deliberately
   crude, so an auditor can run it themselves — but it will pass a sentence
   that borrows the right words and the wrong meaning.
10. **Single-anchor trajectory.** A patient with two unrelated problems is
    assessed against the more advanced one. Correct for triage, incomplete as
    a clinical picture.

### What comes next, in order

1. **Retrospective chart review.** Real trajectories, real outcomes. Nothing
   else on this list matters as much.
2. **Clinical sign-off on the ruleset**, by a named reviewer, with the version
   bumped.
3. **ABDM sandbox registration** and M1–M3.
4. **Prospective evaluation** of the thing that actually matters: does the
   diagnostic interval shorten?
