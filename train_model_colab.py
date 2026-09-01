"""
Google Colab training script for the email-verifier classifier benchmark.

Use in Colab:
  1. Upload this file plus either a labelled dataset OR the valid/invalid CSVs.
  2. Run: !python train_model_colab.py --valid-data valid_emails_v2.csv \\
         --invalid-data invalid_emails_v2.csv
  3. Download `rf_model.joblib` and replace `models/rf_model.joblib` locally.

Colab dependency cell:
  !pip install -q pandas numpy scikit-learn joblib xgboost

The saved artifact is compatible with app/pipeline/ml_handler.py:
    {"model": selected_classifier, "metadata": {...}}

Evaluation protocol:
  * 60% domain-disjoint training set: model fitting.
  * 20% domain-disjoint validation set: benchmark comparison and model selection.
  * 20% domain-disjoint test set: one final, untouched evaluation of the winner.

For a single `--data` CSV, the label contract is 0 = legitimate and
1 = disposable/high-risk.  When `--valid-data` and `--invalid-data` are used,
their source filenames define the labels and any existing label columns are
intentionally ignored.

Probability note:
  The exported classifier uses raw ``predict_proba`` values. No post-hoc
  calibration (for example, Platt scaling or isotonic regression) is applied.
  These values are risk scores and must not be described as calibrated
  probabilities.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import re

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, cross_val_score
from sklearn.naive_bayes import GaussianNB
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.base import clone


FEATURE_ORDER = [
    "local_length", "domain_length", "digit_ratio", "special_char_ratio",
    "vowel_ratio", "consonant_ratio", "entropy", "normalised_entropy",
    "has_repeated_chars", "suspicious_token", "digit_run_length", "dot_count",
    "hyphen_count", "starts_with_digit", "max_consecutive_consonants",
    "avg_qwerty_distance", "domain_hyphen_count", "domain_digit_ratio",
]
SUSPICIOUS_TOKENS = {
    "temp", "temporary", "disposable", "mailinator", "guerrilla", "throwaway",
    "trash", "fake", "spam", "junk", "burner", "noreply", "test",
}
VOWELS = set("aeiou")
CONSONANTS = set("bcdfghjklmnpqrstvwxyz")
QWERTY = {
    **{char: (0, i) for i, char in enumerate("qwertyuiop")},
    **{char: (1, i + 0.25) for i, char in enumerate("asdfghjkl")},
    **{char: (2, i + 0.75) for i, char in enumerate("zxcvbnm")},
    **{char: (-1, i) for i, char in enumerate("1234567890")},
}


def entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = {c: text.count(c) for c in set(text)}
    size = len(text)
    return -sum((n / size) * math.log2(n / size) for n in counts.values())


def normalised_entropy(text: str) -> float:
    if len(text) < 2:
        return 0.0
    return entropy(text) / math.log2(len(text))


def max_consecutive_consonants(text: str) -> float:
    longest = current = 0
    for char in text:
        if char in CONSONANTS:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return float(longest)


def avg_qwerty_distance(text: str) -> float:
    chars = [c for c in text if c in QWERTY]
    if len(chars) < 2:
        return 0.0
    distances = [
        math.dist(QWERTY[first], QWERTY[second])
        for first, second in zip(chars, chars[1:])
    ]
    return round(sum(distances) / len(distances), 4)


def extract_features(email: str) -> list[float]:
    """Must remain in the same order as app.services.feature_extractor."""
    local, domain = email.lower().rsplit("@", 1)
    length = max(len(local), 1)
    digit_runs = re.findall(r"\d+", local)
    return [
        float(len(local)),
        float(len(domain)),
        sum(c.isdigit() for c in local) / length,
        sum(not c.isalnum() and c not in ".-_" for c in local) / length,
        sum(c in VOWELS for c in local) / length,
        sum(c in CONSONANTS for c in local) / length,
        entropy(local),
        normalised_entropy(local),
        float(bool(re.search(r"(.)\1{2,}", local))),
        float(any(token in f"{local} {domain}" for token in SUSPICIOUS_TOKENS)),
        float(max((len(run) for run in digit_runs), default=0)),
        float(local.count(".")),
        float(local.count("-")),
        float(local[:1].isdigit()),
        max_consecutive_consonants(local),
        avg_qwerty_distance(local),
        float(domain.count("-")),
        sum(c.isdigit() for c in domain) / max(len(domain), 1),
    ]


def metrics(y_true: np.ndarray, probability: np.ndarray) -> dict:
    prediction = (probability >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, prediction, labels=[0, 1], zero_division=0
    )
    tn, fp, fn, tp = confusion_matrix(y_true, prediction, labels=[0, 1]).ravel()
    return {
        "accuracy": round(float(accuracy_score(y_true, prediction)), 4),
        "f1_macro": round(float(f1_score(y_true, prediction, average="macro")), 4),
        "recall_legitimate": round(float(recall[0]), 4),
        "recall_disposable": round(float(recall[1]), 4),
        "mcc": round(float(matthews_corrcoef(y_true, prediction)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, probability)), 4),
        "pr_auc": round(float(average_precision_score(y_true, probability)), 4),
        "brier_score": round(float(brier_score_loss(y_true, probability)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def model_candidates() -> dict:
    """Return the four classifiers compared in the dissertation evaluation."""
    try:
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise RuntimeError(
            "XGBoost is required for the comparison. In Colab run: "
            "!pip install -q xgboost"
        ) from exc

    return {
        "Random Forest": RandomForestClassifier(
            n_estimators=400, max_features="sqrt", min_samples_leaf=2,
            class_weight="balanced", random_state=42, n_jobs=1,
        ),
        "SVM (RBF)": Pipeline([
            ("scaler", StandardScaler()),
            ("classifier", SVC(
                kernel="rbf", C=2.0, gamma="scale", probability=True,
                class_weight="balanced", random_state=42,
            )),
        ]),
        "Gaussian Naive Bayes": GaussianNB(),
        "XGBoost": XGBClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05,
            subsample=0.85, colsample_bytree=0.85,
            objective="binary:logistic", eval_metric="logloss",
            random_state=42, n_jobs=1,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", help="CSV containing email,label columns (0=legitimate, 1=invalid)")
    parser.add_argument("--valid-data", help="CSV containing known/synthetic valid emails")
    parser.add_argument("--invalid-data", help="CSV containing known/synthetic invalid emails")
    parser.add_argument("--output", default="rf_model.joblib")
    parser.add_argument(
        "--deploy-model", default="best",
        choices=["best", "Random Forest", "SVM (RBF)", "Gaussian Naive Bayes", "XGBoost"],
        help="Model to save after comparison; default selects the highest validation macro-F1.",
    )
    # Jupyter/Colab injects a kernel connection argument (usually `-f
    # ...kernel-*.json`) when a script is executed through notebook tooling.
    # Ignore those runner-specific arguments; keep parsing the arguments that
    # belong to this training script.
    args, unknown_args = parser.parse_known_args()
    if unknown_args:
        print(f"Ignoring notebook arguments: {' '.join(unknown_args)}")

    if args.data and (args.valid_data or args.invalid_data):
        raise ValueError("Use either --data or the --valid-data/--invalid-data pair, not both.")
    if bool(args.valid_data) != bool(args.invalid_data):
        raise ValueError("Provide both --valid-data and --invalid-data together.")
    if not args.data and not args.valid_data:
        raise ValueError("Provide --data or both --valid-data and --invalid-data.")

    if args.data:
        data = pd.read_csv(args.data)
        if not {"email", "label"}.issubset(data.columns):
            raise ValueError("Dataset must contain `email` and `label` columns.")
    else:
        valid_data = pd.read_csv(args.valid_data)
        invalid_data = pd.read_csv(args.invalid_data)
        if "email" not in valid_data or "email" not in invalid_data:
            raise ValueError("Both source datasets must contain an `email` column.")
        # Project convention: 0=legitimate, 1=disposable/high-risk.
        # Ignore the input label columns because these two v2 files use the reverse encoding.
        valid_data = valid_data[["email"]].assign(label=0)
        invalid_data = invalid_data[["email"]].assign(label=1)
        data = pd.concat([valid_data, invalid_data], ignore_index=True)

    data = data.dropna(subset=["email", "label"]).copy()
    data["email"] = data["email"].astype(str).str.strip().str.lower()
    data["label"] = data["label"].astype(int)
    if not set(data.label.unique()).issubset({0, 1}):
        raise ValueError("Labels must be 0 (legitimate) or 1 (disposable/high-risk).")

    valid = data.email.str.count("@") == 1
    data = data[valid].copy()
    data["domain"] = data.email.str.rsplit("@", n=1).str[-1]
    X = np.asarray([extract_features(email) for email in data.email], dtype=np.float32)
    y = data.label.to_numpy(dtype=int)
    groups = data.domain.to_numpy()

    # First reserve a completely untouched 20% test set by domain.
    # Then split the remaining 80% into 75% train / 25% validation, producing
    # approximately 60/20/20 of the full dataset without domain leakage.
    test_splitter = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=42)
    train_val_idx, test_idx = next(test_splitter.split(X, y, groups))
    validation_splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=43)
    train_relative_idx, validation_relative_idx = next(
        validation_splitter.split(X[train_val_idx], y[train_val_idx], groups[train_val_idx])
    )
    train_idx = train_val_idx[train_relative_idx]
    validation_idx = train_val_idx[validation_relative_idx]

    X_train, y_train = X[train_idx], y[train_idx]
    X_validation, y_validation = X[validation_idx], y[validation_idx]
    X_train_val, y_train_val = X[train_val_idx], y[train_val_idx]
    X_test, y_test = X[test_idx], y[test_idx]

    candidates = model_candidates()
    folds = min(5, len(np.unique(groups[train_idx])))
    comparison = {}
    for name, candidate in candidates.items():
        candidate.fit(X_train, y_train)
        probability = candidate.predict_proba(X_validation)[:, 1]
        cv_scores = cross_val_score(
            candidate, X_train, y_train, groups=groups[train_idx],
            cv=GroupKFold(n_splits=folds), scoring="f1_macro", n_jobs=1,
        )
        comparison[name] = {
            "validation": metrics(y_validation, probability),
            "training_grouped_cv_f1_macro_mean": round(float(cv_scores.mean()), 4),
            "training_grouped_cv_f1_macro_std": round(float(cv_scores.std()), 4),
            "training_grouped_cv_fold_scores": [round(float(score), 4) for score in cv_scores],
        }
        print(
            f"{name}: validation macro-F1={comparison[name]['validation']['f1_macro']:.4f}; "
            f"training grouped-CV macro-F1="
            f"{comparison[name]['training_grouped_cv_f1_macro_mean']:.4f}"
        )

    best_name = max(
        comparison,
        key=lambda name: comparison[name]["validation"]["f1_macro"],
    )
    selected_name = best_name if args.deploy_model == "best" else args.deploy_model
    # Refit only the selected configuration on train+validation.  The test set
    # is evaluated once, after selection, and is never used for fitting/tuning.
    model = clone(candidates[selected_name])
    model.fit(X_train_val, y_train_val)
    final_test_metrics = metrics(y_test, model.predict_proba(X_test)[:, 1])
    print(
        f"\nSelected model: {selected_name}. Final untouched test macro-F1="
        f"{final_test_metrics['f1_macro']:.4f}; accuracy={final_test_metrics['accuracy']:.4f}"
    )
    selected = comparison[selected_name]
    metadata = {
        "model_name": selected_name,
        "selection_criterion": "Highest domain-disjoint validation macro-F1",
        "best_model": best_name,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "random_state": 42,
        "n_samples_total": int(len(data)),
        "n_unique_domains": int(data.domain.nunique()),
        "train_size": int(len(train_idx)),
        "validation_size": int(len(validation_idx)),
        "train_validation_size": int(len(train_val_idx)),
        "test_size": int(len(test_idx)),
        "train_unique_domains": int(len(set(groups[train_idx]))),
        "validation_unique_domains": int(len(set(groups[validation_idx]))),
        "test_unique_domains": int(len(set(groups[test_idx]))),
        "validation_metrics": selected["validation"],
        "test_accuracy": final_test_metrics["accuracy"],
        "test_metrics": final_test_metrics,
        "cv_f1_macro_mean": selected["training_grouped_cv_f1_macro_mean"],
        "cv_f1_macro_std": selected["training_grouped_cv_f1_macro_std"],
        "cv_fold_scores": selected["training_grouped_cv_fold_scores"],
        "model_comparison": comparison,
        "feature_order": FEATURE_ORDER,
        "positive_class": 1,
        "label_definition": "0=legitimate, 1=disposable/high-risk",
        "probability_calibrated": False,
        "probability_note": (
            "Raw classifier probabilities; no post-hoc calibration method was applied."
        ),
        "evaluation_protocol": (
            "Domain-disjoint 60/20/20 train/validation/test split; model selected "
            "on validation macro-F1, retrained on train+validation, and evaluated once on test"
        ),
    }
    joblib.dump({"model": model, "metadata": metadata}, args.output)
    Path(f"{args.output}.metadata.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, indent=2))
    print(f"\nSaved model: {args.output}")


if __name__ == "__main__":
    main()
