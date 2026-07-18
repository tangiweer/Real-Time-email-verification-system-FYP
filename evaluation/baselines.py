"""
System-level baselines for the email verifier.
Implements syntax-only, blocklist-only, MX-only, and pipeline-sans-ML baselines for ablation and McNemar's testing.
"""

from __future__ import annotations

import re
import os
import sqlite3
import asyncio
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, balanced_accuracy_score, matthews_corrcoef,
)
from evaluation.core_metrics import McNemarTest


# Pull the blocklist from the actual SQLite DB, not a hardcoded set
def _load_disposable_domains_from_db() -> set:
    """Load disposable domains from the project's SQLite blocklist DB."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    db_path = os.path.join(base_dir, "data", "disposable_domains.db")

    domains = set()

    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT domain FROM disposable_domains")
            domains = {row[0].lower().strip() for row in cursor.fetchall()}
            conn.close()
        except Exception:
            pass

    # DB empty or missing? Seed a minimal fallback so tests don't blow up.
    if not domains:
        domains = {
            "mailinator.com", "guerrillamail.com", "guerrillamail.net",
            "sharklasers.com", "yopmail.com", "trashmail.com", "tempmail.com",
            "discard.email", "maildrop.cc", "throwam.com", "spamgourmet.com",
            "fakeinbox.com", "getnada.com", "spambox.us", "10minutemail.com",
            "temp-mail.org", "throwaway.email", "mailnull.com",
        }

    return domains


# Lazy singleton so we only touch the DB once
_DISPOSABLE_DOMAINS: Optional[set] = None


def get_disposable_domains() -> set:
    """Get disposable domains (loads once from DB)."""
    global _DISPOSABLE_DOMAINS
    if _DISPOSABLE_DOMAINS is None:
        _DISPOSABLE_DOMAINS = _load_disposable_domains_from_db()
    return _DISPOSABLE_DOMAINS


class Baseline:
    """Base class for all baselines"""
    name: str = "base"

    def classify(self, email: str) -> Tuple[int, str]:
        """
        Classify email as legitimate (0) or disposable (1).
        Returns (label, reason)
        """
        raise NotImplementedError


class SyntaxOnlyBaseline(Baseline):
    """Baseline 1: pure regex + length checks. No network, no ML."""
    name = "syntax_only"

    def classify(self, email: str) -> Tuple[int, str]:
        if not email or len(email) > 320:
            return 1, "Invalid length"

        # Strict ASCII-only pattern — intentionally rejects the unicode
        # local-parts that our permissive pipeline allows
        pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'

        if not re.match(pattern, email):
            return 1, "Syntax invalid"

        # Structural sanity checks — redundant after the regex, but cheap insurance
        if "@" not in email:
            return 1, "Missing @"

        local, domain = email.rsplit("@", 1)

        if not local or not domain:
            return 1, "Empty local-part or domain"

        if ".." in local or ".." in domain:
            return 1, "Consecutive dots"

        if local.startswith(".") or local.endswith("."):
            return 1, "Local-part starts/ends with dot"

        if domain.startswith("-") or domain.endswith("-"):
            return 1, "Domain starts/ends with hyphen"

        if "." not in domain:
            return 1, "Domain missing TLD"

        return 0, "Syntax valid"


class BlocklistOnlyBaseline(Baseline):
    """Baseline 2: syntax + domain blocklist. Catches the easy ones."""
    name = "blocklist_only"

    def __init__(self):
        self._syntax = SyntaxOnlyBaseline()
        self._domains = get_disposable_domains()

    def classify(self, email: str) -> Tuple[int, str]:
        # Syntax gate first
        label, reason = self._syntax.classify(email)
        if label != 0:
            return 1, f"Syntax failed: {reason}"

        # Blocklist lookup
        domain = email.rsplit("@", 1)[1].lower() if "@" in email else ""

        if domain in self._domains:
            return 1, f"Domain {domain} in disposable blocklist"

        return 0, "Domain not in blocklist"


class MXOnlyBaseline(Baseline):
    """
    Baseline 3: syntax + MX lookup.
    NOTE: uses pre-computed MX results for reproducibility — live DNS
    would make the benchmark non-deterministic.
    """
    name = "mx_only"

    def __init__(self, mx_results: Optional[Dict[str, bool]] = None):
        """
        Args:
            mx_results: Pre-computed {domain: has_mx} mapping.
                        If None, assumes all domains have MX (optimistic).
        """
        self._syntax = SyntaxOnlyBaseline()
        self._mx_results = mx_results or {}

    def classify(self, email: str) -> Tuple[int, str]:
        label, reason = self._syntax.classify(email)
        if label != 0:
            return 1, f"Syntax failed: {reason}"

        domain = email.rsplit("@", 1)[1].lower() if "@" in email else ""

        if domain in self._mx_results:
            if not self._mx_results[domain]:
                return 1, f"Domain {domain} has no MX records"
        # If we have no MX data for this domain, assume it’s valid (optimistic)

        return 0, "Domain has MX records"


class FullPipelineWithoutML(Baseline):
    """
    Baseline 4: everything except the ML layer.
    Measures the incremental value of the classifier itself.
    """
    name = "pipeline_without_ml"

    def __init__(self, mx_results: Optional[Dict[str, bool]] = None):
        self._blocklist = BlocklistOnlyBaseline()
        self._mx_results = mx_results or {}

    def classify(self, email: str) -> Tuple[int, str]:
        # Blocklist already includes syntax
        label, reason = self._blocklist.classify(email)
        if label != 0:
            return label, reason

        # MX check on top of blocklist
        domain = email.rsplit("@", 1)[1].lower() if "@" in email else ""
        if domain in self._mx_results and not self._mx_results[domain]:
            return 1, f"Domain {domain} has no MX records"

        return 0, "Passed syntax + blocklist + MX (no ML)"


class BaselineComparison:
    """Run all baselines on the same test set + McNemar's to check significance."""

    def __init__(
        self,
        emails: List[str],
        ground_truth: List[int],
        mx_results: Optional[Dict[str, bool]] = None,
    ):
        self.emails = list(emails)
        self.ground_truth = np.array(ground_truth)
        self.mx_results = mx_results or {}

    def evaluate_baseline(self, baseline: Baseline) -> Dict[str, Any]:
        """Score a single baseline. Returns full confusion-matrix breakdown."""
        predictions = []
        for email in self.emails:
            label, _ = baseline.classify(email)
            predictions.append(label)

        predictions = np.array(predictions)
        gt = self.ground_truth

        # Edge case: if the test set or predictions are single-class, most metrics are meaningless
        if len(np.unique(gt)) < 2 or len(np.unique(predictions)) < 2:
            return {
                "name": baseline.name,
                "accuracy": round(float(accuracy_score(gt, predictions)), 4),
                "note": "Single class in predictions or ground truth — detailed metrics unreliable",
                "predictions": predictions,
            }

        cm = confusion_matrix(gt, predictions, labels=[0, 1])

        prec = precision_score(gt, predictions, labels=[0, 1], average=None, zero_division=0)
        rec = recall_score(gt, predictions, labels=[0, 1], average=None, zero_division=0)

        return {
            "name": baseline.name,
            "accuracy": round(float(accuracy_score(gt, predictions)), 4),
            "balanced_accuracy": round(float(balanced_accuracy_score(gt, predictions)), 4),
            "f1_macro": round(float(f1_score(gt, predictions, average="macro", zero_division=0)), 4),
            "mcc": round(float(matthews_corrcoef(gt, predictions)), 4),
            "precision_legitimate": round(float(prec[0]), 4),
            "precision_disposable": round(float(prec[1]), 4),
            "recall_legitimate": round(float(rec[0]), 4),
            "recall_disposable": round(float(rec[1]), 4),
            "confusion_matrix": {
                "true_negatives": int(cm[0][0]),
                "false_positives": int(cm[0][1]),
                "false_negatives": int(cm[1][0]),
                "true_positives": int(cm[1][1]),
            },
            "predictions": predictions,
        }

    def compare_all_baselines(self) -> Dict[str, Any]:
        """Evaluate all four baselines on the shared test set."""
        baselines = {
            "syntax_only": SyntaxOnlyBaseline(),
            "blocklist_only": BlocklistOnlyBaseline(),
            "mx_only": MXOnlyBaseline(self.mx_results),
            "pipeline_without_ml": FullPipelineWithoutML(self.mx_results),
        }

        results = {}
        for key, baseline in baselines.items():
            results[key] = self.evaluate_baseline(baseline)

        return results

    def mcnemar_comparisons(
        self, ml_predictions: np.ndarray
    ) -> Dict[str, Any]:
        """
        McNemar's between the ML classifier and each baseline.
        If the p-value is < 0.05, ML adds statistically significant value.
        """
        baselines = {
            "syntax_only": SyntaxOnlyBaseline(),
            "blocklist_only": BlocklistOnlyBaseline(),
            "mx_only": MXOnlyBaseline(self.mx_results),
            "pipeline_without_ml": FullPipelineWithoutML(self.mx_results),
        }

        comparisons = {}
        for key, baseline in baselines.items():
            baseline_preds = np.array([baseline.classify(e)[0] for e in self.emails])
            test = McNemarTest.compare(ml_predictions, baseline_preds, self.ground_truth)
            comparisons[f"ml_vs_{key}"] = test

        return comparisons
