"""
Latency and probe-reduction analysis.

The entire "ML pre-screening saves SMTP probes" claim was asserted
but never measured. This module actually does the measurement:
  1. Per-layer p50/p95/p99 breakdown
  2. ML short-circuit impact: how many SMTP probes did we avoid?
  3. Bootstrap CIs on the latency percentiles
  4. A/B comparison: pipeline with and without ML
  5. ML ROI: was the classifier worth the compute?
"""

from __future__ import annotations

import numpy as np
import time
from typing import Dict, List, Tuple, Any
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class LatencySample:
    """A single pipeline-run timing measurement."""
    email: str
    total_ms: float
    syntax_ms: float
    dns_ms: float
    ml_ms: float
    smtp_ms: float
    ml_skipped: bool            # True if ML was bypassed (syntax/dns rejected first)
    smtp_attempted: bool        # True if SMTP was actually probed
    final_status: str = ""      # valid / invalid / suspicious / uncertain
    short_circuited_by: str = ""  # Which layer stopped processing: syntax, dns, ml, or ""


class LatencyAnalysis:
    """Slice and dice latency samples."""

    def __init__(self, samples: List[LatencySample]):
        self.samples = samples

    def percentile_latencies(self) -> Dict[str, Dict[str, float]]:
        """p50/p95/p99 for each layer and the total pipeline."""
        result = {}

        layer_attrs = {
            'total': 'total_ms',
            'syntax': 'syntax_ms',
            'dns': 'dns_ms',
            'ml': 'ml_ms',
            'smtp': 'smtp_ms',
        }

        for layer_name, attr_name in layer_attrs.items():
            values = [getattr(s, attr_name) for s in self.samples]
            if not values:
                continue
            result[layer_name] = {
                "p50": round(float(np.percentile(values, 50)), 2),
                "p95": round(float(np.percentile(values, 95)), 2),
                "p99": round(float(np.percentile(values, 99)), 2),
                "mean": round(float(np.mean(values)), 2),
                "stdev": round(float(np.std(values)), 2),
                "min": round(float(np.min(values)), 2),
                "max": round(float(np.max(values)), 2),
            }

        return result

    def ml_short_circuit_impact(self) -> Dict[str, Any]:
        """The money metric: how much SMTP latency did the ML layer save us?"""
        total = len(self.samples)
        if total == 0:
            return {"error": "No samples to analyze"}

        ml_skipped = sum(1 for s in self.samples if s.ml_skipped)
        smtp_attempted = sum(1 for s in self.samples if s.smtp_attempted)

        # Compare latencies: requests that hit SMTP vs. those that didn't
        with_smtp = [s.total_ms for s in self.samples if s.smtp_attempted]
        without_smtp = [s.total_ms for s in self.samples if not s.smtp_attempted]

        avg_with = float(np.mean(with_smtp)) if with_smtp else 0
        avg_without = float(np.mean(without_smtp)) if without_smtp else 0
        improvement = ((avg_with - avg_without) / avg_with * 100) if avg_with > 0 else 0

        # Specifically, how many were short-circuited by the ML layer?
        ml_short_circuits = sum(
            1 for s in self.samples
            if s.short_circuited_by == "ml"
        )

        return {
            "total_samples": total,
            "ml_short_circuit_count": ml_short_circuits,
            "ml_short_circuit_pct": round(float(ml_short_circuits / total * 100), 2),
            "smtp_attempted_count": smtp_attempted,
            "smtp_attempted_pct": round(float(smtp_attempted / total * 100), 2),
            "smtp_skipped_count": total - smtp_attempted,
            "smtp_skipped_pct": round(float((total - smtp_attempted) / total * 100), 2),
            "avg_latency_with_smtp_ms": round(avg_with, 2),
            "avg_latency_without_smtp_ms": round(avg_without, 2),
            "latency_improvement_pct": round(float(improvement), 2),
            "interpretation": (
                f"ML pre-screening short-circuited {ml_short_circuits}/{total} "
                f"({ml_short_circuits/total*100:.1f}%) emails, avoiding expensive "
                f"SMTP probes. Average latency reduced by {improvement:.1f}% "
                f"when SMTP is skipped."
            ),
        }

    def layer_contribution(self) -> Dict[str, Any]:
        """How much of the total latency does each layer eat?"""
        total_by_layer = defaultdict(float)
        count_by_layer = defaultdict(int)

        for sample in self.samples:
            total_by_layer['syntax'] += sample.syntax_ms
            count_by_layer['syntax'] += 1

            if sample.dns_ms > 0:
                total_by_layer['dns'] += sample.dns_ms
                count_by_layer['dns'] += 1

            if not sample.ml_skipped and sample.ml_ms > 0:
                total_by_layer['ml'] += sample.ml_ms
                count_by_layer['ml'] += 1

            if sample.smtp_attempted and sample.smtp_ms > 0:
                total_by_layer['smtp'] += sample.smtp_ms
                count_by_layer['smtp'] += 1

        grand_total = sum(total_by_layer.values())
        if grand_total == 0:
            return {"error": "No latency data"}

        result = {}
        for layer in ['syntax', 'dns', 'ml', 'smtp']:
            pct = total_by_layer[layer] / grand_total * 100
            avg = total_by_layer[layer] / max(count_by_layer[layer], 1)
            result[layer] = {
                "total_time_ms": round(float(total_by_layer[layer]), 2),
                "pct_of_total": round(float(pct), 2),
                "avg_per_call_ms": round(float(avg), 2),
                "call_count": count_by_layer[layer],
            }

        return result

    def percentile_confidence_intervals(
        self, alpha: float = 0.05, n_bootstrap: int = 1000
    ) -> Dict[str, Dict[str, Tuple[float, float]]]:
        """Bootstrap 95% CIs on the latency percentiles."""
        rng = np.random.RandomState(42)
        result = {}

        layer_attrs = {
            'total': 'total_ms',
            'syntax': 'syntax_ms',
            'dns': 'dns_ms',
            'ml': 'ml_ms',
            'smtp': 'smtp_ms',
        }

        for layer_name, attr_name in layer_attrs.items():
            values = np.array([getattr(s, attr_name) for s in self.samples])
            if len(values) == 0:
                continue

            result[layer_name] = {}

            for percentile in [50, 95, 99]:
                bootstrap_percentiles = []

                for _ in range(n_bootstrap):
                    sample = rng.choice(values, size=len(values), replace=True)
                    bootstrap_percentiles.append(np.percentile(sample, percentile))

                bootstrap_arr = np.array(bootstrap_percentiles)
                lower = np.percentile(bootstrap_arr, alpha / 2 * 100)
                upper = np.percentile(bootstrap_arr, (1 - alpha / 2) * 100)

                result[layer_name][f"p{percentile}_ci"] = (
                    round(float(lower), 2),
                    round(float(upper), 2),
                )

        return result


