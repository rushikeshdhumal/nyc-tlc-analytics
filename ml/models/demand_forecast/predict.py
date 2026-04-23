"""LightGBM demand forecasting — prediction script (Phase 7).

Loads the production alias model from MLflow Registry and writes predictions
to NYC_TLC_DB.ML.fct_demand_forecast.

Usage: python predict.py --run-date YYYY-MM-DD

The prediction window is the calendar month two months before run-date,
matching the TLC 2-month publish lag. This is the month that was just
ingested by the ingest_nyc_taxi_raw DAG, so actuals exist in Gold for
forecast-vs-actuals comparison in Superset.

Example: --run-date 2026-04-05  →  predicts for 2026-02-01 to 2026-02-28.

Timeline for an April 5 retrain run:
  Apr 1: ingest_nyc_taxi_raw loads 2026-02 into Gold
  Apr 5: retrain_demand_forecast trains on data through 2026-02,
      then predicts for 2026-02 using the production model alias.
"""
from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from mlflow import lightgbm as mlflow_lightgbm
from mlflow.tracking import MlflowClient

from ml.features.demand_features import FEATURE_COLS, build_feature_matrix
from ml.utils.mlflow_utils import setup_tracking
from ml.utils.snowflake_io import delete_ml_rows, insert_demand_forecast_rows


_TLC_LAG = 2  # months between run_date and last available Gold month


def _prediction_window(run_date: str) -> tuple[str, str]:
    """Return (start, end) for the last complete month available in Gold.

    Uses the same TLC_LAG offset as _compute_splits in train.py so predictions
    always target a month whose actuals exist in Gold.
    """
    dt = datetime.strptime(run_date, "%Y-%m-%d")
    year = dt.year
    month = dt.month - _TLC_LAG
    if month <= 0:
        month += 12
        year -= 1
    last_day = monthrange(year, month)[1]
    start = datetime(year, month, 1).strftime("%Y-%m-%d")
    end = datetime(year, month, last_day).strftime("%Y-%m-%d")
    return start, end


def run_predictions(run_date: str) -> int:
    """Load production model alias from MLflow Registry and write predictions to Snowflake.

    Generates predictions for the calendar month two months prior to run_date.
    Raises RuntimeError if no production model alias exists (ML_EXPERIMENT_STANDARDS.md §5).
    Returns number of rows written.
    """
    setup_tracking()
    client = MlflowClient()
    model_name = "demand_forecast_hourly"
    production_version = client.get_model_version_by_alias(model_name, "production").version
    model = mlflow_lightgbm.load_model(f"models:/{model_name}/{production_version}")

    pred_start, pred_end = _prediction_window(run_date)
    pred_end_exclusive = (
        datetime.strptime(pred_end, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    print(f"Generating predictions for {pred_start} to {pred_end}")

    df = build_feature_matrix(pred_start, pred_end)
    df = df.dropna(subset=FEATURE_COLS)

    if df.empty:
        raise ValueError(f"No feature data available for {pred_start} to {pred_end}")

    df = df.reset_index(drop=True)
    prediction_features = df[FEATURE_COLS].astype("float64")
    raw = model.predict(prediction_features)
    predictions = np.maximum(np.expm1(np.asarray(raw).flatten()), 0.0)
    predictions = np.round(predictions, 2)
    pickup_hours = pd.to_datetime(df["pickup_hour"], utc=True).dt.tz_convert(None)

    out = pd.DataFrame(
        {
            "PICKUP_HOUR": pd.Series(
                [ts.to_pydatetime() for ts in pickup_hours],
                dtype="object",
            ),
            "PU_LOCATION_ID": pd.Series(df["pu_location_id"].to_numpy(), dtype="int64"),
            "PICKUP_BOROUGH": pd.Series(df["pickup_borough"].to_numpy(), dtype="object"),
            "PREDICTED_TRIP_COUNT": pd.Series(
                predictions.astype("float64"),
                dtype="float64",
            ),
            "MODEL_VERSION": pd.Series([str(production_version)] * len(df), dtype="object"),
            "_RUN_DATE": pd.Series(
                [datetime.strptime(run_date, "%Y-%m-%d").date()] * len(df),
                dtype="object",
            ),
        }
    )

    out = out.reset_index(drop=True)

    # Clean up prior retries for the same run_date (including historically bad rows).
    delete_ml_rows("fct_demand_forecast", f"_RUN_DATE = '{run_date}'")

    # Make reruns idempotent for the full forecast window, regardless of run_date.
    delete_ml_rows(
        "fct_demand_forecast",
        (
            "PICKUP_HOUR >= TO_TIMESTAMP_NTZ('"
            f"{pred_start} 00:00:00'"
            ") AND PICKUP_HOUR < TO_TIMESTAMP_NTZ('"
            f"{pred_end_exclusive} 00:00:00'"
            ")"
        ),
    )
    insert_demand_forecast_rows(out)
    print(f"Wrote {len(out):,} prediction rows to ML.fct_demand_forecast")
    return len(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Execution date; predictions are generated for calendar month -2",
    )
    args = parser.parse_args()
    run_predictions(args.run_date)
