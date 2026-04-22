"""LightGBM demand forecasting — training script (Phase 7).

Usage: python train.py --run-date YYYY-MM-DD
Logs experiment to MLflow under 'demand_forecast_hourly'.
Registers best model in MLflow and assigns alias 'staging'.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from calendar import monthrange
from datetime import date, timedelta

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import mlflow.lightgbm
import numpy as np
import pandas as pd

from ml.features.demand_features import FEATURE_COLS, TARGET_COL, build_feature_matrix
from ml.utils.mlflow_utils import get_or_create_experiment, register_and_stage

INGEST_START = "2024-01-01"   # matches upload_to_azure.py / ingest DAG start_date
_TLC_LAG = 2                  # months between run_date and last available Gold month

EXPERIMENT_NAME = "demand_forecast_hourly"
MODEL_NAME = "demand_forecast_hourly"


def _compute_splits(run_date: str) -> dict[str, str]:
    """Derive rolling train/val/test boundaries from run_date.

    Gold has data through (run_date month - _TLC_LAG).
    Test  = that last complete month (1 month).
    Val   = the month immediately before test (1 month).
    Train = INGEST_START → day before val start.

    Example — run_date 2026-04-05:
        test:  2026-02-01 → 2026-02-28
        val:   2026-01-01 → 2026-01-31
        train: 2024-01-01 → 2025-12-31
    """
    d = date.fromisoformat(run_date[:10]).replace(day=1)
    for _ in range(_TLC_LAG):
        d = date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)

    test_start = d
    test_end = date(d.year, d.month, monthrange(d.year, d.month)[1])

    val_d = date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)
    val_start = val_d
    val_end = date(val_d.year, val_d.month, monthrange(val_d.year, val_d.month)[1])

    train_start = date.fromisoformat(INGEST_START)
    train_end = val_start - timedelta(days=1)

    return {
        "train_start": train_start.isoformat(),
        "train_end":   train_end.isoformat(),
        "val_start":   val_start.isoformat(),
        "val_end":     val_end.isoformat(),
        "test_start":  test_start.isoformat(),
        "test_end":    test_end.isoformat(),
    }

_LGB_PARAMS: dict = {
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


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _new_temp_png_path(prefix: str) -> str:
    fd, path = tempfile.mkstemp(prefix=f"{prefix}_", suffix=".png")
    os.close(fd)
    return path


def _save_feature_importance(model: lgb.Booster, feature_names: list[str]) -> str:
    importances = model.feature_importance(importance_type="gain")
    top_n = min(20, len(feature_names))
    idx = np.argsort(importances)[-top_n:]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh([feature_names[i] for i in idx], importances[idx])
    ax.set_xlabel("Gain")
    ax.set_title("Top Feature Importances")
    fig.tight_layout()
    path = _new_temp_png_path("feature_importance")
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


def _save_predictions_vs_actuals(
    y_true: np.ndarray, y_pred: np.ndarray, title: str
) -> str:
    # Sample first 500 rows to keep chart readable
    n = min(500, len(y_true))
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(y_true[:n], label="Actuals", alpha=0.7)
    ax.plot(y_pred[:n], label="Predicted", alpha=0.7)
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    path = _new_temp_png_path("predictions_vs_actuals")
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


def _save_residuals(y_true: np.ndarray, y_pred: np.ndarray) -> str:
    residuals = y_true - y_pred
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.scatter(y_pred, residuals, alpha=0.2, s=1)
    ax.axhline(0, color="red", linewidth=1)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Residual")
    ax.set_title("Residuals (Holdout)")
    fig.tight_layout()
    path = _new_temp_png_path("residuals")
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


def run_training(run_date: str, cache_path: str | None = None) -> dict:
    """Train LightGBM on rolling date splits, log to MLflow, register with alias 'staging'.

    cache_path: optional path to a Parquet file.
      - If the file exists: load features from disk (no Snowflake query).
      - If the file does not exist: query Snowflake, then save to disk.
      - If None: always query Snowflake.
    Cache is valid as long as the splits don't change (i.e. same run_date month).
    Delete the file when new monthly data lands in Gold.

    Returns a dict with run metadata (run_id, version, metrics).
    Promotion from alias 'staging' to alias 'production' is a deliberate manual step
    (ML_EXPERIMENT_STANDARDS.md §4).
    """
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    experiment_id = get_or_create_experiment(EXPERIMENT_NAME)

    splits = _compute_splits(run_date)
    train_start = splits["train_start"]
    train_end   = splits["train_end"]
    val_start   = splits["val_start"]
    val_end     = splits["val_end"]
    test_start  = splits["test_start"]
    test_end    = splits["test_end"]

    print(
        f"Rolling splits for run_date={run_date}:\n"
        f"  train: {train_start} → {train_end}\n"
        f"  val:   {val_start} → {val_end}\n"
        f"  test:  {test_start} → {test_end}"
    )

    if cache_path and os.path.exists(cache_path):
        print(f"Loading features from cache: {cache_path}")
        df = pd.read_parquet(cache_path)
    else:
        df = build_feature_matrix(train_start, test_end)
        df = df.dropna(subset=FEATURE_COLS)
        if cache_path:
            df.to_parquet(cache_path, index=False)
            print(f"Features cached to: {cache_path}")

    # Time-based splits — never shuffle (ML_FEATURE_CONTRACTS.md §Model 1)
    train_df = df[df["pickup_hour"] <= pd.Timestamp(train_end)]
    val_df = df[
        (df["pickup_hour"] >= pd.Timestamp(val_start))
        & (df["pickup_hour"] <= pd.Timestamp(val_end))
    ]
    test_df = df[df["pickup_hour"] >= pd.Timestamp(test_start)]

    X_train = train_df[FEATURE_COLS].values
    y_train = train_df[TARGET_COL].values
    X_val = val_df[FEATURE_COLS].values
    y_val = val_df[TARGET_COL].values
    X_test = test_df[FEATURE_COLS].values
    y_test = test_df[TARGET_COL].values

    dtrain = lgb.Dataset(X_train, label=np.log1p(y_train), feature_name=FEATURE_COLS)
    dval   = lgb.Dataset(X_val,   label=np.log1p(y_val),   feature_name=FEATURE_COLS, reference=dtrain)

    callbacks = [
        lgb.early_stopping(stopping_rounds=50, verbose=False),
        lgb.log_evaluation(period=100),
    ]

    with mlflow.start_run(experiment_id=experiment_id) as run:
        model: lgb.Booster = lgb.train(
            params=_LGB_PARAMS,
            train_set=dtrain,
            num_boost_round=1000,
            valid_sets=[dval],
            callbacks=callbacks,
        )

        val_pred  = np.maximum(np.expm1(model.predict(X_val)),  0.0)
        test_pred = np.maximum(np.expm1(model.predict(X_test)), 0.0)

        # Naive lag-168 baseline on holdout (ML_FEATURE_CONTRACTS.md §Model 1)
        baseline_raw = test_df["lag_168h_trip_count"].values
        valid_mask = ~np.isnan(baseline_raw)
        baseline_mape = _mape(y_test[valid_mask], baseline_raw[valid_mask])

        val_mae = _mae(y_val, val_pred)
        val_rmse = _rmse(y_val, val_pred)
        val_mape = _mape(y_val, val_pred)
        test_mae = _mae(y_test, test_pred)
        test_rmse = _rmse(y_test, test_pred)
        test_mape = _mape(y_test, test_pred)
        mape_vs_baseline = baseline_mape - test_mape

        # Required params — ML_EXPERIMENT_STANDARDS.md §2
        mlflow.log_param("model_type", "lightgbm")
        mlflow.log_param("log1p_target", True)
        mlflow.log_param("run_date", run_date)
        mlflow.log_param("train_start", train_start)
        mlflow.log_param("train_end",   train_end)
        mlflow.log_param("val_start",   val_start)
        mlflow.log_param("val_end",     val_end)
        mlflow.log_param("test_start",  test_start)
        mlflow.log_param("test_end",    test_end)
        mlflow.log_param("features", ",".join(FEATURE_COLS))
        mlflow.log_param("n_features", len(FEATURE_COLS))
        mlflow.log_param("hyperparams", json.dumps(_LGB_PARAMS))

        # Required metrics — ML_EXPERIMENT_STANDARDS.md §2
        mlflow.log_metric("val_mae", val_mae)
        mlflow.log_metric("val_rmse", val_rmse)
        mlflow.log_metric("val_mape", val_mape)
        mlflow.log_metric("test_mae", test_mae)
        mlflow.log_metric("test_rmse", test_rmse)
        mlflow.log_metric("test_mape", test_mape)
        mlflow.log_metric("baseline_mape", baseline_mape)
        mlflow.log_metric("mape_vs_baseline", mape_vs_baseline)

        # Run name: scannable in MLflow UI without opening each run
        mlflow.set_tag(
            "mlflow.runName", f"lightgbm__{train_end}__{val_mape:.1f}pct"
        )
        mlflow.set_tag("stage", "production_candidate")

        # Required artifacts — ML_EXPERIMENT_STANDARDS.md §2
        mlflow.log_artifact(_save_feature_importance(model, FEATURE_COLS))
        mlflow.log_artifact(
            _save_predictions_vs_actuals(
                y_test, test_pred, "Holdout: Predictions vs Actuals"
            )
        )
        mlflow.log_artifact(_save_residuals(y_test, test_pred))

        mlflow.lightgbm.log_model(
            model,
            artifact_path="model",
            input_example=X_train[:100],  # Representative sample for signature inference
        )

        run_id = run.info.run_id

    version = register_and_stage(run_id, MODEL_NAME, artifact_path="model", stage="Staging")

    print(
        f"Training complete. run_id={run_id}, version={version}\n"
        f"  val_mape={val_mape:.2f}%  test_mape={test_mape:.2f}%\n"
        f"  baseline_mape={baseline_mape:.2f}%  mape_vs_baseline={mape_vs_baseline:+.2f}%"
    )

    return {
        "run_id": run_id,
        "version": version,
        "val_mape": val_mape,
        "test_mape": test_mape,
        "baseline_mape": baseline_mape,
        "mape_vs_baseline": mape_vs_baseline,
        "beats_baseline": mape_vs_baseline > 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Execution date for MLflow logging (does not affect data splits)",
    )
    parser.add_argument(
        "--features-cache",
        metavar="PATH",
        default="data/features_eda.parquet",
        help=(
            "Path to a Parquet cache file for the feature matrix. "
            "Loads from disk if the file exists; queries Snowflake and saves otherwise. "
            "Delete the file when new monthly Gold data lands. "
            "Default: data/features_eda.parquet"
        ),
    )
    args = parser.parse_args()
    run_training(args.run_date, cache_path=args.features_cache)
