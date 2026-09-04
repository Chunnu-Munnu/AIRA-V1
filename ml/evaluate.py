"""
Evaluation plots.

    py -3.11 ml/evaluate.py

Reads the held-out test scores that ml/train.py saved, and draws the three
figures that actually answer a question:

  CALIBRATION   When we say 5%, is it 5%? A model that cannot be trusted at a
                fixed threshold cannot be used inside a guideline-driven
                health system at all, because the whole system is thresholds.

  PRECISION-RECALL  Not ROC. With 1.8% prevalence a ROC curve looks
                magnificent for a model that is useless, because the enormous
                true-negative count flatters the false-positive rate.

  DECISION CURVE  Vickers & Elkin. The only figure here a health administrator
                can act on: is using this model better than referring
                everyone, or referring nobody, at the threshold we actually
                operate at?

No accuracy plot. See the header of ml/metrics.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.metrics import NG12_THRESHOLD, net_benefit, treat_all_net_benefit  # noqa: E402

ARTIFACTS = Path("ml/artifacts")
FIGURES = Path("ml/figures")

INK = "#12211d"
EBM_C = "#2f7d6b"
XGB_C = "#a02a20"
GRID = "#e5e1d8"


def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=11, fontweight="bold", color=INK, pad=10)
    ax.set_xlabel(xlabel, fontsize=9, color=INK)
    ax.set_ylabel(ylabel, fontsize=9, color=INK)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)
    ax.tick_params(labelsize=8, colors=INK)


def calibration_points(y: np.ndarray, p: np.ndarray, bins: int = 12):
    """Quantile bins, not equal-width. With most predictions crowded below 5%,
    equal-width bins put 95% of the cohort in the first bucket and draw a
    calibration curve out of one point."""
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    xs, ys, ns = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p <= hi if hi == edges[-1] else p < hi)
        if mask.sum() < 30:
            continue
        xs.append(p[mask].mean())
        ys.append(y[mask].mean())
        ns.append(int(mask.sum()))
    return np.array(xs), np.array(ys), ns


def plot_model(name: str) -> dict:
    path = ARTIFACTS / f"{name}_test_scores.npz"
    if not path.exists():
        raise SystemExit(f"{path} not found - run: py -3.11 ml/train.py")

    d = np.load(path)
    y, ebm, xgb = d["y"], d["ebm"], d["xgb"]

    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.3))
    fig.patch.set_facecolor("white")

    # ── 1. calibration ───────────────────────────────────────────────────
    ax = axes[0]
    ax.plot([0, 1], [0, 1], "--", color="#9aa8a3", linewidth=1, label="perfect")
    reach = 0.05
    for scores, colour, label in ((ebm, EBM_C, "EBM (shipped)"), (xgb, XGB_C, "XGBoost")):
        xs, ys, _ = calibration_points(y, scores)
        ax.plot(xs, ys, "o-", color=colour, linewidth=1.8, markersize=4, label=label)
        reach = max(reach, float(xs.max()), float(ys.max()))
    # Scale to where the BINS are, not to the single most extreme prediction.
    # A 0.999 quantile put the axis at 0.75 and squashed every plotted point
    # into the bottom-left corner, which is a chart that answers nothing.
    top = reach * 1.15
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    ax.axvline(NG12_THRESHOLD, color="#b4700f", linewidth=1, linestyle=":")
    ax.text(NG12_THRESHOLD, top * 0.96, " NG12 3%", fontsize=7.5, color="#b4700f", va="top")
    _style(ax, "Calibration", "predicted probability", "observed frequency")
    ax.legend(fontsize=8, frameon=False)

    # ── 2. precision-recall ──────────────────────────────────────────────
    ax = axes[1]
    prevalence = float(y.mean())
    for scores, colour, label in ((ebm, EBM_C, "EBM"), (xgb, XGB_C, "XGBoost")):
        precision, recall, _ = precision_recall_curve(y, scores)
        ap = average_precision_score(y, scores)
        ax.plot(recall, precision, color=colour, linewidth=1.8, label=f"{label}  AP={ap:.3f}")
    ax.axhline(prevalence, color="#9aa8a3", linestyle="--", linewidth=1,
               label=f"chance = prevalence = {prevalence:.3f}")
    ax.set_xlim(0, 1)
    _style(ax, "Precision-recall", "recall (cancers found)", "precision (PPV)")
    ax.legend(fontsize=8, frameon=False)

    # ── 3. decision curve ────────────────────────────────────────────────
    ax = axes[2]
    thresholds = np.linspace(0.005, 0.15, 60)
    for scores, colour, label in ((ebm, EBM_C, "EBM"), (xgb, XGB_C, "XGBoost")):
        ax.plot(thresholds, [net_benefit(y, scores, t) for t in thresholds],
                color=colour, linewidth=1.8, label=label)
    ax.plot(thresholds, [treat_all_net_benefit(y, t) for t in thresholds],
            color="#9aa8a3", linestyle="--", linewidth=1.2, label="investigate everyone")
    ax.axhline(0, color=INK, linewidth=1, label="investigate nobody")
    ax.axvline(NG12_THRESHOLD, color="#b4700f", linewidth=1, linestyle=":")
    ax.text(NG12_THRESHOLD, ax.get_ylim()[1] * 0.9, " NG12 3%", fontsize=7.5, color="#b4700f")
    _style(ax, "Decision curve (net benefit)", "threshold probability", "net benefit")
    ax.legend(fontsize=8, frameon=False)

    fig.suptitle(
        f"{name.upper()} model — held-out test set, n={len(y):,}, "
        f"{int(y.sum()):,} cancers ({prevalence:.2%})",
        fontsize=12, fontweight="bold", color=INK, y=1.0,
    )
    fig.text(
        0.5, -0.02,
        "Synthetic cohort. These figures show that the pipeline and the metrics are correct, "
        "not that the model is clinically accurate. See ml/cohort.py.",
        ha="center", fontsize=8, color="#7d918b",
    )
    fig.tight_layout()

    FIGURES.mkdir(parents=True, exist_ok=True)
    out = FIGURES / f"{name}.png"
    fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {
        "figure": str(out),
        "n": int(len(y)),
        "positives": int(y.sum()),
        "ebm_ap": float(average_precision_score(y, ebm)),
        "xgb_ap": float(average_precision_score(y, xgb)),
        "ebm_net_benefit_at_3pct": net_benefit(y, ebm, NG12_THRESHOLD),
        "treat_all_net_benefit_at_3pct": treat_all_net_benefit(y, NG12_THRESHOLD),
    }


def plot_shape_functions() -> str:
    """What a glass box lets you draw that a black box does not.

    Each panel is the EBM's learned contribution for one feature, over that
    feature's whole range. This is not an approximation of the model - it IS
    the model, and a clinician can look at the age curve and say whether it
    is shaped like the epidemiology they know. Try that with a tree ensemble.
    """
    import pickle

    with (ARTIFACTS / "risk_ebm.pkl").open("rb") as fh:
        model = pickle.load(fh)["model"]

    explanation = model.explain_global()
    data = explanation.data()
    names = data["names"]

    interesting = [
        n for n in ("age", "tobacco_chewing_years", "tobacco_smoking_years", "bmi",
                    "n_clusters", "has_red_flag")
        if n in names
    ]

    fig, axes = plt.subplots(2, 3, figsize=(13, 6.4))
    fig.patch.set_facecolor("white")

    for ax, feature in zip(axes.flat, interesting):
        d = explanation.data(names.index(feature))
        xs, ys = d.get("names"), d.get("scores")
        if xs is None or ys is None:
            continue
        xs = np.asarray(xs, dtype=float)
        ys = np.asarray(ys, dtype=float)
        if len(xs) == len(ys) + 1:  # bin edges
            xs = (xs[:-1] + xs[1:]) / 2
        ax.plot(xs, ys, color=EBM_C, linewidth=2)
        ax.axhline(0, color="#9aa8a3", linewidth=0.8, linestyle="--")
        _style(ax, feature.replace("_", " "), "", "log-odds contribution")

    for ax in axes.flat[len(interesting):]:
        ax.axis("off")

    fig.suptitle(
        "What the glass box learned — these curves ARE the model, not an explanation of it",
        fontsize=12, fontweight="bold", color=INK,
    )
    fig.tight_layout()
    FIGURES.mkdir(parents=True, exist_ok=True)
    out = FIGURES / "risk_shape_functions.png"
    fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(out)


def main() -> int:
    summary = {name: plot_model(name) for name in ("risk", "trajectory")}
    try:
        summary["shape_functions"] = plot_shape_functions()
    except Exception as exc:
        print(f"  (shape functions skipped: {exc})")

    (FIGURES / "summary.json").write_text(json.dumps(summary, indent=2, default=float))

    print(f"\n{'=' * 74}")
    for name in ("risk", "trajectory"):
        s = summary[name]
        print(f"  {name:<12} AP  EBM {s['ebm_ap']:.4f}   XGBoost {s['xgb_ap']:.4f}")
        print(f"  {'':<12} net benefit at 3%: {s['ebm_net_benefit_at_3pct']:+.5f} "
              f"(investigate everyone = {s['treat_all_net_benefit_at_3pct']:+.5f})")
    print(f"\n  figures written to {FIGURES}/")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
