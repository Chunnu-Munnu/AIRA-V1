"""
Synthetic cohort generator.

READ THIS BEFORE QUOTING ANY NUMBER THIS PRODUCES.

There is no public dataset of Indian primary-care symptom trajectories with
linked cancer outcomes. Not a restricted one we could not obtain - it does not
exist. That absence is not a weakness of this project; it is a large part of
why the project needs to exist, because it means nobody can currently measure
how long an Indian patient's symptom is treated empirically before anyone
investigates it.

So we generate. But we do not invent. The generator is an explicit
probabilistic model:

    P(person) x P(cancer | person) x P(site | cancer, person)
              x P(symptoms | site) x P(trajectory | cancer, symptoms)

and every parameter below is taken from published epidemiology, cited inline.
Sampling from that model produces a cohort in which the implied positive
predictive values approximately reproduce the published ones.

WHAT CHANGED IN v2 (and why each change is a correctness fix, not a tweak)

  1. CANCER HAS A SITE.
     v1 sampled each symptom cluster independently given "cancer = 1". That
     let a single patient present with lung, breast and gynae symptoms at
     full sensitivity simultaneously, which does not happen. Worse, it made
     n_clusters a near-perfect cancer detector for a reason that has nothing
     to do with medicine. v2 samples a primary site first and then samples
     clusters conditional on that site, so co-occurrence is now structured
     the way a real presentation is.

  2. RISK FACTORS ACT ON SITES, NOT ON "CANCER".
     Chewing tobacco does not raise your risk of every cancer equally; it
     raises oral and head-and-neck sharply and does little to colorectal.
     v2 applies each relative risk to the sites it actually applies to, so
     a chewer's site mix shifts towards oral - which is what makes the
     learned model's shape functions mean something.

  3. CHILDREN EXIST.
     v1 started at age 18. One of the four demo patients is seven years old
     with forty days of fever - the exact paediatric-leukaemia pattern the
     NGO interviews described - and the risk model had never seen anyone
     under 18. v2 samples from age 2, with a paediatric site mix dominated
     by haematological malignancy, as published registries show.

  4. IT IS FIVE TIMES BIGGER.
     At 2% prevalence, 40,000 rows carry roughly 800 positives, which is
     thin for AUPRC and thinner still for fitting per-feature shapes. The
     default is now 200,000.

WHAT THIS LEGITIMATELY DEMONSTRATES
  - the full pipeline runs: features, training, calibration, explanation
  - the explainability machinery produces correct arithmetic
  - the evaluation suite (AUPRC, calibration, decision curve) works
  - the model recovers the epidemiological structure it was given

WHAT IT DOES NOT DEMONSTRATE
  - clinical accuracy on real patients. Not even slightly.

The trajectory model carries an additional and sharper caveat: because the
generator encodes "cancer cases accumulate failed treatments", a model trained
on it will learn that relationship, and reporting its accuracy as evidence
would be circular reasoning. Its purpose here is to show that the feature
extraction, monotonic constraints and explanation path are correct end to end.
Real validation requires a retrospective chart review, which is the first item
on the validation roadmap.

Say all of this out loud before anyone asks. It is a much stronger position
than being caught claiming otherwise.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETERS - every one of these is a published figure or a stated assumption
# ─────────────────────────────────────────────────────────────────────────────

SOURCES = {
    "incidence": "GLOBOCAN 2022 India; ICMR National Cancer Registry Programme. Age-specific all-site incidence per 100,000 per year.",
    "paediatric_incidence": "ICMR NCRP paediatric report; childhood (0-14) all-site incidence in India is of the order of 8-12 per 100,000 per year, dominated by leukaemia and lymphoma.",
    "site_mix": "ICMR NCRP 2020-2022 leading sites. In Indian men, lip/oral cavity and other head-and-neck sites together lead; in Indian women, breast and cervix lead. The mixes below reproduce that ordering.",
    "tobacco": "NFHS-5 (2019-21): tobacco use in adults - approximately 38% of men and 9% of women; chewing predominates over smoking in much of India.",
    "alcohol": "NFHS-5: alcohol consumption approximately 19% of men and 1% of women.",
    "relative_risks": "IARC monographs and standard epidemiological texts; rounded to one decimal place deliberately, because false precision on a borrowed parameter is worse than an honest approximation. Applied SITE BY SITE, because that is how exposure works.",
    "symptom_sensitivity": "Hamilton W. et al., primary care symptom studies (Br J Cancer / BJGP); NICE NG12 evidence reviews.",
    "enrichment": "STATED ASSUMPTION, not a published figure: a person presenting to a health worker with a complaint is modelled as ~10x more likely to have an undiagnosed cancer than an age-matched member of the general population. This single number drives overall prevalence and is the assumption most in need of real-world calibration. It was set by tuning until the implied per-symptom PPVs matched the published Hamilton primary-care values (rectal bleeding ~2-3%, haemoptysis ~7-8%, dysphagia ~5-6%) rather than by picking a number that felt right.",
    "calibration_target": "Hamilton W. The CAPER studies: PPV of individual symptoms in primary care. Rectal bleeding 2.4%, haemoptysis 7.5%, dysphagia 5.7%. If the report below drifts far from this band, the parameters are wrong and anything trained on this cohort is worthless.",
}

# Annual all-site incidence per 100,000, by age band. India, both sexes.
AGE_INCIDENCE = {
    (2, 14): 10,
    (15, 17): 15,
    (18, 29): 25,
    (30, 39): 60,
    (40, 49): 150,
    (50, 59): 300,
    (60, 69): 480,
    (70, 100): 600,
}

SYMPTOMATIC_ENRICHMENT = 10.0

# Fraction of the cohort that is a child. Paediatric OPD is a large share of
# rural primary-care contact, and the guardian-held account is a real usage
# pattern, so children are not a rounding error in a symptomatic cohort.
PAEDIATRIC_FRACTION = 0.15
PAEDIATRIC_MAX_AGE = 14

CLUSTERS = [
    "respiratory",
    "oral",
    "head_neck",
    "upper_gi",
    "lower_gi",
    "breast",
    "gynae",
    "urological",
    "systemic",
    "skin",
]

# ── Sites ────────────────────────────────────────────────────────────────────
# The vocabulary is deliberately coarse. AIRA never names a site to a patient
# and never claims to; the site exists in the generator only so that symptom
# co-occurrence and exposure effects are structured correctly.
SITES = [
    "lung",
    "oral",
    "head_neck",
    "upper_gi",
    "lower_gi",
    "breast",
    "gynae",
    "urological",
    "haematological",
    "skin",
]

# P(site | cancer) before exposure adjustment, by group. These reproduce the
# ICMR NCRP ordering: oral and head-and-neck lead in Indian men, breast and
# cervix in Indian women, leukaemia and lymphoma overwhelmingly in children.
SITE_MIX = {
    "child": {
        "haematological": 0.62,
        "lower_gi": 0.04,
        "upper_gi": 0.03,
        "urological": 0.10,   # Wilms tumour presents as an abdominal mass
        "head_neck": 0.08,
        "lung": 0.02,
        "skin": 0.02,
        "oral": 0.02,
        "breast": 0.00,
        "gynae": 0.00,
    },
    "male": {
        "oral": 0.20,
        "head_neck": 0.14,
        "lung": 0.12,
        "upper_gi": 0.13,
        "lower_gi": 0.11,
        "urological": 0.13,
        "haematological": 0.09,
        "skin": 0.04,
        "breast": 0.01,
        "gynae": 0.00,
    },
    "female": {
        "breast": 0.28,
        "gynae": 0.22,
        "oral": 0.09,
        "head_neck": 0.05,
        "upper_gi": 0.09,
        "lower_gi": 0.09,
        "lung": 0.06,
        "urological": 0.04,
        "haematological": 0.06,
        "skin": 0.02,
    },
}

# Relative risk of a GIVEN SITE for a given exposure. A blanket "smoking
# multiplies cancer by 3" is the kind of shortcut that teaches a model to
# raise colorectal risk for smokers, which is not what the evidence says.
SITE_RELATIVE_RISK = {
    "tobacco_smoking": {"lung": 8.0, "head_neck": 4.0, "oral": 3.0, "urological": 2.5, "upper_gi": 2.0},
    "tobacco_chewing": {"oral": 7.0, "head_neck": 3.5, "upper_gi": 1.8},
    "alcohol_heavy": {"oral": 2.5, "head_neck": 2.5, "upper_gi": 2.2, "lower_gi": 1.3},
    "family_history": {s: 2.0 for s in SITES},
    "obesity": {"breast": 1.4, "gynae": 1.5, "lower_gi": 1.3, "upper_gi": 1.2},
}

# P(cluster present | this site is the primary site). Rows do not sum to 1:
# a real presentation involves several clusters, and systemic symptoms
# accompany most sites.
CLUSTER_GIVEN_SITE = {
    "lung":           {"respiratory": 0.86, "systemic": 0.55, "head_neck": 0.08, "skin": 0.02},
    "oral":           {"oral": 0.90, "head_neck": 0.28, "systemic": 0.25, "upper_gi": 0.08},
    "head_neck":      {"head_neck": 0.84, "oral": 0.22, "respiratory": 0.18, "systemic": 0.32},
    "upper_gi":       {"upper_gi": 0.85, "systemic": 0.58, "lower_gi": 0.10},
    "lower_gi":       {"lower_gi": 0.82, "systemic": 0.48, "upper_gi": 0.12},
    "breast":         {"breast": 0.88, "systemic": 0.28, "skin": 0.08},
    "gynae":          {"gynae": 0.85, "systemic": 0.38, "urological": 0.14},
    "urological":     {"urological": 0.84, "systemic": 0.36, "lower_gi": 0.10},
    "haematological": {"systemic": 0.92, "head_neck": 0.34, "skin": 0.10, "respiratory": 0.10},
    "skin":           {"skin": 0.86, "systemic": 0.14},
}

# P(cluster present | no cancer). These are the base rates that make the
# problem hard: almost everyone with a cough does not have lung cancer.
BACKGROUND_PREVALENCE = {
    "respiratory": 0.30,
    "oral": 0.08,
    "head_neck": 0.09,
    "upper_gi": 0.28,
    "lower_gi": 0.12,
    "breast": 0.05,
    "gynae": 0.10,
    "urological": 0.06,
    "systemic": 0.35,
    "skin": 0.05,
}

# Clusters that do not apply to everyone. Children are gated out of breast
# and gynae entirely; adult men keep the small but real male-breast path,
# because systems that assume male breast cancer cannot happen are precisely
# how it gets missed.
CLUSTER_GATES = {
    "breast": {"min_age": 15, "male_rate": 0.01},
    "gynae": {"min_age": 12, "male_rate": 0.0},
}

# P(a red flag symptom is present | presentation)
REDFLAG_RATE = {"cancer": 0.35, "benign": 0.06}


@dataclass
class Params:
    n: int = 200_000
    seed: int = 20260903


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 - who the person is
# ─────────────────────────────────────────────────────────────────────────────


def _sample_ages(rng: np.random.Generator, n: int) -> np.ndarray:
    """A symptomatic care-seeking cohort: mostly adults, a substantial minority
    of children brought in by a guardian."""
    is_child = rng.random(n) < PAEDIATRIC_FRACTION
    child_age = rng.integers(2, PAEDIATRIC_MAX_AGE + 1, n)
    adult_age = np.clip(rng.gamma(shape=2.5, scale=9.0, size=n) + 18, 18, 92)
    return np.where(is_child, child_age, adult_age).astype(int)


def _sample_people(rng: np.random.Generator, n: int) -> pd.DataFrame:
    age = _sample_ages(rng, n)
    male = rng.random(n) < 0.5
    adult = age >= 18

    # Tobacco: prevalence and type differ sharply by sex in India. Children
    # are excluded outright rather than given a small rate - a seven-year-old
    # with a recorded smoking history is a data-entry bug, not a finding.
    p_tobacco = np.where(male, 0.38, 0.09) * adult
    uses_tobacco = rng.random(n) < p_tobacco
    # Among users, chewing is more common than smoking, and overwhelmingly so
    # among women.
    p_chew_given_use = np.where(male, 0.55, 0.85)
    chews = uses_tobacco & (rng.random(n) < p_chew_given_use)
    smokes = uses_tobacco & ~chews

    # Years of use, bounded by a plausible starting age of 15.
    max_years = np.maximum(age - 15, 0)
    smoking_years = np.where(smokes, np.minimum(rng.gamma(3.0, 5.0, n), max_years), 0)
    chewing_years = np.where(chews, np.minimum(rng.gamma(3.0, 5.0, n), max_years), 0)

    alcohol = (rng.random(n) < np.where(male, 0.19, 0.01)) & adult

    # Children sit far lower on the BMI scale; using the adult distribution
    # would make every child look underweight to a model with a BMI term.
    bmi = np.where(
        adult,
        rng.normal(23.0, 4.0, n),
        rng.normal(15.5, 2.0, n),
    )
    bmi = np.clip(bmi, 10, 45)

    family_history = rng.random(n) < 0.05
    fh_age = np.where(family_history, rng.integers(35, 75, n), 0)

    return pd.DataFrame(
        {
            "age": age,
            "sex_male": male.astype(int),
            "tobacco_smoking_years": np.round(smoking_years, 1),
            "tobacco_chewing_years": np.round(chewing_years, 1),
            "alcohol_heavy": alcohol.astype(int),
            "bmi": np.round(bmi, 1),
            "family_history": family_history.astype(int),
            "family_history_age": fh_age,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 - does this person have an undiagnosed cancer, and where
#
# The two questions are answered together, because they are the same question.
# A person's exposures do not raise "their cancer risk" as a scalar; they
# reshape which cancers they are at risk of, and the scalar falls out of that
# reshaping. Doing it in this order is what keeps the two consistent.
# ─────────────────────────────────────────────────────────────────────────────


def _base_incidence(age: np.ndarray) -> np.ndarray:
    out = np.zeros(len(age), dtype=float)
    for (lo, hi), rate in AGE_INCIDENCE.items():
        mask = (age >= lo) & (age <= hi)
        out[mask] = rate
    return out / 100_000.0


def _site_weights(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Per-person, per-site relative weights.

    Returns (weights, total_rr) where `weights` is n x len(SITES) unnormalised
    and `total_rr` is the person's overall risk multiplier - the exposure-
    weighted average over the base site mix. Summing the per-site weights IS
    the overall relative risk, which is why the two can never disagree.
    """
    n = len(df)
    age = df["age"].to_numpy()
    male = df["sex_male"].to_numpy() == 1

    base = np.zeros((n, len(SITES)))
    for group, mask in (
        ("child", age < 15),
        ("male", (age >= 15) & male),
        ("female", (age >= 15) & ~male),
    ):
        mix = SITE_MIX[group]
        row = np.array([mix.get(s, 0.0) for s in SITES])
        base[mask] = row / row.sum()

    rr = np.ones((n, len(SITES)))

    def apply(exposure: str, active: np.ndarray) -> None:
        table = SITE_RELATIVE_RISK[exposure]
        multipliers = np.array([table.get(s, 1.0) for s in SITES])
        rr[active] *= multipliers

    # Exposure needs duration to matter. Ten years is the conventional cut
    # point in most tobacco epidemiology.
    apply("tobacco_smoking", df["tobacco_smoking_years"].to_numpy() >= 10)
    apply("tobacco_chewing", df["tobacco_chewing_years"].to_numpy() >= 10)
    apply("alcohol_heavy", df["alcohol_heavy"].to_numpy() == 1)
    apply("family_history", df["family_history"].to_numpy() == 1)
    apply("obesity", df["bmi"].to_numpy() >= 30)

    weights = base * rr
    return weights, weights.sum(axis=1)


