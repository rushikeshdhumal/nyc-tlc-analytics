"""Stage 5 — Hyperparameter tuning (Optuna) for LightGBM demand forecasting.

Runs an Optuna study on the same rolling train/val/test split logic used in
production training, logs results to MLflow, and registers the best model as
Staging.

Usage:
  python -m ml.experiments.demand_forecast.hyperparameter_tuning --run-date 2026-04-22
  python -m ml.experiments.demand_forecast.hyperparameter_tuning --run-date 2026-04-22 --features-cache data/features_eda.parquet
  python -m ml.experiments.demand_forecast.hyperparameter_tuning --run-date 2026-04-22 --n-trials 100 --timeout-seconds 7200
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from typing import cast

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
from mlflow import lightgbm as mlflow_lightgbm
import numpy as np
import optuna
import pandas as pd

from ml.features.demand_features import FEATURE_COLS, TARGET_COL, build_feature_matrix
from ml.models.demand_forecast.train import _compute_splits
from ml.utils.mlflow_utils import get_or_create_experiment, register_and_stage, setup_tracking

EXPERIMENT_NAME = "demand_forecast_hourly"
MODEL_NAME = "demand_forecast_hourly"
DEFAULT_BASELINE_STAGE4_TEST_MAPE = 35.22


@dataclass
class DataSplit:
    X_train: np.ndarray
    y_train: np.ndarray
    X_val: np.ndarray
    y_val: np.ndarray
    X_test: np.ndarray
    y_test: np.ndarray
    baseline_mape: float
    splits: dict[str, str]


@dataclass
class TrialResult:
    val_mape: float
    test_mape: float
    params: dict[str, object]
    model: lgb.Booster


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _save_feature_importance(model: lgb.Booster, feature_names: list[str]) -> str:
    importances = model.feature_importance(importance_type="gain")
    top_n = min(20, len(feature_names))
    idx = np.argsort(importances)[-top_n:]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh([feature_names[i] for i in idx], importances[idx])
    ax.set_xlabel("Gain")
    ax.set_title("Top Feature Importances")
    fig.tight_layout()
    path = os.path.join(tempfile.gettempdir(), "feature_importance_tuned.png")
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


def _save_predictions_vs_actuals(y_true: np.ndarray, y_pred: np.ndarray) -> str:
    n = min(500, len(y_true))
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(y_true[:n], label="Actuals", alpha=0.7)
    ax.plot(y_pred[:n], label="Predicted", alpha=0.7)
    ax.set_title("Holdout: Predictions vs Actuals (Tuned)")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(tempfile.gettempdir(), "predictions_vs_actuals_tuned.png")
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
    ax.set_title("Residuals (Holdout, Tuned)")
    fig.tight_layout()
    path = os.path.join(tempfile.gettempdir(), "residuals_tuned.png")
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


def _load_split_data(run_date: str, cache_path: str | None) -> DataSplit:
    splits = _compute_splits(run_date)

    if cache_path and os.path.exists(cache_path):
        print(f"Loading features from cache: {cache_path}")
        df = pd.read_parquet(cache_path)
    else:
        df = build_feature_matrix(splits["train_start"], splits["test_end"])
        df = df.dropna(subset=FEATURE_COLS)
        if cache_path:
            df.to_parquet(cache_path, index=False)
            print(f"Features cached to: {cache_path}")

    train_df = df[df["pickup_hour"] <= pd.Timestamp(splits["train_end"])]
    val_df = df[
        (df["pickup_hour"] >= pd.Timestamp(splits["val_start"]))
        & (df["pickup_hour"] <= pd.Timestamp(splits["val_end"]))
    ]
    test_df = df[df["pickup_hour"] >= pd.Timestamp(splits["test_start"])]

    X_train = np.asarray(train_df[FEATURE_COLS].values, dtype=np.float64)
    y_train = np.asarray(train_df[TARGET_COL].values, dtype=np.float64)
    X_val = np.asarray(val_df[FEATURE_COLS].values, dtype=np.float64)
    y_val = np.asarray(val_df[TARGET_COL].values, dtype=np.float64)
    X_test = np.asarray(test_df[FEATURE_COLS].values, dtype=np.float64)
    y_test = np.asarray(test_df[TARGET_COL].values, dtype=np.float64)

    baseline_raw = test_df["lag_168h_trip_count"].values
    valid_mask = ~np.isnan(baseline_raw)
    baseline_mape = _mape(y_test[valid_mask], baseline_raw[valid_mask])

    return DataSplit(
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        X_test=X_test,
        y_test=y_test,
        baseline_mape=baseline_mape,
        splits=splits,
    )


def run_hyperparameter_tuning(
    run_date: str,
    cache_path: str | None = None,
    n_trials: int = 100,
    timeout_seconds: int | None = None,
    stage4_best_test_mape: float = DEFAULT_BASELINE_STAGE4_TEST_MAPE,
) -> dict[str, object]:
    setup_tracking()
    experiment_id = get_or_create_experiment(EXPERIMENT_NAME)
    data = _load_split_data(run_date, cache_path)

    print(
        f"Rolling splits for run_date={run_date}:\n"
        f"  train: {data.splits['train_start']} -> {data.splits['train_end']}\n"
        f"  val:   {data.splits['val_start']} -> {data.splits['val_end']}\n"
        f"  test:  {data.splits['test_start']} -> {data.splits['test_end']}"
    )

    best_result: TrialResult | None = None

    def objective(trial: optuna.trial.Trial) -> float:
        nonlocal best_result
        params = {
            "objective": "regression",
            "metric": "mae",
            "verbosity": -1,
            "seed": 42,
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 31, 255),
            "max_depth": trial.suggest_int("max_depth", 4, 14),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 120),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.6, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.6, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
            "lambda_l1": trial.suggest_float("lambda_l1", 1e-8, 10.0, log=True),
            "lambda_l2": trial.suggest_float("lambda_l2", 1e-8, 10.0, log=True),
        }

        dtrain = lgb.Dataset(
            data.X_train,
            label=np.log1p(data.y_train),
            feature_name=FEATURE_COLS,
        )
        dval = lgb.Dataset(
            data.X_val,
            label=np.log1p(data.y_val),
            feature_name=FEATURE_COLS,
            reference=dtrain,
        )

        callbacks = [
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=0),
        ]

        with mlflow.start_run(experiment_id=experiment_id, nested=True):
            mlflow.set_tag("stage", "hyperparameter_tuning_trial")
            mlflow.set_tag("mlflow.runName", f"tuning_trial_{trial.number}")
            mlflow.log_param("run_date", run_date)
            mlflow.log_param("trial_number", trial.number)
            mlflow.log_param("n_features", len(FEATURE_COLS))
            mlflow.log_param("features", ",".join(FEATURE_COLS))
            for key, value in data.splits.items():
                mlflow.log_param(key, value)
            mlflow.log_param("hyperparams", json.dumps(params))

            model = lgb.train(
                params=params,
                train_set=dtrain,
                num_boost_round=1000,
                valid_sets=[dval],
                callbacks=callbacks,
            )

            val_raw = cast(np.ndarray, model.predict(data.X_val))
            test_raw = cast(np.ndarray, model.predict(data.X_test))
            val_pred = np.maximum(np.expm1(val_raw), 0.0)
            test_pred = np.maximum(np.expm1(test_raw), 0.0)
            val_mape = _mape(data.y_val, val_pred)
            test_mape = _mape(data.y_test, test_pred)

            mlflow.log_metric("val_mape", val_mape)
            mlflow.log_metric("test_mape", test_mape)

            if best_result is None or val_mape < best_result.val_mape:
                best_result = TrialResult(
                    val_mape=val_mape,
                    test_mape=test_mape,
                    params=params,
                    model=model,
                )

            trial.set_user_attr("test_mape", test_mape)
            return val_mape

    with mlflow.start_run(experiment_id=experiment_id) as parent_run:
        mlflow.set_tag("stage", "hyperparameter_tuning")
        mlflow.set_tag("mlflow.runName", f"lgbm_tuning__{data.splits['train_end']}__{n_trials}trials")
        mlflow.log_param("model_type", "lightgbm")
        mlflow.log_param("run_date", run_date)
        mlflow.log_param("n_trials", n_trials)
        mlflow.log_param("timeout_seconds", timeout_seconds if timeout_seconds is not None else "none")
        mlflow.log_param("features", ",".join(FEATURE_COLS))
        mlflow.log_param("n_features", len(FEATURE_COLS))
        mlflow.log_param("stage4_best_test_mape", stage4_best_test_mape)
        for key, value in data.splits.items():
            mlflow.log_param(key, value)

        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.TPESampler(seed=42),
            study_name=f"lgbm_tuning_{run_date}",
        )
        study.optimize(objective, n_trials=n_trials, timeout=timeout_seconds)

        best_trial = study.best_trial
        if best_result is None:
            raise RuntimeError("No successful trial produced a model.")
        best_params = best_result.params
        best_model = best_result.model

        best_val_raw = cast(np.ndarray, best_model.predict(data.X_val))
        best_test_raw = cast(np.ndarray, best_model.predict(data.X_test))
        val_pred = np.maximum(np.expm1(best_val_raw), 0.0)
        test_pred = np.maximum(np.expm1(best_test_raw), 0.0)

        val_mae = _mae(data.y_val, val_pred)
        val_rmse = _rmse(data.y_val, val_pred)
        val_mape = _mape(data.y_val, val_pred)
        test_mae = _mae(data.y_test, test_pred)
        test_rmse = _rmse(data.y_test, test_pred)
        test_mape = _mape(data.y_test, test_pred)

        mape_vs_baseline = data.baseline_mape - test_mape
        mape_gain_vs_stage4 = stage4_best_test_mape - test_mape

        mlflow.log_param("hyperparams", json.dumps(best_params))
        mlflow.log_param("best_trial_number", best_trial.number)

        mlflow.log_metric("val_mae", val_mae)
        mlflow.log_metric("val_rmse", val_rmse)
        mlflow.log_metric("val_mape", val_mape)
        mlflow.log_metric("test_mae", test_mae)
        mlflow.log_metric("test_rmse", test_rmse)
        mlflow.log_metric("test_mape", test_mape)
        mlflow.log_metric("baseline_mape", data.baseline_mape)
        mlflow.log_metric("mape_vs_baseline", mape_vs_baseline)
        mlflow.log_metric("mape_gain_vs_stage4", mape_gain_vs_stage4)
        mlflow.log_metric("trials_completed", len(study.trials))

        mlflow.log_artifact(_save_feature_importance(best_model, FEATURE_COLS))
        mlflow.log_artifact(_save_predictions_vs_actuals(data.y_test, test_pred))
        mlflow.log_artifact(_save_residuals(data.y_test, test_pred))

        mlflow_lightgbm.log_model(
            best_model,
            artifact_path="model",
            input_example=data.X_train[:100],
        )

        parent_run_id = parent_run.info.run_id

    version = register_and_stage(parent_run_id, MODEL_NAME, artifact_path="model", stage="Staging")

    print(
        f"Tuning complete. run_id={parent_run_id}, version={version}\n"
        f"  best_trial={best_trial.number}\n"
        f"  val_mape={val_mape:.2f}%  test_mape={test_mape:.2f}%\n"
        f"  baseline_mape={data.baseline_mape:.2f}%  mape_vs_baseline={mape_vs_baseline:+.2f}%\n"
        f"  gain_vs_stage4={mape_gain_vs_stage4:+.2f}% (target > +0.50%)"
    )

    return {
        "run_id": parent_run_id,
        "version": version,
        "best_trial": best_trial.number,
        "val_mape": val_mape,
        "test_mape": test_mape,
        "baseline_mape": data.baseline_mape,
        "mape_vs_baseline": mape_vs_baseline,
        "mape_gain_vs_stage4": mape_gain_vs_stage4,
        "passed_stage5_gate": mape_gain_vs_stage4 > 0.5,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--features-cache", metavar="PATH", default=None)
    parser.add_argument("--n-trials", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=None)
    parser.add_argument(
        "--stage4-best-test-mape",
        type=float,
        default=DEFAULT_BASELINE_STAGE4_TEST_MAPE,
        help="Best Stage 4 test MAPE used for Stage 5 gate comparison.",
    )
    args = parser.parse_args()

    run_hyperparameter_tuning(
        run_date=args.run_date,
        cache_path=args.features_cache,
        n_trials=args.n_trials,
        timeout_seconds=args.timeout_seconds,
        stage4_best_test_mape=args.stage4_best_test_mape,
    )
