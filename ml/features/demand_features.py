"""Feature extraction for demand forecasting model (Phase 7).

Source  : NYC_TLC_DB.GOLD.fct_revenue_per_zone_hourly
Target  : trip_count per (pickup_hour, pu_location_id)
Contract: .claude/ML_FEATURE_CONTRACTS.md §Model 1
"""
from __future__ import annotations

import pandas as pd

from ml.utils.snowflake_io import read_gold

FEATURE_COLS: list[str] = [
    "hour_of_day",
    "day_of_week_num",
    "month",
    "is_weekend",
    "lag_1h_trip_count",
    "lag_24h_trip_count",
    "lag_168h_trip_count",
    "rolling_24h_avg_trip_count",
    "rolling_168h_avg_trip_count",
    "pu_location_id",
    "pickup_borough_enc",
    "lag_168h_congestion_fees",
]
TARGET_COL = "trip_count"

# Stable mapping used for encoding at train and predict time.
_BOROUGH_MAP: dict[str, int] = {
    "Manhattan": 0,
    "Brooklyn": 1,
    "Queens": 2,
    "Bronx": 3,
    "Staten Island": 4,
    "EWR": 5,
    "Unknown": 6,
}


def build_feature_matrix(
    start_date: str,
    end_date: str,
    lookback_hours: int = 168,
) -> pd.DataFrame:
    """Pull Gold data, engineer lag/rolling features, return sorted DataFrame.

    start_date / end_date: 'YYYY-MM-DD' (inclusive).
    lookback_hours: extra hours pulled before start_date so lag features are
      non-NaN at the first row inside the requested window. Defaults to 168 (1 week).

    Rows where pickup_hour < start_date (the lookback buffer) are dropped after
    feature engineering. The caller should still dropna(subset=FEATURE_COLS) to
    handle any remaining NaNs at zone boundaries.
    """
    query = f"""
        SELECT
            pickup_hour,
            pu_location_id,
            MIN(pickup_borough)         AS pickup_borough,
            HOUR(pickup_hour)           AS hour_of_day,
            SUM(trip_count)             AS trip_count,
            SUM(total_congestion_fees)  AS total_congestion_fees
        FROM NYC_TLC_DB.GOLD.fct_revenue_per_zone_hourly
        WHERE pickup_hour >= DATEADD('hour', -{lookback_hours},
                                      '{start_date}'::TIMESTAMP)
          AND pickup_hour <  DATEADD('day', 1, '{end_date}'::TIMESTAMP)
        GROUP BY pickup_hour, pu_location_id
        ORDER BY pu_location_id, pickup_hour
    """
    df = read_gold(query)
    df.columns = df.columns.str.lower()
    df["pickup_hour"] = pd.to_datetime(df["pickup_hour"])

    df = _engineer_features(df)

    # Drop the lookback buffer rows — lag features are NaN there by design
    cutoff = pd.Timestamp(start_date)
    df = df[df["pickup_hour"] >= cutoff].copy()
    return df.sort_values(["pu_location_id", "pickup_hour"]).reset_index(drop=True)


def _engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values(["pu_location_id", "pickup_hour"])

    # Calendar
    df["day_of_week_num"] = df["pickup_hour"].dt.dayofweek  # 0=Mon … 6=Sun
    df["month"] = df["pickup_hour"].dt.month
    df["is_weekend"] = (df["day_of_week_num"] >= 5).astype(int)

    # Lag and rolling features — grouped per zone to prevent cross-zone leakage
    g_count = df.groupby("pu_location_id")["trip_count"]
    df["lag_1h_trip_count"] = g_count.shift(1)
    df["lag_24h_trip_count"] = g_count.shift(24)
    df["lag_168h_trip_count"] = g_count.shift(168)
    df["rolling_24h_avg_trip_count"] = g_count.transform(
        lambda s: s.shift(1).rolling(24, min_periods=1).mean()
    )
    df["rolling_168h_avg_trip_count"] = g_count.transform(
        lambda s: s.shift(1).rolling(168, min_periods=1).mean()
    )

    # Congestion fees lagged 168h — same-period value is a leakage risk
    df["lag_168h_congestion_fees"] = (
        df.groupby("pu_location_id")["total_congestion_fees"].shift(168)
    )

    df["pickup_borough_enc"] = (
        df["pickup_borough"].map(_BOROUGH_MAP).fillna(6).astype(int)
    )

    return df
