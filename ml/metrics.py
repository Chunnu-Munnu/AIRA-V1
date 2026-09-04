"""
Evaluation metrics.

Accuracy is not in this file and never will be. On a cohort with 2% cancer
prevalence, a model that outputs "no" for every single patient scores 98%
accuracy and finds nobody. Any team that puts an accuracy figure on a slide
for a problem like this has told the audience they do not understand the
problem.

What is here instead:
  AUPRC       area under precision-recall. The right summary metric when the
              positive class is rare; AUROC flatters imbalanced problems.
  Calibration when we say 5%, is it 5%? A miscalibrated model cannot be used
              with a fixed referral threshold, which makes it unusable in a
              guideline-driven health system.
  Sensitivity at the NG12 3% operating point - the number that actually
              determines who gets referred.
  Net benefit  decision curve analysis (Vickers & Elkin 2006). Answers the
              only question that matters: is acting on this model better than
              referring everyone, or nobody?
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

NG12_THRESHOLD = 0.03  # NICE NG12 adopted a 3% PPV threshold for referral


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.digitize(p, edges[1:-1])
    ece = 0.0
    for b in range(bins):
        mask = idx == b
        if not mask.any():
            continue
        ece += mask.mean() * abs(y[mask].mean() - p[mask].mean())
    return float(ece)


def at_threshold(y: np.ndarray, p: np.ndarray, threshold: float) -> dict:
    pred = p >= threshold
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    return {
        "threshold": threshold,
        "flagged": int(pred.sum()),
        "flagged_rate": float(pred.mean()),
        "sensitivity": tp / (tp + fn) if (tp + fn) else 0.0,
        "specificity": tn / (tn + fp) if (tn + fp) else 0.0,
        "ppv": tp / (tp + fp) if (tp + fp) else 0.0,
        "npv": tn / (tn + fn) if (tn + fn) else 0.0,
        # The number a health system actually budgets for: how many people
        # must be worked up to find one cancer.
        "number_needed_to_investigate": (tp + fp) / tp if tp else float("inf"),
        "missed": fn,
    }


def net_benefit(y: np.ndarray, p: np.ndarray, threshold: float) -> float:
    """Decision curve analysis.

    A threshold of 3% encodes a clinical judgement: investigating 32 people
    who turn out to be well is an acceptable price for finding one cancer.
    Net benefit weighs true positives against false positives at exactly that
    exchange rate, which is why it is the only metric here that a health
    administrator can act on directly.
    """
    n = len(y)
    pred = p >= threshold
    tp = (pred & (y == 1)).sum()
    fp = (pred & (y == 0)).sum()
    w = threshold / (1 - threshold)
    return float(tp / n - (fp / n) * w)


def treat_all_net_benefit(y: np.ndarray, threshold: float) -> float:
    prevalence = y.mean()
    w = threshold / (1 - threshold)
    return float(prevalence - (1 - prevalence) * w)


def summarise(y: np.ndarray, p: np.ndarray, label: str = "") -> dict:
    return {
        "label": label,
        "n": int(len(y)),
        "prevalence": float(y.mean()),
        "auroc": float(roc_auc_score(y, p)),
        "auprc": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "ece": expected_calibration_error(y, p),
        "at_ng12": at_threshold(y, p, NG12_THRESHOLD),
        "net_benefit": net_benefit(y, p, NG12_THRESHOLD),
        "net_benefit_treat_all": treat_all_net_benefit(y, NG12_THRESHOLD),
    }


def format_summary(s: dict) -> str:
    t = s["at_ng12"]
    return "\n".join(
        [
            f"  {s['label']}",
            f"    n {s['n']:,}   prevalence {s['prevalence']:.2%}",
            f"    AUPRC        {s['auprc']:.4f}   (baseline = prevalence = {s['prevalence']:.4f})",
            f"    AUROC        {s['auroc']:.4f}",
            f"    Brier        {s['brier']:.5f}",
            f"    ECE          {s['ece']:.5f}   (0 = perfectly calibrated)",
            f"    at NG12 3% threshold:",
            f"      sensitivity  {t['sensitivity']:.3f}   ({t['missed']} cancers missed)",
            f"      specificity  {t['specificity']:.3f}",
            f"      PPV          {t['ppv']:.3f}",
            f"      flagged      {t['flagged_rate']:.1%} of the cohort",
            f"      NNI          {t['number_needed_to_investigate']:.1f} investigated per cancer found",
            f"    net benefit  {s['net_benefit']:+.5f}   "
            f"(refer everyone = {s['net_benefit_treat_all']:+.5f}, refer nobody = 0)",
        ]
    )
