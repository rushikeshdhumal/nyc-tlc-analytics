"""Stage 3 — Feature ablation for demand forecasting.

Systematically adds or removes features and logs each variant as an MLflow run
tagged stage=feature_ablation.

Ablation strategies:
  1. Full feature set (canonical FEATURE_COLS — the reference)
  2. No lag features (calendar only)
  3. No rolling features
  4. No congestion fee lag
  5. No borough encoding
  6. Add-one: each feature group added individually to a minimal base set

Usage:
  python -m ml.experiments.demand_forecast.feature_ablation --run-date 2026-04-05
  python -m ml.experiments.demand_forecast.feature_ablation --run-date 2026-04-05 --features-cache data/features.parquet
"""
from __future__ import annotations

import argparse

import mlflow
import numpy as np
import pandas as pd

from ml.features.demand_features import FEATURE_COLS, TARGET_COL, build_feature_matrix
from ml.models.demand_forecast.lgbm_forecaster import LGBMForecaster
from ml.models.demand_forecast.train import _compute_splits
from ml.utils.mlflow_utils import get_or_create_experiment, setup_tracking

EXPERIMENT_NAME = "demand_forecast_hourly"

_ABLATION_SETS: dict[str, list[str]] = {
    "full": FEATURE_COLS,
    "no_lag": [c for c in FEATURE_COLS if "lag_" not in c and "rolling_" not in c],
    "no_rolling": [c for c in FEATURE_COLS if "rolling_" not in c],
    "no_congestion": [c for c in FEATURE_COLS if "congestion" not in c],
    "no_borough_enc": [c for c in FEATURE_COLS if c != "pickup_borough_enc"],
    "calendar_only": ["hour_of_day", "day_of_week_num", "month", "is_weekend", "pu_location_id"],
}


def run_ablation(run_date: str, cache_path: str | None = None) -> None:
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

    for variant_name, feature_set in _ABLATION_SETS.items():
        missing = [c for c in feature_set if c not in df.columns]
        if missing:
            print(f"[ablation:{variant_name}] skipping — missing columns: {missing}")
            continue

        model = LGBMForecaster()
        model.fit(
            train_df[feature_set].values,
            train_df[TARGET_COL].values,
            val_df[feature_set].values,
            val_df[TARGET_COL].values,
        )
        preds = model.predict(test_df[feature_set].values)
        mape = _mape(y_test, preds)

        with mlflow.start_run(experiment_id=experiment_id):
            mlflow.set_tag("stage", "feature_ablation")
            mlflow.set_tag(
                "mlflow.runName",
                f"ablation_{variant_name}__{splits['test_start']}",
            )
            mlflow.log_param("run_date", run_date)
            mlflow.log_param("ablation_variant", variant_name)
            mlflow.log_param("n_features", len(feature_set))
            mlflow.log_param("features", ",".join(feature_set))
            for k, v in splits.items():
                mlflow.log_param(k, v)
            mlflow.log_metric("test_mape", mape)
            print(f"[ablation:{variant_name}] n={len(feature_set)} test_mape={mape:.2f}%")


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
    run_ablation(args.run_date, cache_path=args.features_cache)
