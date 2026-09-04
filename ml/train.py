"""
Train both models and benchmark each against a black box.

    py -3.11 ml/train.py

Produces ml/artifacts/{risk,trajectory}_ebm.pkl plus a metrics report.

The argument this script exists to support:

    We did not choose the interpretable model because we could not build the
    accurate one. We built both, measured the difference, and then chose -
    knowing the price.

That is a materially stronger claim than "we used explainable AI", and it
costs about two minutes of compute to be able to make it.

THE PROTOCOL, AND WHY IT IS THIS ONE

  Three-way split, not two. The validation set is where every decision gets
  made - which model to ship, where the operating point sits, whether the
  interpretability cost is acceptable. The test set is scored ONCE, at the
  end, and nothing is changed afterwards. A test set you consult while tuning
  is a validation set wearing a badge, and the number it gives you is the
  number you selected for.

  Stratified on cancer AND site. With 1.8% prevalence a naive split can hand
  one fold most of the paediatric haematological cases and the other almost
  none, and the difference between the two models then measures the split
  rather than the models.

  The headline comparison carries a bootstrap interval. "The glass box won by
  0.02 AUPRC" is not a result if the interval spans zero, and saying so
  before a judge asks is worth more than the 0.02.
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from interpret.glassbox import ExplainableBoostingClassifier
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.cohort import Params, generate  # noqa: E402
from ml.features import (  # noqa: E402
    RISK_FEATURES,
    RISK_MONOTONE,
    TARGET,
    TRAJECTORY_FEATURES,
    TRAJECTORY_MONOTONE,
    monotone_list,
)
from ml.metrics import format_summary, summarise  # noqa: E402

ARTIFACTS = Path("ml/artifacts")
DATA = Path("ml/data/cohort.csv")
SEED = 20260903
N_ROWS = 200_000
BOOTSTRAP = 2_000


def load(n: int = N_ROWS) -> pd.DataFrame:
    if DATA.exists():
        df = pd.read_csv(DATA)
        if len(df) >= n and "site" in df.columns:
            return df
    df = generate(Params(n=n, seed=SEED))
    DATA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA, index=False)
    return df


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """60 / 20 / 20, stratified on the joint of outcome and primary site.

    `site` is a generator variable, never a feature. It is used here only so
    that the rare strata - paediatric haematological, skin - are represented
    proportionally in all three folds.
    """
    strata = df[TARGET].astype(str) + "|" + df.get("site", pd.Series("none", index=df.index)).astype(str)
    # Any stratum with a single member cannot be stratified; fold it into the
    # generic label for its outcome rather than dropping the row.
    counts = strata.value_counts()
    strata = strata.where(strata.map(counts) >= 3, df[TARGET].astype(str))

    train, rest = train_test_split(df, test_size=0.4, random_state=SEED, stratify=strata)
    rest_strata = strata.loc[rest.index]
    val, test = train_test_split(rest, test_size=0.5, random_state=SEED, stratify=rest_strata)
    return train, val, test


def bootstrap_gap(
    y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray, rng: np.random.Generator
) -> tuple[float, float, float]:
    """95% percentile interval on AUPRC(a) - AUPRC(b), paired on the same rows.

    Paired matters: both models are scored on identical resamples, so the
    interval reflects the difference between the models rather than the
    variance of the test set itself.
    """
    n = len(y)
    gaps = np.empty(BOOTSTRAP)
    for i in range(BOOTSTRAP):
        idx = rng.integers(0, n, n)
        ys = y[idx]
        if ys.sum() == 0 or ys.sum() == n:
            gaps[i] = 0.0
            continue
        gaps[i] = average_precision_score(ys, p_a[idx]) - average_precision_score(ys, p_b[idx])
    return float(np.mean(gaps)), float(np.percentile(gaps, 2.5)), float(np.percentile(gaps, 97.5))


def train_one(
    train: pd.DataFrame,
    val: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    monotone: dict[str, int],
    name: str,
) -> dict:
    X_tr, y_tr = train[features], train[TARGET].to_numpy()
    X_va, y_va = val[features], val[TARGET].to_numpy()
    X_te, y_te = test[features], test[TARGET].to_numpy()

    print(f"\n{'=' * 76}\n  {name}\n{'=' * 76}")
    print(
        f"  features {len(features)}   train {len(X_tr):,} ({y_tr.sum():,} pos)   "
        f"val {len(X_va):,} ({y_va.sum():,} pos)   test {len(X_te):,} ({y_te.sum():,} pos)"
    )
    constrained = {k: v for k, v in monotone.items() if v}
    print(f"  monotonic constraints: {constrained}")

    # ── the glass box we intend to ship ──────────────────────────────────
    ebm = ExplainableBoostingClassifier(
        feature_names=features,
        monotone_constraints=monotone_list(features, monotone),
        # Pairwise interactions are switched off deliberately. With them on,
        # an EBM's explanation stops being a simple list of per-feature
        # contributions and starts needing a heatmap to read, which defeats
        # the reason we chose it.
        interactions=0,
        random_state=SEED,
    )
    ebm.fit(X_tr, y_tr)

    # ── the black box we are comparing against ───────────────────────────
    xgb = XGBClassifier(
        n_estimators=600,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        min_child_weight=5,
        # Same constraints, so the comparison is like for like. An
        # unconstrained black box beating a constrained glass box would prove
        # nothing except that constraints cost something.
        monotone_constraints=tuple(monotone_list(features, monotone)),
        eval_metric="aucpr",
        early_stopping_rounds=50,
        random_state=SEED,
        n_jobs=4,
    )
    # The black box gets the validation set for early stopping. The glass box
    # does not need it. If anything this hands XGBoost an advantage, which is
    # the right way round for a comparison we intend to cite.
    xgb.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)

    # ── the decision, made on validation ─────────────────────────────────
    v_ebm = summarise(y_va, ebm.predict_proba(X_va)[:, 1], "EBM  [validation]")
    v_xgb = summarise(y_va, xgb.predict_proba(X_va)[:, 1], "XGBoost [validation]")
    print(f"\n  DECISION SET (validation) — everything below this line is chosen here")
    print(f"    EBM      AUPRC {v_ebm['auprc']:.4f}   ECE {v_ebm['ece']:.5f}")
    print(f"    XGBoost  AUPRC {v_xgb['auprc']:.4f}   ECE {v_xgb['ece']:.5f}")

    # ── the report, scored once on held-out test ─────────────────────────
    p_ebm = ebm.predict_proba(X_te)[:, 1]
    p_xgb = xgb.predict_proba(X_te)[:, 1]
    s_ebm = summarise(y_te, p_ebm, "EBM  (glass box - SHIPPED)")
    s_xgb = summarise(y_te, p_xgb, "XGBoost (black box - benchmark only)")

    print(f"\n  HELD-OUT TEST — scored once, nothing tuned after this\n")
    print(format_summary(s_ebm))
    print()
    print(format_summary(s_xgb))

    # Positive gap = the black box is ahead and interpretability cost us
    # something. Negative gap = the glass box won outright.
    gap = s_xgb["auprc"] - s_ebm["auprc"]
    pct = gap / s_xgb["auprc"] * 100 if s_xgb["auprc"] else 0.0

    rng = np.random.default_rng(SEED)
    mean_diff, lo, hi = bootstrap_gap(y_te, p_ebm, p_xgb, rng)  # EBM minus XGB

    print(f"\n  COST OF INTERPRETABILITY: {gap:+.4f} AUPRC ({pct:+.1f}%)")
    print(
        f"    EBM - XGBoost = {mean_diff:+.4f}  "
        f"95% CI [{lo:+.4f}, {hi:+.4f}]   ({BOOTSTRAP:,} paired bootstrap resamples)"
    )

    significant = lo > 0 or hi < 0
    if not significant:
        print(
            "    THE INTERVAL SPANS ZERO. On this cohort the two models are not\n"
            "    distinguishable, so the honest claim is not 'the glass box won' -\n"
            "    it is 'the glass box costs nothing measurable, and we can read it.'\n"
            "    That is the claim to make on stage."
        )
    elif lo > 0:
        print(
            "    The GLASS BOX WON, and the interval excludes zero. Not a fluke: the\n"
            "    underlying risk structure is additive on the log-odds scale (independent\n"
            "    relative risks multiply, which is addition once you take logs), and that\n"
            "    is precisely a GAM's inductive bias. A tree ensemble has to approximate a\n"
            "    smooth additive surface with axis-aligned splits, and at 1.8% positives it\n"
            "    overfits doing so. Interpretability cost us nothing here - it paid."
        )
    else:
        print(
            "    The black box is genuinely ahead. Do not wave this away - state the\n"
            "    price openly, or find out which interaction the EBM is missing."
        )
    print(
        f"    Calibration (lower is better): EBM ECE {s_ebm['ece']:.5f} "
        f"vs XGBoost {s_xgb['ece']:.5f}"
    )

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with (ARTIFACTS / f"{name}_ebm.pkl").open("wb") as fh:
        pickle.dump(
            {"model": ebm, "features": features, "version": f"{name}-ebm-2.0.0"}, fh
        )
    # The benchmark is kept too. A claim about a model nobody can re-run is
    # not a claim, and this is the artifact that lets someone check ours.
    with (ARTIFACTS / f"{name}_xgboost.pkl").open("wb") as fh:
        pickle.dump(
            {"model": xgb, "features": features, "version": f"{name}-xgb-2.0.0"}, fh
        )
    np.savez_compressed(
        ARTIFACTS / f"{name}_test_scores.npz", y=y_te, ebm=p_ebm, xgb=p_xgb
    )

    return {
        "name": name,
        "features": features,
        "n_train": int(len(X_tr)),
        "n_val": int(len(X_va)),
        "n_test": int(len(X_te)),
        "validation": {"ebm": v_ebm["auprc"], "xgboost": v_xgb["auprc"]},
        "ebm": {k: v for k, v in s_ebm.items() if k != "label"},
        "xgboost": {k: v for k, v in s_xgb.items() if k != "label"},
        "interpretability_cost_auprc": gap,
        "ebm_minus_xgb": {"mean": mean_diff, "ci_low": lo, "ci_high": hi, "significant": bool(significant)},
    }


def demo_explanation(df: pd.DataFrame) -> None:
    """Print the thing the whole architecture exists to make possible."""
    with (ARTIFACTS / "risk_ebm.pkl").open("rb") as fh:
        bundle = pickle.load(fh)
    model, features = bundle["model"], bundle["features"]

    # Pick a genuinely high-risk row so the breakdown is interesting.
    row = df[(df.tobacco_chewing_years > 10) & (df.age > 50)].head(1)
    if row.empty:
        row = df.head(1)

    x = row[features]
    prob = float(model.predict_proba(x)[:, 1][0])

    local = model.explain_local(x).data(0)
    contributions = sorted(
        zip(local["names"], local["scores"]), key=lambda kv: -abs(kv[1])
    )

    print(f"\n{'=' * 76}\n  WHAT 'EXPLAINABLE' ACTUALLY MEANS\n{'=' * 76}")
    print("  This is not SHAP estimating what a black box did afterwards.")
    print("  These numbers ARE the model. They sum to the prediction.\n")
    print(f"  {'log-odds':>10}   feature")
    print(f"  {'-' * 10}   {'-' * 48}")
    print(f"  {local['extra']['scores'][0]:>+10.4f}   (baseline)")
    for fname, score in contributions[:10]:
        if abs(score) < 1e-6:
            continue
        value = x[fname].iloc[0] if fname in x else ""
        print(f"  {score:>+10.4f}   {fname} = {value}")
    print(f"  {'-' * 10}   {'-' * 48}")
    print(f"  {'':>10}   final probability = {prob:.4%}")
    print(
        f"\n  NG12 refers at 3%. This patient is "
        f"{'ABOVE' if prob >= 0.03 else 'below'} that threshold."
    )


def main() -> int:
    df = load()
    print(f"cohort: {len(df):,} rows, {df[TARGET].mean():.3%} prevalence")
    train, val, test = split(df)

    results = [
        train_one(train, val, test, RISK_FEATURES, RISK_MONOTONE, "risk"),
        train_one(train, val, test, TRAJECTORY_FEATURES, TRAJECTORY_MONOTONE, "trajectory"),
    ]

    demo_explanation(df)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "metrics.json").write_text(
        json.dumps(
            {
                "cohort_rows": int(len(df)),
                "prevalence": float(df[TARGET].mean()),
                "seed": SEED,
                "bootstrap_resamples": BOOTSTRAP,
                "models": results,
            },
            indent=2,
            default=float,
        )
    )

    print(f"\n{'=' * 76}")
    print("  artifacts written to ml/artifacts/")
    print("  REMINDER: these numbers describe a synthetic cohort. They are")
    print("  evidence that the pipeline works, not that the model is clinically")
    print("  accurate. See the header of ml/cohort.py.")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
