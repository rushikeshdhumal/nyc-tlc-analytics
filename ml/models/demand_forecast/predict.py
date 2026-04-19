"""LightGBM demand forecasting — prediction script (Phase 7).

Loads the Production model from MLflow Registry and writes predictions
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
         then predicts for 2026-02 using the Production model.
"""
from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import datetime

import numpy as np
import pandas as pd

from ml.features.demand_features import FEATURE_COLS, build_feature_matrix
from ml.utils.mlflow_utils import get_production_model, setup_tracking
from ml.utils.snowflake_io import write_ml_table


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
    """Load Production model from MLflow Registry and write predictions to Snowflake.

    Generates predictions for the calendar month prior to run_date.
    Raises RuntimeError if no Production model exists (ML_EXPERIMENT_STANDARDS.md §5).
    Returns number of rows written.
    """
    setup_tracking()
    model = get_production_model("demand_forecast_hourly")

    pred_start, pred_end = _prediction_window(run_date)
    print(f"Generating predictions for {pred_start} to {pred_end}")

    df = build_feature_matrix(pred_start, pred_end)
    df = df.dropna(subset=FEATURE_COLS)

    if df.empty:
        raise ValueError(f"No feature data available for {pred_start} to {pred_end}")

    raw = model.predict(df[FEATURE_COLS])
    predictions = np.asarray(raw).flatten()

    out = pd.DataFrame(
        {
            "PICKUP_HOUR": df["pickup_hour"].values,
            "PU_LOCATION_ID": df["pu_location_id"].values,
            "PREDICTED_TRIP_COUNT": predictions.clip(min=0).round().astype(int),
            "MODEL_VERSION": "Production",
            "_RUN_DATE": run_date,
        }
    )

    write_ml_table(out, "fct_demand_forecast", overwrite=False)
    print(f"Wrote {len(out):,} prediction rows to ML.fct_demand_forecast")
    return len(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Execution date; predictions are generated for the preceding calendar month",
    )
    args = parser.parse_args()
    run_predictions(args.run_date)
