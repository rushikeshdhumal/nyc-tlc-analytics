"""BaseForecaster Protocol — model-agnostic interface for all demand forecast models.

All model implementations (lgbm_forecaster, xgb_forecaster, etc.) must conform
to this protocol so that experiment scripts can swap models without framework-
specific branching.

Production train.py instantiates model classes directly — this protocol is used
only by experiment comparison scripts.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class BaseForecaster(Protocol):
    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> None: ...

    def predict(self, X: np.ndarray) -> np.ndarray: ...

    def log_model(self, artifact_path: str) -> None:
        """Log the trained model to the active MLflow run."""
        ...

    @property
    def model_type(self) -> str:
        """Short identifier logged as mlflow param 'model_type'."""
        ...
