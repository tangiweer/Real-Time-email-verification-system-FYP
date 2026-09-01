"""
Metrics suite for email verifier evaluation.

TERMINOLOGY (keep this straight):
  Positive = legitimate email (label 0)
  Negative = disposable/invalid (label 1)
  FN = rejecting a real user — COSTLY
  FP = accepting disposable — annoying but survivable
  Primary metric = recall on the legitimate class (minimise FN rate)
"""

from __future__ import annotations

import numpy as np
from typing import Dict, Tuple, Any, Optional
from sklearn.metrics import (
    confusion_matrix, precision_score, recall_score, f1_score,
    roc_auc_score, roc_curve, auc, precision_recall_curve,
    matthews_corrcoef, brier_score_loss, balanced_accuracy_score,
    accuracy_score,
)


class MetricsSuite:
    """
    Full evaluation suite: confusion matrix + 8 metrics.
    Covers everything from basic accuracy to calibration quality.
    """

    def __init__(self, y_true: np.ndarray, y_pred: np.ndarray, y_proba: np.ndarray = None):
        """
        Args:
            y_true: Ground truth labels (0=legitimate, 1=disposable)
            y_pred: Predicted labels (0=legitimate, 1=disposable)
            y_proba: Prediction probabilities for class 1 (optional, required for ROC/PR-AUC)
        """
        self.y_true = np.array(y_true)
        self.y_pred = np.array(y_pred)
        self.y_proba = np.array(y_proba) if y_proba is not None else None

    def compute_all(self) -> Dict[str, Any]:
        """Compute all metrics in standardized suite"""
        result = {
            "confusion_matrix": self.confusion_matrix_dict(),
            "precision_per_class": self.precision_per_class(),
            "recall_per_class": self.recall_per_class(),
            "f1_macro": self.f1_macro(),
            "balanced_accuracy": self.balanced_accuracy(),
            "matthews_corr_coef": self.matthews_corr_coef(),
            "roc_auc": self.roc_auc(),
            "pr_auc": self.pr_auc(),
            "brier_score": self.brier_score(),
            "accuracy": self.accuracy(),
        }

        warning = self.separability_warning()
        if warning:
            result["separability_warning"] = warning

        return result

    def confusion_matrix_dict(self) -> Dict[str, int]:
        """Standard 2×2 CM as a flat dict."""
        cm = confusion_matrix(self.y_true, self.y_pred, labels=[0, 1])
        # cm[0][1] = FP (legitimate predicted disposable) — the costly one
        return {
            "true_negatives": int(cm[0][0]),
            "false_positives": int(cm[0][1]),
            "false_negatives": int(cm[1][0]),
            "true_positives": int(cm[1][1]),
        }

    def accuracy(self) -> float:
        """Overall accuracy"""
        return round(float(accuracy_score(self.y_true, self.y_pred)), 4)

    def precision_per_class(self) -> Dict[str, float]:
        """Per-class precision via average=None."""
        prec = precision_score(
            self.y_true, self.y_pred, labels=[0, 1],
            average=None, zero_division=0
        )
        return {
            "legitimate": round(float(prec[0]), 4),
            "disposable": round(float(prec[1]), 4),
        }

    def recall_per_class(self) -> Dict[str, float]:
        """Per-class recall. recall_legitimate is the PRIMARY metric."""
        rec = recall_score(
            self.y_true, self.y_pred, labels=[0, 1],
            average=None, zero_division=0
        )
        return {
            "legitimate": round(float(rec[0]), 4),   # PRIMARY — minimise false rejections
            "disposable": round(float(rec[1]), 4),
        }

    def f1_macro(self) -> float:
        """Macro F1 (unweighted average across classes)"""
        f1 = f1_score(self.y_true, self.y_pred, average="macro", zero_division=0)
        return round(float(f1), 4)

    def balanced_accuracy(self) -> float:
        """(TPR + TNR) / 2 — handles class imbalance better than raw accuracy."""
        return round(float(balanced_accuracy_score(self.y_true, self.y_pred)), 4)

    def matthews_corr_coef(self) -> float:
        """MCC in [-1, 1]. Better than accuracy on imbalanced data."""
        mcc = matthews_corrcoef(self.y_true, self.y_pred)
        return round(float(mcc), 4)

    def roc_auc(self) -> Optional[float]:
        """ROC-AUC. A score of 1.0 is a red flag, not a victory lap."""
        if self.y_proba is None:
            return None
        if len(np.unique(self.y_true)) < 2:
            return None
        try:
            auc_score = roc_auc_score(self.y_true, self.y_proba)
            return round(float(auc_score), 4)
        except Exception:
            return None

    def pr_auc(self) -> Optional[float]:
        """Precision-Recall AUC — more honest than ROC on imbalanced data."""
        if self.y_proba is None:
            return None
        if len(np.unique(self.y_true)) < 2:
            return None
        try:
            precision_curve, recall_curve, _ = precision_recall_curve(self.y_true, self.y_proba)
            pr_auc_score = auc(recall_curve, precision_curve)
            return round(float(pr_auc_score), 4)
        except Exception:
            return None

    def brier_score(self) -> Optional[float]:
        """MSE between predicted probs and true labels. 0 = perfect, 0.25 = coin flip."""
        if self.y_proba is None:
            return None
        try:
            bs = brier_score_loss(self.y_true, self.y_proba)
            return round(float(bs), 4)
        except Exception:
            return None

    def separability_warning(self) -> Optional[str]:
        """Flag suspiciously perfect AUC — usually means data leakage."""
        roc = self.roc_auc()
        if roc is not None and roc >= 0.9999:
            return (
                f"WARNING: ROC-AUC = {roc} is suspiciously perfect. "
                "Suggests potential data leakage or extreme separability. "
                "Not a merit claim — requires validation on OOD data."
            )
        return None