class ProbeReductionAnalysis:
    """DNS and SMTP probe reduction stats."""

    def __init__(self, samples: List[LatencySample]):
        self.samples = samples

    def dns_probe_statistics(self) -> Dict[str, Any]:
        """How often did we actually fire a DNS query?"""
        total = len(self.samples)
        dns_attempts = sum(1 for s in self.samples if s.dns_ms > 0)
        total_dns_ms = sum(s.dns_ms for s in self.samples)

        return {
            "total_dns_queries": dns_attempts,
            "dns_query_rate_pct": round(float(dns_attempts / max(total, 1) * 100), 2),
            "avg_dns_latency_ms": round(float(total_dns_ms / max(dns_attempts, 1)), 2),
            "total_dns_latency_ms": round(total_dns_ms, 2),
        }

    def smtp_probe_statistics(self) -> Dict[str, Any]:
        """SMTP is the most expensive layer — how often did we call it?"""
        total = len(self.samples)
        smtp_attempts = sum(1 for s in self.samples if s.smtp_attempted)
        total_smtp_ms = sum(s.smtp_ms for s in self.samples if s.smtp_attempted)

        return {
            "total_smtp_probes": smtp_attempts,
            "smtp_probe_rate_pct": round(float(smtp_attempts / max(total, 1) * 100), 2),
            "smtp_skipped_count": total - smtp_attempts,
            "smtp_skipped_pct": round(float((total - smtp_attempts) / max(total, 1) * 100), 2),
            "avg_smtp_latency_ms": round(float(total_smtp_ms / max(smtp_attempts, 1)), 2),
            "total_smtp_latency_ms": round(total_smtp_ms, 2),
        }

    def ml_efficiency_report(self) -> Dict[str, Any]:
        """Was the ML layer worth the compute? Cost vs. probes saved."""
        total_ml_ms = sum(s.ml_ms for s in self.samples if not s.ml_skipped)
        ml_count = sum(1 for s in self.samples if not s.ml_skipped)

        probes_saved = sum(
            1 for s in self.samples
            if not s.ml_skipped and not s.smtp_attempted
        )

        ml_cost_per_email = total_ml_ms / max(ml_count, 1)

        # Average SMTP time per probe — this is what we save per skipped probe
        avg_smtp_ms = 0
        smtp_samples = [s for s in self.samples if s.smtp_attempted]
        if smtp_samples:
            avg_smtp_ms = float(np.mean([s.smtp_ms for s in smtp_samples]))

        time_saved_ms = probes_saved * avg_smtp_ms
        ml_total_cost_ms = total_ml_ms

        roi = time_saved_ms / max(ml_total_cost_ms, 0.1)

        if roi > 5:
            assessment = "EXCELLENT: ML cost heavily justified by probe reduction"
        elif roi > 2:
            assessment = "GOOD: ML cost justified by significant probe reduction"
        elif roi > 1:
            assessment = "MODEST: ML provides some net benefit"
        else:
            assessment = "MARGINAL: ML cost roughly equals savings — consider threshold tuning"

        return {
            "ml_cost_per_email_ms": round(ml_cost_per_email, 2),
            "ml_total_cost_ms": round(ml_total_cost_ms, 2),
            "probes_saved_by_ml": probes_saved,
            "estimated_smtp_time_saved_ms": round(time_saved_ms, 2),
            "roi_ratio": round(roi, 2),
            "ml_roi_assessment": assessment,
        }


