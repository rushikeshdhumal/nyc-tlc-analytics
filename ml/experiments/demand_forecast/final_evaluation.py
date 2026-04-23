"""Stage 6 — Final evaluation for demand forecasting.

Validates the Stage 4 LightGBM model (default params) before production
registration:
  1. Walk-forward CV (3 consecutive monthly windows) — std gate < 2.0%
  2. SHAP summary via TreeExplainer (logged as artifact)
  3. Error segmentation by zone (pu_location_id) and by hour (hour_of_day)
  4. Promotion recommendation printed to stdout

All runs tagged stage=final_evaluation.

Promotion gates (ML_DEVELOPMENT_WORKFLOW.md §5 Stage 6):
  - CV MAPE std < 2.0%
  - test_mape < Stage 4 best (35.22%)
  - mape_vs_baseline > 0

If all gates pass: run train.py, then manually promote alias staging → production
in the MLflow UI.

Usage:
  python -m ml.experiments.demand_forecast.final_evaluation --run-date 2026-04-22
  python -m ml.experiments.demand_forecast.final_evaluation --run-date 2026-04-22 --features-cache data/features_eda.parquet
"""
from __future__ import annotations

import argparse
import os
import tempfile

import mlflow
import numpy as np
import pandas as pd

from ml.features.demand_features import FEATURE_COLS, TARGET_COL, build_feature_matrix
from ml.models.demand_forecast.lgbm_forecaster import LGBMForecaster
from ml.models.demand_forecast.train import _compute_splits
from ml.utils.evaluation import (
    plot_error_by_segment,
    segment_errors,
    walk_forward_cv,
)
from ml.utils.mlflow_utils import get_or_create_experiment
from ml.utils.shap_utils import log_shap_summary

EXPERIMENT_NAME = "demand_forecast_hourly"
CV_STD_GATE = 2.0
STAGE4_BEST_TEST_MAPE = 35.22
SHAP_SAMPLE_SIZE = 2000


