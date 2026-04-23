"""Ridge regression forecaster — interpretable linear baseline.

Implements BaseForecaster for experiment scripts.
Tier 1: very fast, minimal memory.
"""
from __future__ import annotations

import mlflow
import mlflow.sklearn
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


class RidgeForecaster:
    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha
        self._scaler = StandardScaler()
        self._model = Ridge(alpha=alpha)

    @property
    def model_type(self) -> str:
        return "ridge"

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> None:
        X_scaled = self._scaler.fit_transform(X_train)
        self._model.fit(X_scaled, y_train)

    def predict(self, X: np.ndarray) -> np.ndarray:
        X_scaled = self._scaler.transform(X)
        return np.maximum(self._model.predict(X_scaled), 0.0)

    def log_model(self, artifact_path: str = "model", input_example: np.ndarray | None = None) -> None:
        mlflow.log_param("model_type", self.model_type)
        mlflow.log_param("alpha", self.alpha)
        mlflow.sklearn.log_model(
            self._model,
            artifact_path=artifact_path,
            input_example=input_example,
        )
