"""Stage 4 — Model candidate comparison for demand forecasting.

Runs all Tier 1 models (and optionally Tier 2) against the same holdout set
via the BaseForecaster interface. Each model is a separate MLflow run tagged
stage=model_selection.

Tier 1 models (run with all Docker services active, ~7 GB):
  LightGBM, XGBoost, Ridge

Tier 2 models (stop Airflow workers + Superset first, ~10 GB):
  TabNet, LSTM (compact, DirectML)

Usage:
  # Tier 1 only
  python -m ml.experiments.demand_forecast.model_comparison --run-date 2026-04-05

  # Include Tier 2 (ensure services are stopped first)
  python -m ml.experiments.demand_forecast.model_comparison --run-date 2026-04-05 --tier 2

  # With feature cache
  python -m ml.experiments.demand_forecast.model_comparison --run-date 2026-04-05 --features-cache data/features.parquet
"""
from __future__ import annotations

import argparse
import os

import mlflow
import numpy as np
import pandas as pd

from ml.features.demand_features import FEATURE_COLS, TARGET_COL, build_feature_matrix
from ml.models.demand_forecast.lgbm_forecaster import LGBMForecaster
from ml.models.demand_forecast.ridge_forecaster import RidgeForecaster
from ml.models.demand_forecast.train import _compute_splits
from ml.models.demand_forecast.xgb_forecaster import XGBForecaster
from ml.utils.mlflow_utils import get_or_create_experiment, setup_tracking

EXPERIMENT_NAME = "demand_forecast_hourly"


def _tier1_candidates() -> list:
    return [
        LGBMForecaster(),
        XGBForecaster(),
        RidgeForecaster(alpha=1.0),
    ]


def _tier2_candidates() -> list:
    from ml.models.demand_forecast.lstm_forecaster import LSTMForecaster
    from ml.models.demand_forecast.tabnet_forecaster import TabNetForecaster

    return [
        TabNetForecaster(),
        LSTMForecaster(hidden_size=64, num_layers=2, lookback=24),
    ]


def run_model_comparison(
    run_date: str,
    tier: int = 1,
    cache_path: str | None = None,
) -> None:
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

    candidates = _tier1_candidates()
    if tier >= 2:
        print(
            "Including Tier 2 models. Confirm Airflow workers + Superset are stopped:\n"
            "  docker compose stop airflow-worker airflow-scheduler superset"
        )
        candidates.extend(_tier2_candidates())

    for model in candidates:
        print(f"\nTraining [{model.model_type}]...")
        model.fit(
            train_df[FEATURE_COLS].values,
            train_df[TARGET_COL].values,
            val_df[FEATURE_COLS].values,
            val_df[TARGET_COL].values,
        )
        preds = model.predict(test_df[FEATURE_COLS].values)
        mape = _mape(y_test, preds)
        val_preds = model.predict(val_df[FEATURE_COLS].values)
        val_mape = _mape(val_df[TARGET_COL].values, val_preds)

        with mlflow.start_run(experiment_id=experiment_id):
            mlflow.set_tag("stage", "model_selection")
            mlflow.set_tag(
                "mlflow.runName",
                f"model_sel_{model.model_type}__{splits['test_start']}",
            )
            mlflow.log_param("run_date", run_date)
            for k, v in splits.items():
                mlflow.log_param(k, v)
            # Pass representative input sample for MLflow signature inference
            input_sample = train_df[FEATURE_COLS].values[:100]
            model.log_model(input_example=input_sample)
            mlflow.log_metric("val_mape", val_mape)
            mlflow.log_metric("test_mape", mape)
            print(f"  val_mape={val_mape:.2f}%  test_mape={mape:.2f}%")


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument(
        "--tier",
        type=int,
        default=1,
        choices=[1, 2],
        help="Memory tier: 1=all services, 2=stop Airflow+Superset first",
    )
    parser.add_argument("--features-cache", metavar="PATH", default=None)
    args = parser.parse_args()
    run_model_comparison(args.run_date, tier=args.tier, cache_path=args.features_cache)
