"""Demand forecast model monitoring — Phase 9.

Computes prediction error metrics (MAE/RMSE/MAPE) for the latest forecast window
by joining ML.fct_demand_forecast predictions against Gold actuals, detects feature
distribution drift vs the training baseline stored as a MLflow artifact, and writes
one summary row to ML.fct_model_monitoring.

MAPE degradation is flagged when either:
  - Current MAPE > training test_mape * 1.2  (20% relative degradation)
  - Current MAPE > training baseline_mape    (model no longer beats naive lag-168)

Drift is flagged per feature when:
  |current_month_mean - training_mean| > 2 * training_std

Usage: python monitor.py --run-date YYYY-MM-DD
"""
from __future__ import annotations

import argparse
import json
import logging
import tempfile
from calendar import monthrange
from datetime import datetime

import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient

from ml.features.demand_features import FEATURE_COLS, build_feature_matrix
from ml.utils.mlflow_utils import setup_tracking
from ml.utils.snowflake_io import (
    delete_ml_rows,
    insert_model_monitoring_rows,
    read_sql,
)

_TLC_LAG = 2
_MAPE_DEGRADATION_FACTOR = 1.2
_DRIFT_SIGMA = 2.0

logger = logging.getLogger(__name__)


def _prediction_window(run_date: str) -> tuple[str, str]:
    """Return (start, end) for the forecast month — mirrors predict.py."""
    dt = datetime.strptime(run_date, "%Y-%m-%d")
    year, month = dt.year, dt.month - _TLC_LAG
    if month <= 0:
        month += 12
        year -= 1
    last_day = monthrange(year, month)[1]
    start = datetime(year, month, 1).strftime("%Y-%m-%d")
    end = datetime(year, month, last_day).strftime("%Y-%m-%d")
    return start, end


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _load_feature_baseline(run_id: str) -> dict:
    """Download feature_baseline.json from an MLflow run and parse it."""
    local_dir = tempfile.mkdtemp(prefix="mlflow_baseline_dl_")
    try:
        local_path = mlflow.artifacts.download_artifacts(
            artifact_uri=f"runs:/{run_id}/feature_baseline.json",
            dst_path=local_dir,
        )
        with open(local_path) as f:
            return json.load(f)
    finally:
        import shutil
        shutil.rmtree(local_dir, ignore_errors=True)


def _detect_drift(
    current_df: pd.DataFrame,
    baseline: dict,
) -> list[str]:
    """Return names of features whose current mean has shifted > DRIFT_SIGMA σ."""
    drifted: list[str] = []
    feature_stats: dict = baseline.get("features", {})
    for col in FEATURE_COLS:
        if col not in feature_stats or col not in current_df.columns:
            continue
        bl = feature_stats[col]
        bl_mean: float = bl["mean"]
        bl_std: float = bl["std"]
        if bl_std == 0:
            continue
        current_mean = float(current_df[col].mean())
        if abs(current_mean - bl_mean) > _DRIFT_SIGMA * bl_std:
            drifted.append(col)
    return drifted


