"""Congestion pricing DiD causal inference (Phase 8).

Fits two-way fixed effects difference-in-differences OLS regression:

    Y = α + β₁·post + β₃·(post × treated) + zone_FE + dow_FE + ε

The `treated` main effect is intentionally omitted — it is absorbed by zone
fixed effects (treated is time-invariant, constant within each zone). β₃ is
the causal estimate of the congestion pricing effect on outcome Y.

Treatment : Manhattan CBD Yellow Zone
            (pickup_borough = 'Manhattan' AND service_zone = 'Yellow Zone')
Control   : Brooklyn, Queens, Bronx
Pre period: 2024-01-01 to 2025-01-04
Post period: 2025-01-05 onward (CBD congestion pricing effective date)

Incremental: the post window grows monthly as new Gold data lands. Re-running
monthly stabilises the β₃ estimate and reveals whether the effect persists,
fades, or accelerates over time.

Writes per-zone per-period summary rows with DiD coefficients to:
    NYC_TLC_DB.ML.fct_congestion_pricing_impact

Logs experiment to MLflow under: congestion_pricing_did
Contract: .claude/ML_FEATURE_CONTRACTS.md §Model 3

Usage: python congestion_pricing_did.py --run-date YYYY-MM-DD
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import mlflow
import pandas as pd
import statsmodels.api as sm

from ml.utils.mlflow_utils import setup_tracking
from ml.utils.snowflake_io import (
    delete_ml_rows,
    insert_congestion_impact_rows,
    read_gold,
)

_TREATMENT_DATE = date(2025, 1, 5)
_PRE_START = date(2024, 1, 1)
_EXPERIMENT = "congestion_pricing_did"

_TREATMENT_FILTER = "(pickup_borough = 'Manhattan' AND service_zone = 'Yellow Zone')"
_CONTROL_FILTER = "pickup_borough IN ('Brooklyn', 'Queens', 'Bronx')"


def _load_data(run_date: str) -> pd.DataFrame:
    query = f"""
        SELECT
            pickup_date,
            pu_location_id,
            pickup_borough,
            service_zone,
            day_of_week,
            trip_count,
            total_revenue,
            total_congestion_fees
        FROM NYC_TLC_DB.GOLD.fct_revenue_daily
        WHERE pickup_date >= '{_PRE_START}'
          AND pickup_date <  '{run_date}'
          AND ({_TREATMENT_FILTER} OR {_CONTROL_FILTER})
        ORDER BY pickup_date, pu_location_id
    """
    df = read_gold(query)
    df.columns = [c.lower() for c in df.columns]
    df["pickup_date"] = pd.to_datetime(df["pickup_date"]).dt.date
    return df


def _assign_groups(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["treated"] = (
        (df["pickup_borough"] == "Manhattan") & (df["service_zone"] == "Yellow Zone")
    ).astype(int)
    df["post"] = (df["pickup_date"] >= _TREATMENT_DATE).astype(int)
    df["post_treated"] = df["post"] * df["treated"]
    return df


def _fit_did(df: pd.DataFrame, outcome: str) -> tuple[float, float, float]:
    """Fit TWFE DiD OLS. Returns (β₃, p_value, r²).

    Zone and day-of-week fixed effects via dummy encoding.
    `treated` main effect excluded — absorbed by zone FEs.
    """
    zone_dummies = pd.get_dummies(df["pu_location_id"], prefix="zone", drop_first=True)
    dow_dummies = pd.get_dummies(df["day_of_week"], prefix="dow", drop_first=True)

    X = pd.concat(
        [df[["post", "post_treated"]], zone_dummies, dow_dummies],
        axis=1,
    ).astype(float)
    X = sm.add_constant(X)
    y = df[outcome].astype(float)

    result = sm.OLS(y, X).fit()
    beta3 = float(result.params["post_treated"])
    p_value = float(result.pvalues["post_treated"])
    r2 = float(result.rsquared)
    return beta3, p_value, r2


def _zone_summaries(df: pd.DataFrame) -> pd.DataFrame:
    """Per-zone, per-period (pre/post) average metrics."""
    return (
        df.groupby(["pu_location_id", "pickup_borough", "service_zone", "treated", "post"])
        .agg(
            avg_trip_count=("trip_count", "mean"),
            avg_revenue=("total_revenue", "mean"),
            avg_congestion_fees=("total_congestion_fees", "mean"),
        )
        .reset_index()
        .assign(period=lambda x: x["post"].map({1: "post", 0: "pre"}))
        .drop(columns=["post"])
        .round({"avg_trip_count": 2, "avg_revenue": 2, "avg_congestion_fees": 4})
    )


def run_did(run_date: str) -> int:
    """Fit DiD model, log to MLflow, write results to Snowflake.

    Returns number of rows written to fct_congestion_pricing_impact.
    """
    setup_tracking()

    df = _load_data(run_date)
    if df.empty:
        raise ValueError(f"No Gold data available before {run_date}")

    df = _assign_groups(df)

    n_treatment = int(df[df["treated"] == 1]["pu_location_id"].nunique())
    n_control = int(df[df["treated"] == 0]["pu_location_id"].nunique())
    pre_end = str(_TREATMENT_DATE - timedelta(days=1))
    post_start = str(_TREATMENT_DATE)
    post_end = str(df["pickup_date"].max())

    print(f"Treatment zones: {n_treatment}, Control zones: {n_control}")
    print(f"Pre  period: {_PRE_START} → {pre_end}")
    print(f"Post period: {post_start} → {post_end}")

    did_trip, p_trip, r2_trip = _fit_did(df, "trip_count")
    did_revenue, p_revenue, r2_revenue = _fit_did(df, "total_revenue")

    print(f"DiD trip_count:   β₃={did_trip:.2f},    p={p_trip:.4f},    R²={r2_trip:.4f}")
    print(f"DiD total_revenue: β₃={did_revenue:.2f}, p={p_revenue:.4f}, R²={r2_revenue:.4f}")

    mlflow.set_experiment(_EXPERIMENT)
    with mlflow.start_run():
        mlflow.set_tag("mlflow.runName", f"did__{run_date}")
        mlflow.log_params({
            "model_type":           "did_ols_twfe",
            "run_date":             run_date,
            "pre_start":            str(_PRE_START),
            "pre_end":              pre_end,
            "post_start":           post_start,
            "post_end":             post_end,
            "n_treatment_zones":    n_treatment,
            "n_control_zones":      n_control,
            "treatment_definition": "Manhattan CBD (pickup_borough=Manhattan, service_zone=Yellow Zone)",
            "control_definition":   "Brooklyn, Queens, Bronx",
            "fixed_effects":        "pu_location_id, day_of_week",
            "outcome_primary":      "trip_count",
            "outcome_secondary":    "total_revenue",
        })
        mlflow.log_metrics({
            "did_estimate":      did_trip,
            "p_value":           p_trip,
            "r_squared":         r2_trip,
            "did_revenue":       did_revenue,
            "p_value_revenue":   p_revenue,
            "r_squared_revenue": r2_revenue,
        })

    summaries = _zone_summaries(df)
    summaries["did_trip_count"] = did_trip
    summaries["did_revenue"] = did_revenue
    summaries["p_value_trip_count"] = p_trip
    summaries["p_value_revenue"] = p_revenue
    summaries["r2_trip_count"] = r2_trip
    summaries["r2_revenue"] = r2_revenue
    summaries["_run_date"] = date.fromisoformat(run_date)

    delete_ml_rows("fct_congestion_pricing_impact", f"_RUN_DATE = '{run_date}'")
    insert_congestion_impact_rows(summaries)

    print(f"Wrote {len(summaries):,} rows to ML.fct_congestion_pricing_impact")
    return len(summaries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-date", required=True, metavar="YYYY-MM-DD")
    args = parser.parse_args()
    run_did(args.run_date)