class ShortCircuitExperiment:
    """
    A/B test: same emails, once with ML and once without.
    Quantifies the actual contribution of the classifier to tail latency.
    """

    def __init__(
        self,
        samples_with_ml: List[LatencySample],
        samples_without_ml: List[LatencySample],
    ):
        self.with_ml = samples_with_ml
        self.without_ml = samples_without_ml

    def compare(self) -> Dict[str, Any]:
        """Side-by-side latency comparison."""
        with_latencies = np.array([s.total_ms for s in self.with_ml])
        without_latencies = np.array([s.total_ms for s in self.without_ml])

        with_smtp_rate = sum(1 for s in self.with_ml if s.smtp_attempted) / max(len(self.with_ml), 1)
        without_smtp_rate = sum(1 for s in self.without_ml if s.smtp_attempted) / max(len(self.without_ml), 1)

        smtp_reduction = (without_smtp_rate - with_smtp_rate) / max(without_smtp_rate, 0.01) * 100

        return {
            "with_ml": {
                "sample_count": len(self.with_ml),
                "p50_ms": round(float(np.percentile(with_latencies, 50)), 2),
                "p95_ms": round(float(np.percentile(with_latencies, 95)), 2),
                "p99_ms": round(float(np.percentile(with_latencies, 99)), 2),
                "mean_ms": round(float(np.mean(with_latencies)), 2),
                "smtp_call_rate_pct": round(with_smtp_rate * 100, 2),
            },
            "without_ml": {
                "sample_count": len(self.without_ml),
                "p50_ms": round(float(np.percentile(without_latencies, 50)), 2),
                "p95_ms": round(float(np.percentile(without_latencies, 95)), 2),
                "p99_ms": round(float(np.percentile(without_latencies, 99)), 2),
                "mean_ms": round(float(np.mean(without_latencies)), 2),
                "smtp_call_rate_pct": round(without_smtp_rate * 100, 2),
            },
            "impact": {
                "smtp_reduction_pct": round(smtp_reduction, 2),
                "mean_latency_reduction_pct": round(
                    float((np.mean(without_latencies) - np.mean(with_latencies))
                          / max(np.mean(without_latencies), 0.01) * 100), 2
                ),
                "p95_latency_reduction_pct": round(
                    float((np.percentile(without_latencies, 95) - np.percentile(with_latencies, 95))
                          / max(np.percentile(without_latencies, 95), 0.01) * 100), 2
                ),
            },
        }