def run_monitoring(run_date: str) -> dict:
    """Run one monitoring cycle for the demand forecast model.

    Steps:
      1. Resolve production model version and run_id from MLflow.
      2. Load feature_baseline.json artifact (free — local MLflow).
      3. Pull training metrics (test_mape, baseline_mape) from MLflow run.
      4. Query fct_demand_forecast predictions for this run_date.
      5. Query Gold actuals for the same prediction window.
      6. Compute MAE / RMSE / MAPE on the joined set.
      7. Build current feature matrix → detect distribution drift.
      8. Write summary row to ML.fct_model_monitoring (idempotent).

    Returns dict with mape, mape_degraded, drifted_features, n_drifted_features.
    """
    setup_tracking()
    client = MlflowClient()
    model_name = "demand_forecast_hourly"

    mv = client.get_model_version_by_alias(model_name, "production")
    production_version: str = mv.version
    production_run_id: str = mv.run_id

    # Training metrics from the production model's run (no Snowflake credits).
    run_data = client.get_run(production_run_id).data
    training_test_mape: float = float(run_data.metrics.get("test_mape", float("nan")))
    training_baseline_mape: float = float(run_data.metrics.get("baseline_mape", float("nan")))

    # Feature baseline artifact (local MLflow — no Snowflake credits).
    try:
        baseline = _load_feature_baseline(production_run_id)
    except Exception as exc:
        logger.warning(
            "feature_baseline.json not found for run %s (%s). "
            "Drift detection skipped. Re-train the model to generate the artifact.",
            production_run_id, exc,
        )
        baseline = {}

    pred_start, pred_end = _prediction_window(run_date)
    prediction_month = pred_start[:7]
    dt_end = datetime.strptime(pred_end, "%Y-%m-%d")
    if dt_end.month == 12:
        next_month_start = f"{dt_end.year + 1}-01-01"
    else:
        next_month_start = f"{dt_end.year}-{dt_end.month + 1:02d}-01"

    print(f"Monitoring predictions for {pred_start} to {pred_end} (run_date={run_date})")

    # Predictions (one Snowflake query — ML schema).
    predictions_df = read_sql(f"""
        SELECT
            PICKUP_HOUR,
            PU_LOCATION_ID,
            PREDICTED_TRIP_COUNT,
            MODEL_VERSION
        FROM NYC_TLC_DB.ML.FCT_DEMAND_FORECAST
        WHERE _RUN_DATE = '{run_date}'
    """)
    predictions_df.columns = predictions_df.columns.str.lower()
    n_predictions = len(predictions_df)

    if predictions_df.empty:
        raise ValueError(
            f"No predictions found in ML.fct_demand_forecast for _RUN_DATE = '{run_date}'. "
            "Ensure write_predictions completed successfully before monitoring."
        )

    # Gold actuals (one Snowflake query — same warehouse charge as retrain).
    actuals_df = read_sql(f"""
        SELECT
            pickup_hour,
            pu_location_id,
            SUM(trip_count) AS trip_count
        FROM NYC_TLC_DB.GOLD.fct_revenue_per_zone_hourly
        WHERE pickup_hour >= '{pred_start}'::TIMESTAMP
          AND pickup_hour <  '{next_month_start}'::TIMESTAMP
        GROUP BY pickup_hour, pu_location_id
    """)
    actuals_df.columns = actuals_df.columns.str.lower()

    predictions_df["pickup_hour"] = pd.to_datetime(predictions_df["pickup_hour"])
    actuals_df["pickup_hour"] = pd.to_datetime(actuals_df["pickup_hour"])

    joined = predictions_df.merge(
        actuals_df,
        on=["pickup_hour", "pu_location_id"],
        how="inner",
    )
    n_actuals = len(joined)

    if joined.empty:
        raise ValueError(
            f"Predictions and Gold actuals produced an empty join for {prediction_month}. "
            "Check that Gold data exists for this month."
        )

    y_true = joined["trip_count"].to_numpy(dtype="float64")
    y_pred = joined["predicted_trip_count"].to_numpy(dtype="float64")

    mae = _mae(y_true, y_pred)
    rmse = _rmse(y_true, y_pred)
    mape = _mape(y_true, y_pred)

    # MAPE degradation check.
    mape_degraded = False
    if not np.isnan(training_test_mape):
        mape_degraded = mape > training_test_mape * _MAPE_DEGRADATION_FACTOR
    if not np.isnan(training_baseline_mape):
        mape_degraded = mape_degraded or (mape > training_baseline_mape)

    # Feature drift detection (one Snowflake query for current month features).
    drifted_features: list[str] = []
    if baseline:
        try:
            current_df = build_feature_matrix(pred_start, pred_end)
            current_df = current_df.dropna(subset=FEATURE_COLS)
            drifted_features = _detect_drift(current_df, baseline)
        except Exception as exc:
            logger.warning("Feature drift detection failed: %s", exc)

    drifted_str = ",".join(drifted_features)
    n_drifted = len(drifted_features)

    print(
        f"Monitoring results: MAE={mae:.2f}  RMSE={rmse:.2f}  MAPE={mape:.2f}%\n"
        f"  training_test_mape={training_test_mape:.2f}%  "
        f"baseline_mape={training_baseline_mape:.2f}%\n"
        f"  mape_degraded={mape_degraded}  n_drifted_features={n_drifted}"
    )
    if mape_degraded:
        logger.warning(
            "[MAPE DEGRADED] run_date=%s  current_mape=%.2f%%  "
            "training_test_mape=%.2f%%  baseline_mape=%.2f%%",
            run_date, mape, training_test_mape, training_baseline_mape,
        )
    if drifted_features:
        logger.warning(
            "[FEATURE DRIFT] run_date=%s  drifted=%s",
            run_date, drifted_str,
        )

    row = pd.DataFrame([{
        "monitor_date":        datetime.strptime(run_date, "%Y-%m-%d").date(),
        "prediction_month":    prediction_month,
        "model_version":       str(production_version),
        "model_run_id":        production_run_id,
        "mae":                 mae,
        "rmse":                rmse,
        "mape":                mape,
        "training_test_mape":  training_test_mape,
        "baseline_mape":       training_baseline_mape,
        "mape_degraded":       mape_degraded,
        "n_predictions":       n_predictions,
        "n_actuals":           n_actuals,
        "drifted_features":    drifted_str,
        "n_drifted_features":  n_drifted,
        "_scored_at":          datetime.utcnow(),
    }])

    delete_ml_rows("fct_model_monitoring", f"MONITOR_DATE = '{run_date}'")
    insert_model_monitoring_rows(row)
    print(f"Wrote monitoring row to ML.fct_model_monitoring for {run_date}")

    return {
        "mape":               mape,
        "mape_degraded":      mape_degraded,
        "drifted_features":   drifted_features,
        "n_drifted_features": n_drifted,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Execution date; must match the _RUN_DATE used by predict.py",
    )
    args = parser.parse_args()
    run_monitoring(args.run_date)
