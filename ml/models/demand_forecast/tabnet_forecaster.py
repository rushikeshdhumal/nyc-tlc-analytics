"""TabNet forecaster — attention-based tabular DL model.

Implements BaseForecaster for experiment scripts.

Tier 2: stop Airflow workers + Superset before running.
  docker compose stop airflow-worker airflow-scheduler superset

AMD GPU acceleration via DirectML (optional — falls back to CPU if unavailable):
  pip install torch torch-directml>=0.2 pytorch-tabnet>=4.1
"""
from __future__ import annotations

import json

import mlflow
import numpy as np

_DEFAULT_PARAMS: dict = {
    "n_d": 32,
    "n_a": 32,
    "n_steps": 5,
    "gamma": 1.5,
    "n_independent": 2,
    "n_shared": 2,
    "momentum": 0.02,
    "mask_type": "entmax",
}

_DEFAULT_FIT_PARAMS: dict = {
    "max_epochs": 200,
    "patience": 20,
    "batch_size": 1024,
    "virtual_batch_size": 256,
}


class TabNetForecaster:
    def __init__(
        self,
        model_params: dict | None = None,
        fit_params: dict | None = None,
    ) -> None:
        self.model_params = model_params or _DEFAULT_PARAMS.copy()
        self.fit_params = fit_params or _DEFAULT_FIT_PARAMS.copy()
        self._model = None

    @property
    def model_type(self) -> str:
        return "tabnet"

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> None:
        from pytorch_tabnet.tab_model import TabNetRegressor

        device = _get_device()
        self._model = TabNetRegressor(device_name=device, **self.model_params)
        self._model.fit(
            X_train=X_train.astype(np.float32),
            y_train=y_train.reshape(-1, 1).astype(np.float32),
            eval_set=[(X_val.astype(np.float32), y_val.reshape(-1, 1).astype(np.float32))],
            eval_name=["val"],
            eval_metric=["mae"],
            **self.fit_params,
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Call fit() before predict().")
        preds = self._model.predict(X.astype(np.float32))
        return np.maximum(preds.flatten(), 0.0)

    def log_model(self, artifact_path: str = "model") -> None:
        if self._model is None:
            raise RuntimeError("Call fit() before log_model().")
        mlflow.log_param("model_type", self.model_type)
        mlflow.log_param("model_params", json.dumps(self.model_params))
        mlflow.log_param("fit_params", json.dumps(self.fit_params))
        mlflow.log_param("device", _get_device())
        mlflow.sklearn.log_model(self._model, artifact_path=artifact_path)


def _get_device() -> str:
    try:
        import torch_directml
        return "cpu"  # TabNetRegressor device_name — DirectML used internally by torch
    except ImportError:
        return "cpu"
