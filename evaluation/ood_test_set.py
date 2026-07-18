"""
Out-of-Distribution (OOD) Test Set.

CRITICAL: No OOD test exists in the original project. The Enron corpus (early 2000s
corporate email) is a known mismatch with modern addresses.

This module provides a dedicated OOD test set with:
  1. Unseen disposable domain families (NOT in the training blocklist)
  2. Modern consumer email patterns (TikTok-era, gaming, social media)
  3. Non-English / internationalized local parts
  4. Corporate patterns (firstname.lastname@bigcorp.com)
  5. Edge cases that stress-test generalization

Performance degradation on OOD is EXPECTED and must be reported honestly,
not hidden. The gap between in-distribution and OOD performance is itself
a key finding for the dissertation.
"""

from __future__ import annotations
from typing import List, Tuple, Dict


import csv
import os

def get_ood_test_set() -> Tuple[List[str], List[int]]:
    """
    Returns (emails, labels) for out-of-distribution testing.
    Reads from data/ood_test_set.csv to avoid hardcoded emails.
    """
    emails = []
    labels = []
    
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    csv_path = os.path.join(base_dir, "data", "ood_test_set.csv")
    
    if not os.path.exists(csv_path):
        return [], []
        
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            emails.append(row["email"])
            labels.append(int(row["label"]))
            
    return emails, labels


def get_ood_test_metadata() -> Dict[str, any]:
    """Return metadata about the OOD test set composition."""
    emails, labels = get_ood_test_set()
    n_legit = sum(1 for l in labels if l == 0)
    n_disp = sum(1 for l in labels if l == 1)

    return {
        "total_samples": len(emails),
        "legitimate_count": n_legit,
        "disposable_count": n_disp,
        "class_ratio": round(n_legit / max(n_disp, 1), 2),
        "composition": {
            "unseen_disposable_domains": "Domains NOT in training blocklist (emailondeck, mohmal, etc.)",
            "modern_consumer_addresses": "HEY, Tuta, Skiff, DuckDuckGo, Vivaldi",
            "internationalized_names": "Swedish, German, Japanese, Russian, Arabic",
            "corporate_patterns": "Toyota, Deloitte, Philips, Dangote",
            "edge_cases": "Very short addresses, plus-addressing, bot-generated",
            "hard_negatives": "Normal-looking names on disposable domains",
        },
        "expected_behaviour": (
            "Performance degradation on OOD data is EXPECTED. "
            "The model was trained on Enron-era addresses and common blocklist domains. "
            "OOD accuracy below in-distribution accuracy is an honest finding, "
            "not a failure — it motivates future work on domain adaptation."
        ),
    }
