"""XGBoost forecaster — implements BaseForecaster for experiment scripts.

Tier 1: trains under all Docker services running (~7 GB available).
"""
from __future__ import annotations

import json

import mlflow
import mlflow.xgboost
import numpy as np
import xgboost as xgb

_DEFAULT_PARAMS: dict = {
    "objective": "reg:squarederror",
    "eval_metric": "mae",
    "max_depth": 7,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 20,
    "random_state": 42,
    "verbosity": 0,
}


class XGBForecaster:
    def __init__(self, params: dict | None = None, num_boost_round: int = 1000) -> None:
        self.params = params or _DEFAULT_PARAMS.copy()
        self.num_boost_round = num_boost_round
        self._model: xgb.Booster | None = None

    @property
    def model_type(self) -> str:
        return "xgboost"

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> None:
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dval = xgb.DMatrix(X_val, label=y_val)
        self._model = xgb.train(
            params=self.params,
            dtrain=dtrain,
            num_boost_round=self.num_boost_round,
            evals=[(dval, "val")],
            early_stopping_rounds=50,
            verbose_eval=100,
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Call fit() before predict().")
        return self._model.predict(xgb.DMatrix(X))

    def log_model(self, artifact_path: str = "model", input_example: np.ndarray | None = None) -> None:
        if self._model is None:
            raise RuntimeError("Call fit() before log_model().")
        mlflow.log_param("model_type", self.model_type)
        mlflow.log_param("hyperparams", json.dumps(self.params))
        mlflow.xgboost.log_model(
            self._model,
            artifact_path=artifact_path,
            input_example=input_example,
        )