class BootstrapCI:
    """
    Bootstrap 95% CIs on held-out predictions.
    1000+ resamples for decent coverage.
    """

    def __init__(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_proba: np.ndarray = None,
        n_bootstrap: int = 1000,
        alpha: float = 0.05,
        random_state: int = 42,
    ):
        self.y_true = np.array(y_true)
        self.y_pred = np.array(y_pred)
        self.y_proba = np.array(y_proba) if y_proba is not None else None
        self.n_bootstrap = n_bootstrap
        self.alpha = alpha
        self.rng = np.random.RandomState(random_state)

    def compute_all_cis(self) -> Dict[str, Dict[str, float]]:
        """Bootstrap CIs for all primary metrics."""
        results = {}

        # Define metric lambdas
        metric_fns = {
            "accuracy": lambda yt, yp, ypr: accuracy_score(yt, yp),
            "f1_macro": lambda yt, yp, ypr: f1_score(yt, yp, average="macro", zero_division=0),
            "balanced_accuracy": lambda yt, yp, ypr: balanced_accuracy_score(yt, yp),
            "mcc": lambda yt, yp, ypr: matthews_corrcoef(yt, yp),
            "recall_legitimate": lambda yt, yp, ypr: recall_score(
                yt, yp, labels=[0, 1], average=None, zero_division=0
            )[0],
            "recall_disposable": lambda yt, yp, ypr: recall_score(
                yt, yp, labels=[0, 1], average=None, zero_division=0
            )[1],
        }

        if self.y_proba is not None:
            metric_fns["roc_auc"] = lambda yt, yp, ypr: (
                roc_auc_score(yt, ypr) if len(np.unique(yt)) >= 2 else float("nan")
            )
            metric_fns["brier_score"] = lambda yt, yp, ypr: brier_score_loss(yt, ypr)

        for name, fn in metric_fns.items():
            bootstrap_scores = []
            n = len(self.y_true)

            for _ in range(self.n_bootstrap):
                indices = self.rng.randint(0, n, size=n)
                yt_boot = self.y_true[indices]
                yp_boot = self.y_pred[indices]
                ypr_boot = self.y_proba[indices] if self.y_proba is not None else None

                # Skip degenerate single-class bootstrap samples
                if len(np.unique(yt_boot)) < 2:
                    continue

                try:
                    score = fn(yt_boot, yp_boot, ypr_boot)
                    if not np.isnan(score):
                        bootstrap_scores.append(score)
                except Exception:
                    continue

            if bootstrap_scores:
                scores_arr = np.array(bootstrap_scores)
                results[name] = {
                    "mean": round(float(scores_arr.mean()), 4),
                    "ci_lower": round(float(np.percentile(scores_arr, self.alpha / 2 * 100)), 4),
                    "ci_upper": round(float(np.percentile(scores_arr, (1 - self.alpha / 2) * 100)), 4),
                    "std": round(float(scores_arr.std()), 4),
                }
            else:
                results[name] = {
                    "mean": None, "ci_lower": None, "ci_upper": None, "std": None,
                    "warning": "Insufficient valid bootstrap samples",
                }

        return results


class McNemarTest:
    """McNemar's test: are two classifiers on the same test set significantly different?"""

    @staticmethod
    def compare(
        predictions_1: np.ndarray,
        predictions_2: np.ndarray,
        ground_truth: np.ndarray,
    ) -> Dict[str, Any]:
        """
        Run McNemar's with continuity correction.
        b = cases correct in 1 only, c = cases correct in 2 only.
        """
        predictions_1 = np.array(predictions_1)
        predictions_2 = np.array(predictions_2)
        ground_truth = np.array(ground_truth)

        correct_1 = predictions_1 == ground_truth
        correct_2 = predictions_2 == ground_truth

        b = int(np.sum(correct_1 & ~correct_2))   # correct in 1, wrong in 2
        c = int(np.sum(~correct_1 & correct_2))    # wrong in 1, correct in 2

        if b + c == 0:
            return {
                "statistic": 0.0,
                "p_value": 1.0,
                "significant_at_0_05": False,
                "interpretation": "Classifiers make identical predictions (no discordant pairs)",
                "b": b,
                "c": c,
            }

        # Continuity-corrected chi-squared
        chi2_stat = (abs(b - c) - 1) ** 2 / (b + c)

        from scipy.stats import chi2
        p_value = 1 - chi2.cdf(chi2_stat, df=1)

        interpretation = (
            f"SIGNIFICANT difference (p = {p_value:.4f} < 0.05): "
            f"Classifiers are statistically different. "
            f"Classifier 1 gets {b} cases right that 2 misses; "
            f"Classifier 2 gets {c} cases right that 1 misses."
            if p_value < 0.05
            else f"NO significant difference (p = {p_value:.4f} >= 0.05): "
                 f"Cannot reject null hypothesis that classifiers perform equally."
        )

        return {
            "statistic": round(float(chi2_stat), 4),
            "p_value": round(float(p_value), 4),
            "significant_at_0_05": p_value < 0.05,
            "interpretation": interpretation,
            "b": b,
            "c": c,
        }


