"""
Domain-aware dataset splitting.
Provides domain-disjoint GroupShuffleSplit, domain-grouped CV, and local-part-only ablation.
"""

from __future__ import annotations

import numpy as np
from typing import Tuple, List, Dict, Optional
from sklearn.model_selection import GroupShuffleSplit, GroupKFold
import re


def extract_domain(email: str) -> str:
    """Extract domain from email address"""
    if "@" not in email:
        return "INVALID"
    return email.split("@")[1].lower()


def extract_local_part(email: str) -> str:
    """Extract local-part from email address"""
    if "@" not in email:
        return "INVALID"
    return email.split("@")[0].lower()


class DomainAwareDataSplitter:
    """
    Splits data so no domain appears on both sides.
    Without this, the model could ace the test just by memorising domains.
    """
    
    def __init__(self, random_state: int = 42):
        self.random_state = random_state
    
    def domain_disjoint_split(
        self,
        emails: List[str],
        labels: List[int],
        test_size: float = 0.2,
    ) -> Tuple[Tuple[np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray]]:
        """
        Split data so that no domain appears in both train and test.
        
        Args:
            emails: List of email addresses
            labels: List of labels (0=legitimate, 1=disposable)
            test_size: Fraction of domains (not emails) for test set
        
        Returns:
            ((X_train, y_train), (X_test, y_test))
        """
        emails = np.array(emails)
        labels = np.array(labels)
        
        # Extract domain for each email
        domains = np.array([extract_domain(e) for e in emails])
        
        # Group by domain, then split the *groups* (not individual emails)
        unique_domains = np.unique(domains)
        domain_to_group = {domain: idx for idx, domain in enumerate(unique_domains)}
        groups = np.array([domain_to_group[d] for d in domains])
        
        # GroupShuffleSplit splits domains, not rows — that's the whole point
        gss = GroupShuffleSplit(
            n_splits=1,
            test_size=test_size,
            random_state=self.random_state
        )
        
        train_idx, test_idx = next(gss.split(emails, labels, groups))
        
        return (
            (emails[train_idx], labels[train_idx]),
            (emails[test_idx], labels[test_idx])
        )
    
    def domain_aware_cross_validation_groups(
        self,
        emails: List[str],
        n_splits: int = 5,
    ) -> np.ndarray:
        """Build group IDs for GroupKFold so no domain leaks across folds."""
        domains = np.array([extract_domain(e) for e in emails])
        unique_domains = np.unique(domains)
        
        if len(unique_domains) < n_splits:
            print(
                f"WARNING: Only {len(unique_domains)} unique domains found, "
                f"but {n_splits} CV folds requested. Reducing folds to {len(unique_domains)}."
            )
            n_splits = len(unique_domains)
        
        domain_to_group = {domain: idx for idx, domain in enumerate(unique_domains)}
        groups = np.array([domain_to_group[d] for d in domains])
        
        return groups
    
    def analyze_split_quality(
        self,
        train_emails: np.ndarray,
        test_emails: np.ndarray,
        train_labels: np.ndarray,
        test_labels: np.ndarray,
    ) -> Dict[str, any]:
        """Sanity-check the split — zero domain overlap means no leakage."""
        train_domains = {extract_domain(e) for e in train_emails}
        test_domains = {extract_domain(e) for e in test_emails}
        
        overlap = train_domains & test_domains
        
        train_legit_ratio = (train_labels == 0).sum() / len(train_labels)
        test_legit_ratio = (test_labels == 0).sum() / len(test_labels)
        
        return {
            "train_unique_domains": len(train_domains),
            "test_unique_domains": len(test_domains),
            "domain_overlap_count": len(overlap),
            "overlapping_domains": list(overlap)[:5],  # Show first 5
            "train_legitimate_ratio": round(float(train_legit_ratio), 4),
            "test_legitimate_ratio": round(float(test_legit_ratio), 4),
            "leakage_detected": len(overlap) > 0,
            "warning": (
                f"DOMAIN LEAKAGE DETECTED: {len(overlap)} domains appear in both sets!"
                if len(overlap) > 0
                else "✓ No domain leakage detected (split is clean)"
            ),
        }


class AblationStudy:
    """
    Swap out real domains with neutral ones, keeping only the local-part.
    If the score drops hard, the model was leaning on domain features.
    If it barely moves, the local-part features carry genuine signal.
    """
    
    @staticmethod
    def extract_local_features_only(emails: List[str]) -> List[str]:
        """Strip real domains and substitute neutrals."""
        local_parts = [extract_local_part(e) for e in emails]
        
        # Neutral domains that shouldn't trigger any domain-based features
        random_domains = [
            "example.com", "test.io", "sample.net", "demo.org", "validation.co"
        ]
        
        ablated = []
        for i, local in enumerate(local_parts):
            domain = random_domains[i % len(random_domains)]
            ablated.append(f"{local}@{domain}")
        
        return ablated
    
    @staticmethod
    def compare_models_with_ablation(
        y_true_original: np.ndarray,
        y_pred_original: np.ndarray,
        y_pred_ablated: np.ndarray,
        metric_name: str = "accuracy",
    ) -> Dict[str, any]:
        """Compare original vs ablated. Big drop = domain-dependent model."""
        from sklearn.metrics import accuracy_score, f1_score, recall_score
        
        if metric_name == "accuracy":
            score_fn = lambda y_true, y_pred: accuracy_score(y_true, y_pred)
        elif metric_name == "f1":
            score_fn = lambda y_true, y_pred: f1_score(y_true, y_pred, average="macro")
        elif metric_name == "recall_legitimate":
            score_fn = lambda y_true, y_pred: recall_score(
                y_true, y_pred, pos_label=0, average='binary'
            )
        else:
            raise ValueError(f"Unknown metric: {metric_name}")
        
        original_score = score_fn(y_true_original, y_pred_original)
        ablated_score = score_fn(y_true_original, y_pred_ablated)
        drop_pct = (original_score - ablated_score) / original_score * 100 if original_score > 0 else 0
        
        if drop_pct > 30:
            interpretation = (
                f"STRONG indication of domain-feature reliance ({drop_pct:.1f}% drop). "
                "Model likely memorizing known disposable domains rather than learning patterns."
            )
        elif drop_pct > 10:
            interpretation = (
                f"MODERATE domain dependency ({drop_pct:.1f}% drop). "
                "Some genuine local-part signal, but domain features prominent."
            )
        else:
            interpretation = (
                f"GOOD generalization ({drop_pct:.1f}% drop). "
                "Model learned robust local-part patterns independent of domain."
            )
        
        return {
            "original_score": round(float(original_score), 4),
            "ablated_score": round(float(ablated_score), 4),
            "score_drop_pct": round(float(drop_pct), 2),
            "metric": metric_name,
            "interpretation": interpretation,
        }