def run_final_evaluation(run_date: str, cache_path: str | None = None) -> None:
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
    test_df = df[df["pickup_hour"] >= pd.Timestamp(splits["test_start"])].reset_index(drop=True)
    y_test = test_df[TARGET_COL].values

    X_train = train_df[FEATURE_COLS].values
    y_train = train_df[TARGET_COL].values
    X_val = val_df[FEATURE_COLS].values
    y_val = val_df[TARGET_COL].values
    X_test = test_df[FEATURE_COLS].values

    # ── 1. Walk-forward CV ────────────────────────────────────────────────────
    print("Running walk-forward CV (3 windows)...")
    cv_results = walk_forward_cv(
        LGBMForecaster(), df, FEATURE_COLS, TARGET_COL, run_date, n_windows=3
    )
    cv_gate_pass = cv_results["mape_std"] < CV_STD_GATE
    print(
        f"  CV MAPE: {cv_results['mape_mean']:.2f}% "
        f"± {cv_results['mape_std']:.2f}%  "
        f"per-window: {[f'{m:.2f}%' for m in cv_results['mape_per_window']]}"
    )
    print(f"  CV std gate (< {CV_STD_GATE}%): {'PASS' if cv_gate_pass else 'FAIL'}")

    # ── 2. Holdout evaluation (baseline, SHAP, segmentation need trained model)
    print("\nTraining evaluation model on current split...")
    eval_model = LGBMForecaster()
    eval_model.fit(X_train, y_train, X_val, y_val)
    preds = eval_model.predict(X_test)
    val_preds = eval_model.predict(X_val)
    test_mape = _mape(y_test, preds)
    val_mape = _mape(val_df[TARGET_COL].values, val_preds)
    beats_stage4 = test_mape < STAGE4_BEST_TEST_MAPE

    baseline_raw = test_df["lag_168h_trip_count"].values
    valid_mask = ~np.isnan(baseline_raw)
    baseline_mape = _mape(y_test[valid_mask], baseline_raw[valid_mask])
    mape_vs_baseline = baseline_mape - test_mape
    beats_baseline = mape_vs_baseline > 0

    with mlflow.start_run(experiment_id=experiment_id) as run:
        mlflow.set_tag("stage", "final_evaluation")
        mlflow.set_tag("mlflow.runName", f"final_eval__{splits['test_start']}")
        mlflow.log_param("run_date", run_date)
        for k, v in splits.items():
            mlflow.log_param(k, v)

        mlflow.log_metric("cv_mape_mean", cv_results["mape_mean"])
        mlflow.log_metric("cv_mape_std", cv_results["mape_std"])
        mlflow.log_metric("cv_gate_pass", int(cv_gate_pass))
        for i, m in enumerate(cv_results["mape_per_window"]):
            mlflow.log_metric(f"cv_mape_window_{i}", m)

        mlflow.log_metric("val_mape", val_mape)
        mlflow.log_metric("test_mape", test_mape)
        mlflow.log_metric("baseline_mape", baseline_mape)
        mlflow.log_metric("mape_vs_baseline", mape_vs_baseline)
        mlflow.log_metric("beats_stage4_best", int(beats_stage4))

        # ── 3. SHAP summary ──────────────────────────────────────────────────
        print("Computing SHAP values (TreeExplainer)...")
        n_shap = min(SHAP_SAMPLE_SIZE, len(X_test))
        rng = np.random.default_rng(42)
        shap_idx = rng.choice(len(X_test), size=n_shap, replace=False)
        fd, shap_path = tempfile.mkstemp(prefix="shap_summary_", suffix=".png")
        os.close(fd)
        log_shap_summary(
            eval_model._model,
            X_test[shap_idx],
            FEATURE_COLS,
            model_type="lightgbm",
            out_path=shap_path,
        )

        # ── 4. Error segmentation ────────────────────────────────────────────
        print("Computing error segmentation...")
        zone_seg = segment_errors(y_test, preds, test_df, "pu_location_id")
        fd, zone_path = tempfile.mkstemp(prefix="error_by_zone_", suffix=".png")
        os.close(fd)
        plot_error_by_segment(zone_seg, "pu_location_id", "MAPE by Zone (Top 20 Worst)", zone_path)
        mlflow.log_artifact(zone_path)

        hour_seg = segment_errors(y_test, preds, test_df, "hour_of_day")
        fd, hour_path = tempfile.mkstemp(prefix="error_by_hour_", suffix=".png")
        os.close(fd)
        plot_error_by_segment(hour_seg, "hour_of_day", "MAPE by Hour of Day", hour_path)
        mlflow.log_artifact(hour_path)

        run_id = run.info.run_id

    # ── Promotion recommendation ─────────────────────────────────────────────
    all_pass = cv_gate_pass and beats_stage4 and beats_baseline
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"STAGE 6 FINAL EVALUATION — {splits['test_start']}")
    print(sep)
    print(f"  test_mape:        {test_mape:.2f}%")
    print(f"  val_mape:         {val_mape:.2f}%")
    print(
        f"  CV MAPE:          {cv_results['mape_mean']:.2f}% "
        f"± {cv_results['mape_std']:.2f}%"
    )
    print(f"  baseline_mape:    {baseline_mape:.2f}%")
    print(f"  mape_vs_baseline: {mape_vs_baseline:+.2f}%")
    print()
    print(f"  Gate 1 — CV std < {CV_STD_GATE}%:                    {'PASS' if cv_gate_pass else 'FAIL'}")
    print(f"  Gate 2 — test_mape < Stage 4 ({STAGE4_BEST_TEST_MAPE}%):  {'PASS' if beats_stage4 else 'FAIL'}")
    print(f"  Gate 3 — beats lag-168 baseline:             {'PASS' if beats_baseline else 'FAIL'}")
    print()
    if all_pass:
        print("  → PROMOTE")
        print("    1. python -m ml.models.demand_forecast.train --run-date", run_date)
        print("    2. Set alias production in MLflow UI (Models → demand_forecast_hourly → Staging version)")
    else:
        print("  → HOLD — review failed gate(s) above")
    print(f"\n  MLflow run_id: {run_id}")


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument(
        "--features-cache",
        metavar="PATH",
        default="data/features_eda.parquet",
        help=(
            "Path to a Parquet cache file for the feature matrix. "
            "Loads from disk if the file exists; queries Snowflake and saves otherwise. "
            "Default: data/features_eda.parquet"
        ),
    )
    args = parser.parse_args()
    run_final_evaluation(args.run_date, cache_path=args.features_cache)
