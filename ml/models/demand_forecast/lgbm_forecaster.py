"""LightGBM forecaster — implements BaseForecaster for experiment scripts.

Tier 1: trains under all Docker services running (~7 GB available).
"""
from __future__ import annotations

import json

import lightgbm as lgb
import mlflow
import mlflow.lightgbm
import numpy as np

_DEFAULT_PARAMS: dict = {
    "objective": "regression",
    "metric": "mae",
    "num_leaves": 127,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_child_samples": 20,
    "random_state": 42,
    "verbose": -1,
}


class LGBMForecaster:
    def __init__(
        self,
        params: dict | None = None,
        num_boost_round: int = 1000,
        log1p_target: bool = True,
    ) -> None:
        self.params = params or _DEFAULT_PARAMS.copy()
        self.num_boost_round = num_boost_round
        self.log1p_target = log1p_target
        self._model: lgb.Booster | None = None

    @property
    def model_type(self) -> str:
        return "lightgbm"

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> None:
        y_tr = np.log1p(y_train) if self.log1p_target else y_train
        y_v  = np.log1p(y_val)   if self.log1p_target else y_val
        dtrain = lgb.Dataset(X_train, label=y_tr)
        dval   = lgb.Dataset(X_val,   label=y_v, reference=dtrain)
        callbacks = [
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=100),
        ]
        self._model = lgb.train(
            params=self.params,
            train_set=dtrain,
            num_boost_round=self.num_boost_round,
            valid_sets=[dval],
            callbacks=callbacks,
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Call fit() before predict().")
        raw = self._model.predict(X)
        return np.maximum(np.expm1(raw), 0.0) if self.log1p_target else raw

    def log_model(self, artifact_path: str = "model", input_example: np.ndarray | None = None) -> None:
        if self._model is None:
            raise RuntimeError("Call fit() before log_model().")
        mlflow.log_param("model_type", self.model_type)
        mlflow.log_param("log1p_target", self.log1p_target)
        mlflow.log_param("hyperparams", json.dumps(self.params))
        mlflow.lightgbm.log_model(
            self._model,
            artifact_path=artifact_path,
            input_example=input_example,
        )