class CalibrationAnalysis:
    """Calibration analysis: reliability diagram + ECE + MCE."""

    def __init__(self, y_true: np.ndarray, y_proba: np.ndarray, n_bins: int = 10):
        """
        Args:
            y_true: Ground truth labels
            y_proba: Predicted probabilities for class 1
            n_bins: Number of bins for reliability diagram
        """
        self.y_true = np.array(y_true)
        self.y_proba = np.array(y_proba)
        self.n_bins = n_bins

    def reliability_diagram(self) -> Dict[str, Any]:
        """Bin predictions and compare predicted prob vs. observed frequency."""
        bin_edges = np.linspace(0, 1, self.n_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        empirical_freqs = []
        mean_predicts = []
        counts = []

        for i in range(self.n_bins):
            if i == self.n_bins - 1:  # last bin includes the right edge
                mask = (self.y_proba >= bin_edges[i]) & (self.y_proba <= bin_edges[i + 1])
            else:
                mask = (self.y_proba >= bin_edges[i]) & (self.y_proba < bin_edges[i + 1])

            if mask.sum() > 0:
                empirical_freqs.append(float(self.y_true[mask].mean()))
                mean_predicts.append(float(self.y_proba[mask].mean()))
                counts.append(int(mask.sum()))
            else:
                empirical_freqs.append(None)
                mean_predicts.append(None)
                counts.append(0)

        return {
            "bin_centers": [round(x, 4) for x in bin_centers],
            "empirical_frequencies": [
                round(x, 4) if x is not None else None for x in empirical_freqs
            ],
            "mean_predicted_probabilities": [
                round(x, 4) if x is not None else None for x in mean_predicts
            ],
            "counts_per_bin": counts,
            "total_samples": int(len(self.y_true)),
        }

    def expected_calibration_error(self) -> float:
        """ECE = weighted mean |predicted - observed| across bins. 0 = perfect."""
        bin_edges = np.linspace(0, 1, self.n_bins + 1)
        ece = 0.0
        total_count = 0

        for i in range(self.n_bins):
            if i == self.n_bins - 1:
                mask = (self.y_proba >= bin_edges[i]) & (self.y_proba <= bin_edges[i + 1])
            else:
                mask = (self.y_proba >= bin_edges[i]) & (self.y_proba < bin_edges[i + 1])

            if mask.sum() > 0:
                empirical_freq = self.y_true[mask].mean()
                mean_predict = self.y_proba[mask].mean()
                ece += abs(empirical_freq - mean_predict) * mask.sum()
                total_count += mask.sum()

        return round(float(ece / total_count) if total_count > 0 else 0.0, 4)

    def max_calibration_error(self) -> float:
        """MCE = worst single-bin calibration gap."""
        bin_edges = np.linspace(0, 1, self.n_bins + 1)
        mce = 0.0

        for i in range(self.n_bins):
            if i == self.n_bins - 1:
                mask = (self.y_proba >= bin_edges[i]) & (self.y_proba <= bin_edges[i + 1])
            else:
                mask = (self.y_proba >= bin_edges[i]) & (self.y_proba < bin_edges[i + 1])

            if mask.sum() > 0:
                empirical_freq = self.y_true[mask].mean()
                mean_predict = self.y_proba[mask].mean()
                mce = max(mce, abs(empirical_freq - mean_predict))

        return round(float(mce), 4)

    def calibration_recommendation(self) -> str:
        """Suggest whether post-hoc calibration is needed."""
        ece = self.expected_calibration_error()
        if ece < 0.05:
            return (
                f"GOOD calibration (ECE = {ece:.4f}). "
                "No post-hoc calibration needed."
            )
        elif ece < 0.10:
            return (
                f"MODERATE calibration (ECE = {ece:.4f}). "
                "Consider Platt scaling on a held-out fold for marginal improvement."
            )
        else:
            return (
                f"POOR calibration (ECE = {ece:.4f}). "
                "Platt scaling or isotonic regression strongly recommended. "
                "Threshold choices based on uncalibrated probabilities may be unreliable."
            )

    def full_analysis(self) -> Dict[str, Any]:
        """Complete calibration analysis."""
        brier = brier_score_loss(self.y_true, self.y_proba)
        return {
            "reliability_diagram": self.reliability_diagram(),
            "expected_calibration_error": self.expected_calibration_error(),
            "max_calibration_error": self.max_calibration_error(),
            "brier_score": round(float(brier), 4),
            "recommendation": self.calibration_recommendation(),
        }
