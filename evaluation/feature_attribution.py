"""
Feature attribution and interpretability.

The pipeline has a 20-dim feature vector but zero visibility into
which features actually drive predictions. This module adds:
  1. Permutation importance (reliable, model-agnostic)
  2. Tree-based Gini importance (biased but fast)
  3. Bias check: if domain features dominate, the model is leaking
  4. Per-feature ablation (zero out one feature at a time)
  5. Combined ranking (weighted permutation + tree)
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Any
from sklearn.inspection import permutation_importance
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score
import warnings

warnings.filterwarnings('ignore')

# Domain-level features that could encode target leakage
DOMAIN_FEATURES = {
    'is_known_provider', 'domain_tld_suspicious', 'domain_hyphen_count',
    'domain_digit_ratio', 'domain_length', 'suspicious_token',
}


class FeatureAttribution:
    """Feature importance via multiple methods."""

    def __init__(
        self,
        model: RandomForestClassifier,
        feature_names: List[str],
        X_test: np.ndarray,
        y_test: np.ndarray,
    ):
        """
        Args:
            model: Trained RandomForestClassifier
            feature_names: List of feature names (in order)
            X_test: Test features
            y_test: Test labels
        """
        self.model = model
        self.feature_names = feature_names
        self.X_test = X_test
        self.y_test = y_test
        self._perm_cache = None   # avoid re-running the expensive permutation loop

    @staticmethod
    def _get_base_estimator(model):
        """Return feature importances from a direct estimator or optional wrapper."""
        # Support optional calibrated-model wrappers in future experiments.
        if hasattr(model, 'calibrated_classifiers_'):
            # CalibratedClassifierCV stores N sub-estimators; average their importances
            sub_importances = []
            for cc in model.calibrated_classifiers_:
                base = cc.estimator
                # Handle FrozenEstimator wrapper
                if hasattr(base, 'estimator'):
                    base = base.estimator
                if hasattr(base, 'feature_importances_'):
                    sub_importances.append(base.feature_importances_)
            if sub_importances:
                import numpy as _np
                return _np.mean(sub_importances, axis=0)
        # Direct estimator attribute (older sklearn)
        if hasattr(model, 'estimator'):
            base = model.estimator
            if hasattr(base, 'feature_importances_'):
                return base.feature_importances_
        # Raw model
        if hasattr(model, 'feature_importances_'):
            return model.feature_importances_
        return None

    def tree_importance(self) -> Dict[str, float]:
        """Gini importance from the RF. Fast but biased toward high-cardinality features."""
        importances = self._get_base_estimator(self.model)
        if importances is None:
            # Can't extract importances from this model type — return zeros as a fallback
            return {name: 0.0 for name in self.feature_names}
        return {
            name: round(float(imp), 4)
            for name, imp in zip(self.feature_names, importances)
        }

    def permutation_importance_scores(
        self, n_repeats: int = 10, random_state: int = 42
    ) -> Dict[str, Dict[str, float]]:
        """Permutation importance — shuffle each feature, measure the performance drop."""
        if self._perm_cache is not None:
            return self._perm_cache

        perm_result = permutation_importance(
            self.model,
            self.X_test,
            self.y_test,
            n_repeats=n_repeats,
            random_state=random_state,
            scoring='f1_macro',
        )

        importances = perm_result.importances_mean
        stds = perm_result.importances_std

        # Rank: 1 = most important (not the index order)
        rank_order = np.argsort(-importances)
        rankings = np.empty_like(rank_order)
        rankings[rank_order] = np.arange(1, len(rank_order) + 1)

        result = {}
        for idx, name in enumerate(self.feature_names):
            result[name] = {
                "importance": round(float(importances[idx]), 4),
                "std": round(float(stds[idx]), 4),
                "ranking": int(rankings[idx]),
            }

        self._perm_cache = result
        return result

    def domain_feature_dominance(self) -> Dict[str, Any]:
        """If domain features account for >40% of importance, we have a leakage problem."""
        perm_imp = self.permutation_importance_scores()

        domain_imp = sum(
            max(v['importance'], 0) for k, v in perm_imp.items() if k in DOMAIN_FEATURES
        )
        local_imp = sum(
            max(v['importance'], 0) for k, v in perm_imp.items() if k not in DOMAIN_FEATURES
        )
        total_imp = domain_imp + local_imp

        domain_ratio = domain_imp / total_imp if total_imp > 0 else 0

        if domain_ratio > 0.6:
            assessment = (
                f"HIGH LEAKAGE RISK ({domain_ratio*100:.1f}% domain-driven). "
                "Model likely memorizing known disposable domains rather than learning "
                "genuine local-part patterns. Ablation study critical."
            )
        elif domain_ratio > 0.4:
            assessment = (
                f"MODERATE LEAKAGE RISK ({domain_ratio*100:.1f}% domain-driven). "
                "Domain features prominent; local-part ablation recommended."
            )
        else:
            assessment = (
                f"LOW LEAKAGE RISK ({domain_ratio*100:.1f}% domain-driven). "
                "Good balance between domain and local-part features. "
                "Model appears to learn genuine lexical patterns."
            )

        return {
            "domain_features": {
                k: v for k, v in perm_imp.items() if k in DOMAIN_FEATURES
            },
            "local_features": {
                k: v for k, v in perm_imp.items() if k not in DOMAIN_FEATURES
            },
            "domain_importance_ratio": round(domain_ratio, 4),
            "domain_importance_pct": round(domain_ratio * 100, 2),
            "local_importance_pct": round((1 - domain_ratio) * 100, 2),
            "leakage_risk_assessment": assessment,
        }

    def feature_interaction_analysis(self) -> Dict[str, Any]:
        """Pairwise correlations between top-5 features. Quick proxy for interaction effects."""
        perm_imp = self.permutation_importance_scores()
        individual_imp = {k: v['importance'] for k, v in perm_imp.items()}

        # Only look at the top 5 — full pairwise would be N²
        top_features_idx = sorted(
            range(len(self.feature_names)),
            key=lambda i: individual_imp[self.feature_names[i]],
            reverse=True
        )[:5]

        interactions = []

        for i in range(len(top_features_idx)):
            for j in range(i + 1, len(top_features_idx)):
                idx_i = top_features_idx[i]
                idx_j = top_features_idx[j]

                col_i = self.X_test[:, idx_i]
                col_j = self.X_test[:, idx_j]

                # Constant columns can't correlate with anything
                if np.std(col_i) == 0 or np.std(col_j) == 0:
                    continue

                correlation = np.corrcoef(col_i, col_j)[0, 1]

                if abs(correlation) > 0.3:
                    interactions.append({
                        "feature1": self.feature_names[idx_i],
                        "feature2": self.feature_names[idx_j],
                        "correlation": round(float(correlation), 4),
                        "strength": (
                            "STRONG" if abs(correlation) > 0.7
                            else "MODERATE" if abs(correlation) > 0.5
                            else "WEAK"
                        ),
                    })

        interactions.sort(key=lambda x: abs(x['correlation']), reverse=True)

        return {
            "high_interacting_pairs": interactions[:10],
            "total_pairs_analyzed": len(top_features_idx) * (len(top_features_idx) - 1) // 2,
        }

    def combined_feature_summary(self) -> Dict[str, Any]:
        """Blended ranking: 60% permutation + 40% tree. Permutation gets more weight because it's unbiased."""
        tree_imp = self.tree_importance()
        perm_imp = self.permutation_importance_scores()
        perm_imp_vals = {k: v['importance'] for k, v in perm_imp.items()}

        # Normalize both to [0, 1]
        tree_vals = np.array([tree_imp[f] for f in self.feature_names])
        perm_vals = np.array([perm_imp_vals[f] for f in self.feature_names])

        tree_range = tree_vals.max() - tree_vals.min()
        perm_range = perm_vals.max() - perm_vals.min()

        tree_norm = (tree_vals - tree_vals.min()) / (tree_range + 1e-8)
        perm_norm = (perm_vals - perm_vals.min()) / (perm_range + 1e-8)

        # Weighted blend
        combined = 0.6 * perm_norm + 0.4 * tree_norm

        # Proper rankings from the combined score
        rank_order = np.argsort(-combined)
        rankings = np.empty_like(rank_order)
        rankings[rank_order] = np.arange(1, len(rank_order) + 1)

        features_contrib = []
        for idx, feature in enumerate(self.feature_names):
            features_contrib.append({
                "feature": feature,
                "tree_importance": round(float(tree_imp[feature]), 4),
                "permutation_importance": round(float(perm_imp_vals[feature]), 4),
                "combined_score": round(float(combined[idx]), 4),
                "ranking": int(rankings[idx]),
                "is_domain_feature": feature in DOMAIN_FEATURES,
            })

        features_contrib.sort(key=lambda x: x['combined_score'], reverse=True)

        return {
            "feature_contributions": features_contrib,
            "method": "0.6×permutation + 0.4×tree (SHAP fallback)",
            "note": "Permutation importance weighted higher as it is model-agnostic and unbiased",
        }


