"""Ensemble forecaster — weighted blend, rank average, and OOF stacking.

Implements BaseForecaster for experiment_comparison scripts.
Strategy is selected at construction time.

Tier 2 for stacking (OOF meta-learner training requires more memory).
Weighted blend and rank average are Tier 1.
"""
from __future__ import annotations

import json
from typing import Literal

import mlflow
import numpy as np

EnsembleStrategy = Literal["weighted_blend", "rank_average", "stacking"]


class EnsembleForecaster:
    """Wraps a list of BaseForecaster instances into a combined prediction.

    Args:
        forecasters: Ordered list of fitted forecasters.
        strategy: "weighted_blend" | "rank_average" | "stacking"
        weights: Per-forecaster weights for weighted_blend (defaults to equal).
        meta_model: sklearn regressor for stacking meta-learner (required when
                    strategy="stacking"; trained on OOF predictions passed to fit).
    """

    def __init__(
        self,
        forecasters: list,
        strategy: EnsembleStrategy = "weighted_blend",
        weights: list[float] | None = None,
        meta_model=None,
    ) -> None:
        self.forecasters = forecasters
        self.strategy = strategy
        self.weights = weights or [1.0 / len(forecasters)] * len(forecasters)
        self.meta_model = meta_model
        self._fitted = False

    @property
    def model_type(self) -> str:
        names = "+".join(f.model_type for f in self.forecasters)
        return f"ensemble_{self.strategy}[{names}]"

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> None:
        """Fit all base forecasters.

        For stacking: pass OOF predictions as X_train to the meta_model separately
        via fit_meta(). This method only trains the base models.
        """
        for forecaster in self.forecasters:
            forecaster.fit(X_train, y_train, X_val, y_val)
        self._fitted = True

    def fit_meta(self, X_oof: np.ndarray, y_oof: np.ndarray) -> None:
        """Train the stacking meta-learner on out-of-fold predictions.

        X_oof shape: (n_samples, n_forecasters) — one column per base model's OOF preds.
        Call this after generating OOF predictions via walk-forward CV.
        Never train the meta-learner on the same fold used to train base models.
        """
        if self.strategy != "stacking":
            raise RuntimeError("fit_meta() is only applicable when strategy='stacking'.")
        if self.meta_model is None:
            raise RuntimeError("Provide a meta_model (sklearn regressor) for stacking.")
        self.meta_model.fit(X_oof, y_oof)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")

        base_preds = np.column_stack([f.predict(X) for f in self.forecasters])

        if self.strategy == "weighted_blend":
            weights = np.array(self.weights)
            return base_preds @ weights

        if self.strategy == "rank_average":
            ranks = np.argsort(np.argsort(base_preds, axis=0), axis=0).astype(float)
            return ranks.mean(axis=1)

        if self.strategy == "stacking":
            if self.meta_model is None:
                raise RuntimeError("Meta model not trained. Call fit_meta() first.")
            return np.maximum(self.meta_model.predict(base_preds), 0.0)

        raise ValueError(f"Unknown strategy: {self.strategy}")

    def log_model(self, artifact_path: str = "model", input_example: np.ndarray | None = None) -> None:
        mlflow.log_param("model_type", self.model_type)
        mlflow.log_param("strategy", self.strategy)
        mlflow.log_param("weights", json.dumps(self.weights))
        mlflow.log_param(
            "base_models",
            json.dumps([f.model_type for f in self.forecasters]),
        )
        if self.strategy == "stacking" and self.meta_model is not None:
            mlflow.log_param("meta_model", type(self.meta_model).__name__)
