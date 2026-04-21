"""Stage 4b — Ensemble exploration for demand forecasting.

Compares ensemble strategies on the best Tier 1 base models identified in
Stage 4 (model_comparison.py). Each strategy is a separate MLflow run tagged
stage=ensemble_exploration.

Strategies evaluated:
  1. Weighted blend (equal weights)
  2. Rank average
  3. OOF stacking with Ridge meta-learner

Gain threshold: ensemble must beat the best individual model by > 0.5% MAPE
to justify the added complexity (ML_DEVELOPMENT_WORKFLOW.md §5 Stage 4b).

Tier 2: stop Airflow workers + Superset before running stacking.
  docker compose stop airflow-worker airflow-scheduler superset

Usage:
  python -m ml.experiments.demand_forecast.ensemble_comparison --run-date 2026-04-05
  python -m ml.experiments.demand_forecast.ensemble_comparison --run-date 2026-04-05 --features-cache data/features.parquet
"""
from __future__ import annotations

import argparse
import os

import mlflow
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from ml.features.demand_features import FEATURE_COLS, TARGET_COL, build_feature_matrix
from ml.models.demand_forecast.ensemble_forecaster import EnsembleForecaster
from ml.models.demand_forecast.lgbm_forecaster import LGBMForecaster
from ml.models.demand_forecast.train import _compute_splits
from ml.models.demand_forecast.xgb_forecaster import XGBForecaster
from ml.utils.evaluation import walk_forward_cv
from ml.utils.mlflow_utils import get_or_create_experiment

EXPERIMENT_NAME = "demand_forecast_hourly"
GAIN_THRESHOLD_PCT = 0.5


def run_ensemble_comparison(run_date: str, cache_path: str | None = None) -> None:
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns"))
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

    X_train = train_df[FEATURE_COLS].values
    y_train = train_df[TARGET_COL].values
    X_val = val_df[FEATURE_COLS].values
    y_val = val_df[TARGET_COL].values
    X_test = test_df[FEATURE_COLS].values

    best_individual_mape = _get_best_individual_mape(
        X_train, y_train, X_val, y_val, X_test, y_test
    )
    print(f"Best individual model test_mape: {best_individual_mape:.2f}%")

    strategies = [
        ("weighted_blend", _build_ensemble("weighted_blend")),
        ("rank_average", _build_ensemble("rank_average")),
        ("stacking", _build_stacking_ensemble(df, FEATURE_COLS, TARGET_COL, run_date)),
    ]

    for strategy_name, ensemble in strategies:
        ensemble.fit(X_train, y_train, X_val, y_val)
        preds = ensemble.predict(X_test)
        mape = _mape(y_test, preds)
        gain = best_individual_mape - mape

        with mlflow.start_run(experiment_id=experiment_id):
            mlflow.set_tag("stage", "ensemble_exploration")
            mlflow.set_tag(
                "mlflow.runName",
                f"ensemble_{strategy_name}__{splits['test_start']}",
            )
            mlflow.log_param("run_date", run_date)
            for k, v in splits.items():
                mlflow.log_param(k, v)
            ensemble.log_model()
            mlflow.log_metric("test_mape", mape)
            mlflow.log_metric("mape_gain_vs_best_individual", gain)
            mlflow.log_metric("gain_threshold_met", int(gain > GAIN_THRESHOLD_PCT))

            verdict = "PASS" if gain > GAIN_THRESHOLD_PCT else "FAIL (below threshold)"
            print(
                f"[ensemble:{strategy_name}] test_mape={mape:.2f}%  "
                f"gain={gain:+.2f}% vs individual  → {verdict}"
            )


def _build_ensemble(strategy: str) -> EnsembleForecaster:
    return EnsembleForecaster(
        forecasters=[LGBMForecaster(), XGBForecaster()],
        strategy=strategy,
    )


def _build_stacking_ensemble(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    run_date: str,
) -> EnsembleForecaster:
    lgbm = LGBMForecaster()
    xgb = XGBForecaster()

    cv_lgbm = walk_forward_cv(LGBMForecaster(), df, feature_cols, target_col, run_date)
    cv_xgb = walk_forward_cv(XGBForecaster(), df, feature_cols, target_col, run_date)
    print(
        f"Walk-forward CV — LightGBM: {cv_lgbm['mape_mean']:.2f}% ± {cv_lgbm['mape_std']:.2f}%"
    )
    print(
        f"Walk-forward CV — XGBoost:  {cv_xgb['mape_mean']:.2f}% ± {cv_xgb['mape_std']:.2f}%"
    )

    ensemble = EnsembleForecaster(
        forecasters=[lgbm, xgb],
        strategy="stacking",
        meta_model=Ridge(alpha=1.0),
    )
    return ensemble


def _get_best_individual_mape(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> float:
    best = float("inf")
    for model in [LGBMForecaster(), XGBForecaster()]:
        model.fit(X_train, y_train, X_val, y_val)
        mape = _mape(y_test, model.predict(X_test))
        if mape < best:
            best = mape
    return best


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
    run_ensemble_comparison(args.run_date, cache_path=args.features_cache)
