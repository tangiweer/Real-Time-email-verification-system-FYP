#!/usr/bin/env python3
"""
Comprehensive Evaluation Runner.

Single entry-point that:
  1. Loads/generates training data with proper methodology
  2. Trains model with domain-disjoint awareness
  3. Runs the full 10-area evaluation
  4. Produces a comprehensive JSON report
  5. Prints human-readable summary

Usage:
    python -m evaluation.run_evaluation
    python -m evaluation.run_evaluation --output path/to/report.json
    python -m evaluation.run_evaluation --dataset data/real_evaluation_dataset.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.ml_model import MLModelService
from app.services.feature_extractor import FEATURE_ORDER
from evaluation.comprehensive_evaluator import ComprehensiveEvaluator
from evaluation.ood_test_set import get_ood_test_set, get_ood_test_metadata


def _print_summary(report: dict) -> None:
    """Print a human-readable summary of the evaluation report."""
    print("\n" + "=" * 70)
    print("  COMPREHENSIVE EVALUATION REPORT — SUMMARY")
    print("=" * 70)

    areas = report.get("improvement_areas", {})

    # Area 1: Split quality
    split = areas.get("1_dataset_split", {})
    sq = split.get("split_quality_analysis", {})
    print(f"\n  [1] Dataset Split")
    print(f"      Method:  {split.get('method', 'N/A')}")
    print(f"      Train:   {split.get('train_size', '?')} samples")
    print(f"      Test:    {split.get('test_size', '?')} samples")
    print(f"      Leakage: {'NONE ✓' if not sq.get('leakage_detected', True) else 'DETECTED ⚠'}")
    print(f"      Train domains: {sq.get('train_unique_domains', '?')}")
    print(f"      Test domains:  {sq.get('test_unique_domains', '?')}")

    # Area 3: Metrics
    metrics = areas.get("3_metrics_suite", {}).get("metrics_8_suite", {})
    if metrics:
        print(f"\n  [3] 8-Metric Suite (held-out test)")
        print(f"      Accuracy:          {metrics.get('accuracy', 'N/A')}")
        print(f"      Balanced Accuracy: {metrics.get('balanced_accuracy', 'N/A')}")
        print(f"      F1 (macro):        {metrics.get('f1_macro', 'N/A')}")
        print(f"      MCC:               {metrics.get('matthews_corr_coef', 'N/A')}")
        print(f"      ROC-AUC:           {metrics.get('roc_auc', 'N/A')}")
        print(f"      PR-AUC:            {metrics.get('pr_auc', 'N/A')}")
        print(f"      Brier Score:       {metrics.get('brier_score', 'N/A')}")

        recall = metrics.get("recall_per_class", {})
        print(f"      Recall (legit):    {recall.get('legitimate', 'N/A')}  ← PRIMARY METRIC")
        print(f"      Recall (disp):     {recall.get('disposable', 'N/A')}")

        cm = metrics.get("confusion_matrix", {})
        if cm:
            print(f"      Confusion Matrix:  TN={cm.get('true_negatives')}, FP={cm.get('false_positives')}, "
                  f"FN={cm.get('false_negatives')}, TP={cm.get('true_positives')}")

        warning = metrics.get("separability_warning")
        if warning:
            print(f"      ⚠ {warning}")

    # Area 4: Baselines
    baselines = areas.get("4_baselines", {}).get("baselines_comparison", {})
    if baselines:
        print(f"\n  [4] System-Level Baselines")
        for name, result in baselines.items():
            if isinstance(result, dict):
                print(f"      {name}: F1={result.get('f1_macro', 'N/A')}, "
                      f"Recall(legit)={result.get('recall_legitimate', 'N/A')}")

    mcnemar = areas.get("4_baselines", {}).get("mcnemar_tests", {})
    if mcnemar:
        print(f"      McNemar's Tests:")
        for name, result in mcnemar.items():
            if isinstance(result, dict):
                sig = "SIG" if result.get("significant_at_0_05") else "n.s."
                print(f"        {name}: p={result.get('p_value', 'N/A')} ({sig})")

    # Area 5: Statistical rigor
    rigor = areas.get("5_statistical_rigor", {})
    cis = rigor.get("bootstrap_confidence_intervals", {})
    if cis:
        print(f"\n  [5] Statistical Rigor (Bootstrap 95% CIs)")
        for metric, vals in cis.items():
            if isinstance(vals, dict) and vals.get("ci_lower") is not None:
                print(f"      {metric}: {vals['mean']} [{vals['ci_lower']}, {vals['ci_upper']}]")

    # Area 6: Calibration
    calib = areas.get("6_calibration", {}).get("calibration_analysis", {})
    if calib:
        print(f"\n  [6] Probability Calibration")
        print(f"      ECE:         {calib.get('expected_calibration_error', 'N/A')}")
        print(f"      MCE:         {calib.get('max_calibration_error', 'N/A')}")
        print(f"      Brier:       {calib.get('brier_score', 'N/A')}")
        print(f"      Assessment:  {calib.get('recommendation', 'N/A')}")

    # Area 7: Feature attribution
    dominance = areas.get("7_feature_attribution", {}).get("domain_feature_dominance", {})
    if dominance:
        print(f"\n  [7] Feature Attribution")
        print(f"      Domain feature ratio: {dominance.get('domain_importance_pct', 'N/A')}%")
        print(f"      Assessment: {dominance.get('leakage_risk_assessment', 'N/A')}")

    # Top 5 features
    ranking = areas.get("7_feature_attribution", {}).get("combined_feature_ranking", {})
    if ranking:
        features = ranking.get("feature_contributions", [])[:5]
        if features:
            print(f"      Top 5 features:")
            for f in features:
                marker = " (domain)" if f.get("is_domain_feature") else ""
                print(f"        #{f['ranking']} {f['feature']}: {f['combined_score']}{marker}")

    # Area 8: Ablation
    ablation = areas.get("8_ablation_study", {}).get("ablation_comparisons", {})
    if ablation:
        print(f"\n  [8] Local-Part Ablation")
        for metric, result in ablation.items():
            if isinstance(result, dict) and "score_drop_pct" in result:
                print(f"      {metric}: {result.get('original_score', 'N/A')} → "
                      f"{result.get('ablated_score', 'N/A')} "
                      f"(↓{result.get('score_drop_pct', 'N/A')}%)")
                print(f"        → {result.get('interpretation', '')}")

    # Area 9: Latency
    latency = areas.get("9_latency_performance", {})
    percentiles = latency.get("latency_percentiles", {}).get("total", {})
    if percentiles:
        print(f"\n  [9] Latency Performance")
        print(f"      p50:  {percentiles.get('p50', 'N/A')} ms")
        print(f"      p95:  {percentiles.get('p95', 'N/A')} ms")
        print(f"      p99:  {percentiles.get('p99', 'N/A')} ms")

    short_circuit = latency.get("ml_short_circuit_impact", {})
    if short_circuit:
        print(f"      SMTP skipped:    {short_circuit.get('smtp_skipped_pct', 'N/A')}%")
        print(f"      ML short-circuit: {short_circuit.get('ml_short_circuit_pct', 'N/A')}%")

    # Area 10: OOD
    ood = areas.get("10_out_of_distribution", {})
    ood_metrics = ood.get("ood_metrics", {})
    if ood_metrics:
        print(f"\n  [10] Out-of-Distribution Evaluation")
        print(f"      OOD samples:       {ood.get('ood_test_size', 'N/A')}")
        print(f"      OOD Accuracy:      {ood_metrics.get('accuracy', 'N/A')}")
        print(f"      OOD F1 (macro):    {ood_metrics.get('f1_macro', 'N/A')}")
        print(f"      OOD Bal. Accuracy: {ood_metrics.get('balanced_accuracy', 'N/A')}")
        print(f"      OOD MCC:           {ood_metrics.get('matthews_corr_coef', 'N/A')}")

        ood_recall = ood_metrics.get("recall_per_class", {})
        print(f"      OOD Recall (legit): {ood_recall.get('legitimate', 'N/A')}")
        print(f"      OOD Recall (disp):  {ood_recall.get('disposable', 'N/A')}")

    print("\n" + "=" * 70)
    print("  ✓ All 10 improvement areas evaluated")
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run comprehensive 10-area evaluation of the email verification system."
    )
    parser.add_argument(
        "--output", "-o",
        default="evaluation/comprehensive_evaluation_report.json",
        help="Output path for the JSON report",
    )
    parser.add_argument(
        "--dataset",
        default="data/evaluation_dataset.csv",
        help="Path to the evaluation dataset CSV (must contain 'email' and 'label' columns)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  Email Verification System — Comprehensive Evaluation")
    print("  Addressing 10 Critical Feedback Dimensions")
    print("=" * 70)

    # Step 1: Load/train model
    print("\n[Step 1] Loading ML model...")
    start = time.time()
    ml_model = MLModelService()
    print(f"[Step 1] Model ready ({time.time() - start:.1f}s)")
    print(f"[Step 1] Training metadata: {ml_model.metadata}")

    # Step 2: Get training data for evaluation
    print("\n[Step 2] Preparing evaluation datasets...")
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Evaluation dataset not found at {dataset_path}. "
            "Please provide the real dataset used to produce the comprehensive evaluation report, "
            "or specify its path using --dataset."
        )
    
    emails_list = []
    labels_list = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "email" in row and "label" in row and "@" in row["email"]:
                emails_list.append(row["email"])
                labels_list.append(int(row["label"]))
    
    emails = np.array(emails_list)
    labels = np.array(labels_list)
    print(f"[Step 2] Total dataset: {len(emails)} samples "
          f"({sum(1 for l in labels if l == 0)} legitimate, "
          f"{sum(1 for l in labels if l == 1)} disposable)")

    # Step 3: Get OOD test set
    print("\n[Step 3] Loading OOD test set...")
    ood_emails, ood_labels = get_ood_test_set()
    ood_meta = get_ood_test_metadata()
    print(f"[Step 3] OOD test set: {ood_meta['total_samples']} samples "
          f"({ood_meta['legitimate_count']} legitimate, "
          f"{ood_meta['disposable_count']} disposable)")

    # Step 4: Run comprehensive evaluation
    print("\n[Step 4] Running comprehensive evaluation...")
    evaluator = ComprehensiveEvaluator(
        model=ml_model.model,
        feature_names=FEATURE_ORDER,
        emails=emails,
        labels=labels,
        output_dir=str(Path(args.output).parent),
    )

    start = time.time()
    report = evaluator.generate_comprehensive_report(
        ood_test_emails=ood_emails,
        ood_test_labels=ood_labels,
    )
    elapsed = time.time() - start
    print(f"\n[Step 4] Evaluation complete ({elapsed:.1f}s)")

    # Step 5: Save report
    print(f"\n[Step 5] Saving report...")
    output_path = evaluator.save_report(Path(args.output).name)

    # Step 6: Print summary
    _print_summary(report)

    print(f"Full report saved to: {output_path}")


if __name__ == "__main__":
    main()