def _cancer_and_site(rng, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    weights, total_rr = _site_weights(df)
    p = np.clip(_base_incidence(df["age"].to_numpy()) * SYMPTOMATIC_ENRICHMENT * total_rr, 0.0, 0.60)
    cancer = (rng.random(len(df)) < p).astype(int)

    # Site is drawn only for the cases. Vectorised inverse-CDF sampling: the
    # per-person distribution differs for every row, so np.random.choice is
    # not usable here.
    probs = weights / weights.sum(axis=1, keepdims=True)
    draw = rng.random(len(df))[:, None]
    idx = (probs.cumsum(axis=1) < draw).sum(axis=1)
    idx = np.clip(idx, 0, len(SITES) - 1)

    site = np.array(SITES, dtype=object)[idx]
    site = np.where(cancer == 1, site, "none")
    return cancer, site, p


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 - what they present with
# ─────────────────────────────────────────────────────────────────────────────


def _sample_symptoms(rng, df: pd.DataFrame, cancer: np.ndarray, site: np.ndarray) -> pd.DataFrame:
    n = len(df)
    age = df["age"].to_numpy()
    female = df["sex_male"].to_numpy() == 0
    cols: dict[str, np.ndarray] = {}

    for cluster in CLUSTERS:
        # Cases: P(cluster | their own site). Controls: background rate.
        p = np.full(n, BACKGROUND_PREVALENCE[cluster], dtype=float)
        for s in SITES:
            p = np.where(
                (cancer == 1) & (site == s),
                CLUSTER_GIVEN_SITE[s].get(cluster, 0.03),
                p,
            )
        present = rng.random(n) < p

        gate = CLUSTER_GATES.get(cluster)
        if gate:
            present &= age >= gate["min_age"]
            if gate["male_rate"] <= 0:
                present &= female
            else:
                present &= female | (rng.random(n) < gate["male_rate"])

        cols[f"cluster_{cluster}"] = present.astype(int)

    clusters = pd.DataFrame(cols)
    cluster_cols = [f"cluster_{c}" for c in CLUSTERS]

    # Nobody with zero symptoms is in a symptomatic cohort. Give them the
    # single most common presenting cluster rather than dropping the row.
    empty = clusters[cluster_cols].sum(axis=1).to_numpy() == 0
    clusters.loc[empty, "cluster_systemic"] = 1

    red_flag = rng.random(n) < np.where(
        cancer == 1, REDFLAG_RATE["cancer"], REDFLAG_RATE["benign"]
    )
    clusters["has_red_flag"] = red_flag.astype(int)
    clusters["n_clusters"] = clusters[cluster_cols].sum(axis=1)
    return clusters


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 - the trajectory
#
# This is the part that encodes the project's core clinical claim, and it is
# also the part whose learned coefficients must NOT be presented as a finding.
# We built this relationship in; a model recovering it proves the machinery
# works, not that the claim is true. The claim's evidence is the NGO field
# research and the published literature on diagnostic intervals, not this.
# ─────────────────────────────────────────────────────────────────────────────


def _sample_trajectory(rng, df: pd.DataFrame, cancer: np.ndarray) -> pd.DataFrame:
    n = len(df)

    # Benign self-limiting illness resolves. Malignancy does not. That single
    # asymmetry is the entire basis of the safe-window concept.
    safe_window = rng.choice([14, 21, 28, 42], size=n, p=[0.2, 0.35, 0.25, 0.2])
    ratio = np.where(
        cancer == 1,
        rng.gamma(shape=3.0, scale=1.1, size=n) + 0.6,
        rng.gamma(shape=1.6, scale=0.45, size=n),
    )
    days = np.round(ratio * safe_window).astype(int)

    # How often someone goes to a doctor is mostly about them, not about their
    # disease: distance, money, whether they can lose a day's wages, whether
    # anyone will mind the children. Modelling visit count as a pure function
    # of illness severity produced an implied PPV of 39% for two failed
    # treatments, which is the generator admiring its own assumptions. This
    # person-level term is independent of cancer status and breaks that.
    care_seeking = rng.gamma(shape=2.0, scale=0.6, size=n)
    n_episodes = rng.poisson(np.clip(ratio * 0.5 + care_seeking, 0.2, 6.0))
    n_episodes = np.clip(n_episodes, 0, 8)

    # Investigation rate is the system's behaviour, not the disease's. It is
    # deliberately LOW and identical for both groups: a clinician cannot know
    # who has cancer, which is exactly why the gap is dangerous.
    p_investigate = 0.22
    n_investigations = rng.binomial(n_episodes, p_investigate)

    treated = rng.binomial(n_episodes, 0.75)
    # Softened deliberately. An earlier version used 0.10 / 0.72 and produced
    # an implied PPV of 88% for "two failed treatments", which is not a
    # finding - it is the generator's own assumption being read back. These
    # values give a likelihood ratio around 6-7, which is large enough to
    # matter clinically and small enough to be honest.
    p_resolve = np.where(cancer == 1, 0.25, 0.62)
    n_failed = rng.binomial(treated, 1 - p_resolve)

    severity_slope = np.where(
        cancer == 1,
        rng.normal(0.9, 0.7, n),
        rng.normal(-0.15, 0.5, n),
    )
    breadth_creep = rng.poisson(np.where(cancer == 1, 1.3, 0.25))
    provider_switches = np.clip(rng.poisson(np.clip(n_episodes * 0.6, 0, 4)), 0, n_episodes)

    return pd.DataFrame(
        {
            "safe_window_days": safe_window,
            "days_elapsed": days,
            "duration_ratio": np.round(ratio, 3),
            "n_episodes": n_episodes,
            "n_investigations": n_investigations,
            "n_failed_treatments": n_failed,
            "severity_slope": np.round(severity_slope, 3),
            "breadth_creep": breadth_creep,
            "provider_switches": provider_switches,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────


def generate(params: Params) -> pd.DataFrame:
    rng = np.random.default_rng(params.seed)

    people = _sample_people(rng, params.n)
    cancer, site, p_cancer = _cancer_and_site(rng, people)

    symptoms = _sample_symptoms(rng, people, cancer, site)
    trajectory = _sample_trajectory(rng, people, cancer)

    df = pd.concat([people, symptoms, trajectory], axis=1)
    df["cancer"] = cancer
    # Kept for stratified splitting and for the report. NOT a training
    # feature: AIRA never predicts a site and must never be able to.
    df["site"] = site
    df["true_probability"] = np.round(p_cancer, 6)
    return df


def report(df: pd.DataFrame) -> str:
    """Sanity report. If the implied PPVs here look nothing like the published
    ones, the parameters above are wrong and the model trained on this data is
    worthless. Check this every time the generator changes."""
    child = df[df.age < 15]
    lines = [
        f"cohort size           {len(df):,}",
        f"cancer prevalence     {df['cancer'].mean():.3%}   ({int(df['cancer'].sum()):,} cases)",
        f"mean age              {df['age'].mean():.1f}",
        f"children (<15)        {len(child):,} ({len(child) / len(df):.1%}), "
        f"prevalence {child['cancer'].mean():.3%}",
        f"tobacco users         {((df.tobacco_smoking_years > 0) | (df.tobacco_chewing_years > 0)).mean():.1%}",
        "",
        "site mix among cases (target: oral/head-neck lead in men, breast/cervix in women):",
    ]
    cases = df[df.cancer == 1]
    for s, frac in cases["site"].value_counts(normalize=True).items():
        lines.append(f"  {s:<16} {frac:>6.1%}   n={int((cases['site'] == s).sum()):,}")

    lines += ["", "implied PPV by presenting cluster (P(cancer | cluster present)):"]
    for c in CLUSTERS:
        col = f"cluster_{c}"
        sub = df[df[col] == 1]
        if len(sub) > 50:
            lines.append(f"  {c:<14} {sub['cancer'].mean():>7.2%}   n={len(sub):,}")

    lines += ["", "implied PPV by trajectory:"]
    for label, mask in [
        ("no failed treatments", df.n_failed_treatments == 0),
        ("1 failed treatment", df.n_failed_treatments == 1),
        ("2+ failed treatments", df.n_failed_treatments >= 2),
        ("past safe window", df.duration_ratio > 1.0),
        ("2+ visits, 0 tests", (df.n_episodes >= 2) & (df.n_investigations == 0)),
    ]:
        sub = df[mask]
        if len(sub) > 50:
            lines.append(f"  {label:<22} {sub['cancer'].mean():>7.2%}   n={len(sub):,}")

    lines += ["", "exposure check (relative risk should track the IARC tables):"]
    for label, mask in [
        ("chews 10+ years", df.tobacco_chewing_years >= 10),
        ("smokes 10+ years", df.tobacco_smoking_years >= 10),
        ("neither", (df.tobacco_chewing_years < 10) & (df.tobacco_smoking_years < 10)),
    ]:
        sub = df[mask]
        if len(sub) > 50:
            oral = (sub[sub.cancer == 1]["site"] == "oral").mean() if (sub.cancer == 1).any() else 0
            lines.append(
                f"  {label:<18} prevalence {sub['cancer'].mean():>6.2%}   "
                f"oral share of cases {oral:>5.1%}   n={len(sub):,}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=Params.n)
    ap.add_argument("--seed", type=int, default=Params.seed)
    ap.add_argument("--out", default="ml/data/cohort.csv")
    args = ap.parse_args()

    df = generate(Params(n=args.n, seed=args.seed))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    print(report(df))
    print(f"\nwritten to {out}")
