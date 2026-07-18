import os
import joblib
import numpy as np
from app.services.feature_extractor import FeatureExtractor

class MLModelService:
    def __init__(self, model_path: str = "models/rf_model.joblib"):
        self.model_path = model_path
        self.model = None
        self.metadata = {}
        self.feature_extractor = FeatureExtractor()
        self._load_production_artifact()

    def _load_production_artifact(self):
        # Can't do anything without the serialised model
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Production model payload missing at {self.model_path}")
            
        try:
            payload = joblib.load(self.model_path)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load model artifact at {self.model_path}: {e}. "
                "Check for unpicklable custom classes or sklearn version mismatch."
            ) from e
        
        if isinstance(payload, dict) and "model" in payload:
            self.model = payload["model"]
            self.metadata = payload.get("metadata", {})
            print(f"✓ Calibrated RF Model Loaded successfully. Accuracy: {self.metadata.get('test_accuracy')}")
        else:
            # Legacy format — no metadata wrapper. Probably fine, but who knows.
            self.model = payload
            print("⚠ Warning: Raw classifier loaded without explicit validation metadata.")

    def predict_email_risk(self, email: str) -> float:
        features = np.array([self.feature_extractor.extract_as_vector(email)], dtype=np.float32)
        
        # predict_proba → [P(disposable), P(legitimate)]
        probabilities = self.model.predict_proba(features)[0]
        return float(probabilities[0])  # risk = P(disposable)