class FeatureAblationStudy:
    """Zero out each feature one at a time and see what breaks."""

    def __init__(
        self,
        model: RandomForestClassifier,
        feature_names: List[str],
        X_test: np.ndarray,
        y_test: np.ndarray,
    ):
        self.model = model
        self.feature_names = feature_names
        self.X_test = X_test
        self.y_test = y_test

        # Baseline F1 with all features intact
        self.baseline_f1 = f1_score(
            y_test, model.predict(X_test), average='macro', zero_division=0
        )

    def ablate_feature(self, feature_idx: int) -> Dict[str, Any]:
        """Zero out one feature and measure F1 drop."""
        X_ablated = self.X_test.copy()
        X_ablated[:, feature_idx] = 0

        ablated_f1 = f1_score(
            self.y_test, self.model.predict(X_ablated),
            average='macro', zero_division=0
        )

        drop = self.baseline_f1 - ablated_f1
        drop_pct = (drop / self.baseline_f1 * 100) if self.baseline_f1 > 0 else 0

        if drop_pct > 10:
            assessment = "HIGH impact — feature is critical"
        elif drop_pct > 3:
            assessment = "MODERATE impact — feature contributes notably"
        elif drop_pct > 0.5:
            assessment = "LOW impact — minor contribution"
        else:
            assessment = "NEGLIGIBLE impact — feature rarely used"

        return {
            "feature": self.feature_names[feature_idx],
            "baseline_f1": round(self.baseline_f1, 4),
            "ablated_f1": round(float(ablated_f1), 4),
            "f1_drop": round(float(drop), 4),
            "f1_drop_pct": round(float(drop_pct), 2),
            "impact_assessment": assessment,
            "is_domain_feature": self.feature_names[feature_idx] in DOMAIN_FEATURES,
        }

    def ablate_all_features(self) -> Dict[str, Any]:
        """Run ablation on every feature and rank by impact."""
        results = []
        for idx in range(len(self.feature_names)):
            results.append(self.ablate_feature(idx))

        results.sort(key=lambda x: x['f1_drop_pct'], reverse=True)

        # Compare aggregate impact: domain features vs. local-part features
        domain_drops = [
            r['f1_drop_pct'] for r in results if r['is_domain_feature']
        ]
        local_drops = [
            r['f1_drop_pct'] for r in results if not r['is_domain_feature']
        ]

        return {
            "ablation_results": results,
            "baseline_f1": round(self.baseline_f1, 4),
            "summary": {
                "avg_domain_feature_drop_pct": round(
                    float(np.mean(domain_drops)) if domain_drops else 0, 2
                ),
                "avg_local_feature_drop_pct": round(
                    float(np.mean(local_drops)) if local_drops else 0, 2
                ),
                "most_critical_feature": results[0]["feature"] if results else None,
            },
        }
