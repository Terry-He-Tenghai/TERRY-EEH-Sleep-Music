from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd


class InferenceEngine:
    """Load versioned sklearn bundles and perform one-window inference."""

    def __init__(
        self,
        prediction_model_path: str | Path,
        state_model_path: str | Path,
    ) -> None:
        prediction_bundle = self._load_bundle(prediction_model_path)
        state_bundle = self._load_bundle(state_model_path)
        self.prediction_model = prediction_bundle["model"]
        self.prediction_features = tuple(prediction_bundle["features"])
        self.state_model = state_bundle["model"]
        self.state_features = tuple(state_bundle["features"])
        self.state_classes = tuple(state_bundle["classes"])
        self.state_aggregation_seconds = float(
            state_bundle.get("aggregation_seconds", 0.0)
        )

    @staticmethod
    def _load_bundle(path: str | Path) -> dict[str, Any]:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model bundle not found: {path}")
        bundle = joblib.load(path)
        if not isinstance(bundle, dict) or "model" not in bundle or "features" not in bundle:
            raise ValueError(f"Invalid model bundle: {path}")
        return bundle

    @property
    def required_features(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.prediction_features + self.state_features))

    def predict(
        self,
        features: Mapping[str, float],
        state_features: Mapping[str, float] | None = None,
    ) -> tuple[float, dict[str, float]]:
        state_features = state_features or features
        n2_probability = self.predict_future_n2(features)
        state_probabilities = self.predict_state(state_features)
        return n2_probability, state_probabilities

    def predict_future_n2(self, features: Mapping[str, float]) -> float:
        missing = [
            name for name in self.prediction_features if name not in features
        ]
        if missing:
            raise ValueError(f"Missing inference features: {missing}")
        if not all(
            np.isfinite(float(features[name]))
            for name in self.prediction_features
        ):
            raise ValueError("Inference features contain non-finite values")
        prediction_matrix = pd.DataFrame(
            [[features[name] for name in self.prediction_features]],
            columns=self.prediction_features,
        )
        return float(
            self.prediction_model.predict_proba(prediction_matrix)[0, 1]
        )

    def predict_state(
        self,
        features: Mapping[str, float],
    ) -> dict[str, float]:
        missing = [name for name in self.state_features if name not in features]
        if missing:
            raise ValueError(f"Missing state features: {missing}")
        if not all(
            np.isfinite(float(features[name])) for name in self.state_features
        ):
            raise ValueError("State features contain non-finite values")
        state_matrix = pd.DataFrame(
            [[features[name] for name in self.state_features]],
            columns=self.state_features,
        )
        state_values = self.state_model.predict_proba(state_matrix)[0]
        return {
            stage: float(probability)
            for stage, probability in zip(
                self.state_classes,
                state_values,
                strict=True,
            )
        }
