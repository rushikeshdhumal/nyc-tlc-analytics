"""Stage 2 — Baseline comparison for demand forecasting.

Runs three baselines against the same holdout set and logs each as a separate
MLflow run tagged stage=baseline.

Baselines:
  1. Naive lag-168 (last week same hour) — primary benchmark from ADR-005
  2. Seasonal naive (same hour, averaged over last 4 weeks)
  3. Ridge regression on the canonical FEATURE_COLS

Usage:
  python -m ml.experiments.demand_forecast.baseline_comparison --run-date 2026-04-05
  python -m ml.experiments.demand_forecast.baseline_comparison --run-date 2026-04-05 --features-cache data/features.parquet
"""
from __future__ import annotations

import argparse

import mlflow
import numpy as np
import pandas as pd

from ml.features.demand_features import FEATURE_COLS, TARGET_COL, build_feature_matrix
from ml.models.demand_forecast.ridge_forecaster import RidgeForecaster
from ml.models.demand_forecast.train import _compute_splits
from ml.utils.mlflow_utils import get_or_create_experiment, setup_tracking

EXPERIMENT_NAME = "demand_forecast_hourly"


def run_baselines(run_date: str, cache_path: str | None = None) -> None:
    setup_tracking()
    experiment_id = get_or_create_experiment(EXPERIMENT_NAME)
    splits = _compute_splits(run_date)

    if cache_path and os.path.exists(cache_path):
        df = pd.read_parquet(cache_path)
    else:
        df = build_feature_matrix(splits["train_start"], splits["test_end"])
        df = df.dropna(subset=FEATURE_COLS)
        if cache_path:
            df.to_parquet(cache_path, index=False)

    train_df = df[df["pickup_hour"] <= pd.Timestamp(splits["train_end"])]
    val_df = df[
        (df["pickup_hour"] >= pd.Timestamp(splits["val_start"]))
        & (df["pickup_hour"] <= pd.Timestamp(splits["val_end"]))
    ]
    test_df = df[df["pickup_hour"] >= pd.Timestamp(splits["test_start"])]

    y_test = test_df[TARGET_COL].values

    _run_lag168(experiment_id, run_date, splits, test_df, y_test)
    _run_seasonal_naive(experiment_id, run_date, splits, test_df, y_test)
    _run_ridge(experiment_id, run_date, splits, train_df, val_df, test_df, y_test)


def _run_lag168(
    experiment_id: str,
    run_date: str,
    splits: dict,
    test_df: pd.DataFrame,
    y_test: np.ndarray,
) -> None:
    preds = test_df["lag_168h_trip_count"].values
    valid = ~np.isnan(preds)
    mape = _mape(y_test[valid], preds[valid])

    with mlflow.start_run(experiment_id=experiment_id):
        mlflow.set_tag("stage", "baseline")
        mlflow.set_tag("mlflow.runName", f"baseline_lag168__{splits['test_start']}")
        mlflow.log_param("model_type", "naive_lag168")
        mlflow.log_param("run_date", run_date)
        _log_splits(splits)
        mlflow.log_metric("test_mape", mape)
        print(f"[lag-168] test_mape={mape:.2f}%")


def _run_seasonal_naive(
    experiment_id: str,
    run_date: str,
    splits: dict,
    test_df: pd.DataFrame,
    y_test: np.ndarray,
) -> None:
    lag_cols = [c for c in test_df.columns if "lag_" in c and "trip_count" in c]
    if len(lag_cols) < 2:
        print("[seasonal_naive] not enough lag columns — skipping")
        return

    preds = test_df[lag_cols].mean(axis=1).values
    valid = ~np.isnan(preds)
    mape = _mape(y_test[valid], preds[valid])

    with mlflow.start_run(experiment_id=experiment_id):
        mlflow.set_tag("stage", "baseline")
        mlflow.set_tag("mlflow.runName", f"baseline_seasonal_naive__{splits['test_start']}")
        mlflow.log_param("model_type", "seasonal_naive")
        mlflow.log_param("run_date", run_date)
        mlflow.log_param("lag_cols_used", ",".join(lag_cols))
        _log_splits(splits)
        mlflow.log_metric("test_mape", mape)
        print(f"[seasonal_naive] test_mape={mape:.2f}%")


def _run_ridge(
    experiment_id: str,
    run_date: str,
    splits: dict,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    y_test: np.ndarray,
) -> None:
    model = RidgeForecaster(alpha=1.0)
    model.fit(
        train_df[FEATURE_COLS].values,
        train_df[TARGET_COL].values,
        val_df[FEATURE_COLS].values,
        val_df[TARGET_COL].values,
    )
    preds = model.predict(test_df[FEATURE_COLS].values)
    mape = _mape(y_test, preds)

    with mlflow.start_run(experiment_id=experiment_id):
        mlflow.set_tag("stage", "baseline")
        mlflow.set_tag("mlflow.runName", f"baseline_ridge__{splits['test_start']}")
        _log_splits(splits)
        mlflow.log_param("run_date", run_date)
        mlflow.log_param("model_type", model.model_type)
        mlflow.log_param("alpha", model.alpha)
        mlflow.log_metric("test_mape", mape)
        print(f"[ridge] test_mape={mape:.2f}%")


def _log_splits(splits: dict) -> None:
    for k, v in splits.items():
        mlflow.log_param(k, v)


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--features-cache", metavar="PATH", default=None)
    args = parser.parse_args()
    run_baselines(args.run_date, cache_path=args.features_cache)
