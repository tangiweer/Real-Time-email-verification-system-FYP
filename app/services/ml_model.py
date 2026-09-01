"""Shared loader for deployment and offline evaluation model artifacts."""

from __future__ import annotations

import os
from typing import Any

import joblib


class MLModelService:
    """Load the project's versioned ``{model, metadata}`` joblib artifact."""

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "models", "rf_model.joblib")
        )
        self.model: Any = None
        self.metadata: dict = {}
        self._load_production_artifact()

    def _load_production_artifact(self) -> None:
        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(f"Production model artifact missing: {self.model_path}")

        artifact = joblib.load(self.model_path)
        if isinstance(artifact, dict):
            self.model = artifact.get("model")
            self.metadata = artifact.get("metadata", {})
        else:
            self.model = artifact  # legacy direct-classifier artifact

        if self.model is None or not hasattr(self.model, "predict_proba"):
            raise ValueError("Model artifact must contain a classifier with predict_proba().")
