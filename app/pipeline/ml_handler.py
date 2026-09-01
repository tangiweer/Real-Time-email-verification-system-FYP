


from __future__ import annotations
import logging
import os
import time
from typing import Optional, TYPE_CHECKING

import joblib

from app.models import PipelineContext, VerificationStatus, FailedLayer
from app.pipeline.base_handler import BaseEmailHandler
from app.services.feature_extractor import FeatureExtractor
from app.services.feature_extractor import FEATURE_ORDER
from app.services.heuristic_engine import HeuristicEngine

if TYPE_CHECKING:
    from app.services.disposable_cache import DisposableDomainsCache

logger = logging.getLogger(__name__)

# Path to the trained Random Forest model produced by the training notebook
_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models")
_MODEL_PATH = os.path.join(_MODEL_DIR, "rf_model.joblib")

# Decision thresholds — tuned against the dissertation evaluation set
_INVALID_THRESHOLD = 0.80     # score >= this → hard reject
_SUSPICIOUS_THRESHOLD = 0.50  # score >= this → soft flag


class MLHandler(BaseEmailHandler):
    """
    Chain-of-Responsibility handler that runs a Random Forest classifier
    over 18 lexical features and then applies the Domain-Aware Heuristic
    Engine to reduce false positives for culturally diverse names.
    """

    def __init__(
        self,
        disposable_cache: Optional["DisposableDomainsCache"] = None,
    ) -> None:
        super().__init__()
        self._extractor = FeatureExtractor()
        self._heuristic = HeuristicEngine(disposable_cache=disposable_cache)
        self._model = None  # lazy-loaded on first call or via warmup()
        self._metadata: dict = {}
        self._risk_class: int | None = None

    # --- Public interface ---

    async def handle(self, context: PipelineContext) -> PipelineContext:
        start_time = time.perf_counter()

        # Load the model on the first invocation if warmup() wasn't called
        self._ensure_model_loaded()

        email = context.email

        # Extract features and run the RF model
        feature_vector = self._extractor.extract_as_vector(email)

        if self._model is not None:
            # New Colab artifacts declare 1=disposable/high-risk. The bundled
            # legacy artifact predates that metadata and uses class 0 as risk.
            # Resolve the class position rather than assuming array ordering.
            proba = self._model.predict_proba([feature_vector])[0]
            classes = list(getattr(self._model, "classes_", [0, 1]))
            risk_class = self._risk_class
            if risk_class not in classes:
                raise RuntimeError(
                    f"ML model does not contain its configured risk class ({risk_class})."
                )
            raw_score = float(proba[classes.index(risk_class)])
        else:
            # No model available — fall back to a neutral score
            raw_score = 0.0
            context.reasons.append(
                "ML model not available; skipping lexical classification."
            )

        # Post-process through the heuristic engine (domain reputation,
        # disposable cache, name-pattern discounts)
        adjusted_score, heuristic_notes = self._heuristic.adjust_score(
            email, raw_score
        )
        context.ml_score = adjusted_score
        context.reasons.extend(heuristic_notes)

        # Flag disposable domains on the context for downstream consumers
        if any("disposable" in note.lower() for note in heuristic_notes):
            context.is_disposable = True

        # Apply thresholds
        if adjusted_score >= _INVALID_THRESHOLD:
            context.status = VerificationStatus.INVALID
            context.confidence = round(adjusted_score, 2)
            context.failed_layer = FailedLayer.ML
            context.suggestion = (
                "This email address appears to be auto-generated or from a "
                "disposable provider.  Please use a permanent personal or "
                "work email address."
            )
            context.stop_processing = True
        elif adjusted_score >= _SUSPICIOUS_THRESHOLD:
            context.status = VerificationStatus.SUSPICIOUS
            context.confidence = round(1.0 - adjusted_score, 2)
            context.failed_layer = FailedLayer.ML
            context.suggestion = (
                "This email address has characteristics common to temporary "
                "or bot-generated addresses.  Consider verifying with the "
                "recipient directly."
            )
            # Don't stop — let SMTP still attempt delivery confirmation
        # else: score is low, email looks fine — leave status as-is

        context.execution_times[self.layer_name] = round(
            (time.perf_counter() - start_time) * 1000, 1
        )

        if context.stop_processing:
            return context
        return await super().handle(context)

    def warmup(self) -> None:
        """Pre-load the model at startup so the first request isn't slow."""
        self._ensure_model_loaded()
        super().warmup()

    # --- Private helpers ---

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return
        model_path = os.path.abspath(_MODEL_PATH)
        if os.path.isfile(model_path):
            try:
                artifact = joblib.load(model_path)
                if isinstance(artifact, dict):
                    self._model = artifact.get("model")
                    self._metadata = artifact.get("metadata", {})
                else:
                    # Support legacy artifacts that serialized the classifier directly.
                    self._model = artifact
                    self._metadata = {}
                if self._model is None or not hasattr(self._model, "predict_proba"):
                    raise ValueError("Artifact does not contain a classifier with predict_proba().")
                self._validate_model_contract()
                logger.info(
                    "[MLHandler] Loaded %s model from %s",
                    self._metadata.get("model_name", "classifier"), model_path,
                )
            except Exception as exc:
                self._model = None
                self._metadata = {}
                self._risk_class = None
                logger.warning(
                    "[MLHandler] Refusing incompatible model artifact (%s).",
                    exc,
                )
                raise RuntimeError("Email-risk model failed its deployment contract.") from exc
        else:
            logger.warning(
                "[MLHandler] Model file not found at %s. "
                "ML scoring will be disabled.",
                model_path,
            )

    def _validate_model_contract(self) -> None:
        """Fail closed when a replacement artifact is incompatible with inference."""
        expected_features = FEATURE_ORDER
        artifact_features = self._metadata.get("feature_order")
        if artifact_features != expected_features:
            raise ValueError("Model feature_order does not exactly match the production extractor.")
        if getattr(self._model, "n_features_in_", len(expected_features)) != len(expected_features):
            raise ValueError("Model feature count does not match the production extractor.")

        label_definition = self._metadata.get("label_definition")
        if label_definition != "0=legitimate, 1=disposable/high-risk":
            raise ValueError("Model label_definition is missing or incompatible.")

        # The submitted final artifact omitted positive_class but explicitly
        # declares this label mapping.  Use that mapping, never the old class-0
        # legacy fallback that inverted its predictions.
        risk_class = self._metadata.get("positive_class", 1)
        if risk_class != 1:
            raise ValueError("Model positive_class must be 1 (disposable/high-risk).")
        self._risk_class = risk_class
