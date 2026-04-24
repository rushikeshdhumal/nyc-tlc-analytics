"""Snowflake I/O utilities for ML scripts.

All ML outputs go to NYC_TLC_DB.ML schema (CLAUDE.md §4).
Features are read from NYC_TLC_DB.GOLD schema only — never Silver or Bronze.
"""
from __future__ import annotations

import os
from datetime import date, datetime

import pandas as pd
import snowflake.connector
from snowflake.connector.errors import ProgrammingError
from snowflake.connector.pandas_tools import write_pandas


def _connect() -> snowflake.connector.SnowflakeConnection:
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE", "DE_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "NYC_TLC_DB"),
    )


def read_gold(query: str) -> pd.DataFrame:
    """Execute a SELECT against the Gold schema and return a DataFrame."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)
            return cursor.fetch_pandas_all()


def write_ml_table(
    df: pd.DataFrame,
    table_name: str,
    overwrite: bool = False,
) -> None:
    """Write a DataFrame to NYC_TLC_DB.ML.<table_name>.

    overwrite=True  — truncates the table before writing (full refresh).
    overwrite=False — appends new rows (incremental scoring run).

    Raises RuntimeError if the write fails.
    """
    with _connect() as conn:
        success, nchunks, nrows, _ = write_pandas(
            conn=conn,
            df=df,
            table_name=table_name.upper(),
            schema="ML",
            auto_create_table=False,
            overwrite=overwrite,
        )
    if not success:
        raise RuntimeError(
            f"write_pandas failed writing to ML.{table_name}: "
            f"{nchunks} chunk(s), {nrows} row(s)"
        )


def delete_ml_rows(table_name: str, where_clause: str) -> None:
    """Delete rows from NYC_TLC_DB.ML.<table_name> matching a SQL WHERE clause."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            result = cursor.execute(
                """
                SELECT 1
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = 'ML'
                  AND TABLE_NAME = %s
                LIMIT 1
                """,
                (table_name.upper(),),
            )
            if result is None:
                return
            table_exists = result.fetchone()
            if not table_exists:
                return
            cursor.execute(f"DELETE FROM ML.{table_name.upper()} WHERE {where_clause}")


def insert_congestion_impact_rows(df: pd.DataFrame) -> None:
    """Insert rows into ML.FCT_CONGESTION_PRICING_IMPACT with explicit SQL typing.

    Avoids Parquet/logical-type ambiguity in write_pandas for date columns.
    """
    required_columns = [
        "pu_location_id", "pickup_borough", "service_zone", "period", "treated",
        "avg_trip_count", "avg_revenue", "avg_congestion_fees",
        "did_trip_count", "did_revenue",
        "p_value_trip_count", "p_value_revenue",
        "r2_trip_count", "r2_revenue",
        "_run_date",
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns for congestion impact insert: {missing}")

    run_dates = pd.to_datetime(df["_run_date"], errors="raise").dt.date

    records = list(
        zip(
            df["pu_location_id"].astype("int64").tolist(),
            df["pickup_borough"].astype("object").tolist(),
            df["service_zone"].astype("object").tolist(),
            df["period"].astype("object").tolist(),
            df["treated"].astype(bool).tolist(),
            df["avg_trip_count"].astype("float64").tolist(),
            df["avg_revenue"].astype("float64").tolist(),
            df["avg_congestion_fees"].astype("float64").tolist(),
            df["did_trip_count"].astype("float64").tolist(),
            df["did_revenue"].astype("float64").tolist(),
            df["p_value_trip_count"].astype("float64").tolist(),
            df["p_value_revenue"].astype("float64").tolist(),
            df["r2_trip_count"].astype("float64").tolist(),
            df["r2_revenue"].astype("float64").tolist(),
            list(run_dates),
        )
    )
    if not records:
        return

    sql = """
        INSERT INTO ML.FCT_CONGESTION_PRICING_IMPACT (
            PU_LOCATION_ID, PICKUP_BOROUGH, SERVICE_ZONE, PERIOD, TREATED,
            AVG_TRIP_COUNT, AVG_REVENUE, AVG_CONGESTION_FEES,
            DID_TRIP_COUNT, DID_REVENUE,
            P_VALUE_TRIP_COUNT, P_VALUE_REVENUE,
            R2_TRIP_COUNT, R2_REVENUE,
            _RUN_DATE
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    with _connect() as conn:
        with conn.cursor() as cursor:
            try:
                for i in range(0, len(records), 5000):
                    cursor.executemany(sql, records[i : i + 5000])
            except ProgrammingError:
                for record in records:
                    cursor.execute(sql, record)


def insert_demand_forecast_rows(df: pd.DataFrame) -> None:
    """Insert rows into ML.FCT_DEMAND_FORECAST with explicit SQL typing.

    This avoids Parquet/logical-type ambiguity in write_pandas for timestamp/date
    columns.
    """
    required_columns = [
        "PICKUP_HOUR",
        "PU_LOCATION_ID",
        "PICKUP_BOROUGH",
        "PREDICTED_TRIP_COUNT",
        "MODEL_VERSION",
        "_RUN_DATE",
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns for forecast insert: {missing}")

    pickup_hours = pd.to_datetime(df["PICKUP_HOUR"], errors="raise")
    run_dates = pd.to_datetime(df["_RUN_DATE"], errors="raise").dt.date

    pickup_hour_values: list[datetime] = [ts.to_pydatetime() for ts in pickup_hours]
    run_date_values: list[date] = [d for d in run_dates]

    records = list(
        zip(
            pickup_hour_values,
            df["PU_LOCATION_ID"].astype("int64").tolist(),
            df["PICKUP_BOROUGH"].astype("object").tolist(),
            df["PREDICTED_TRIP_COUNT"].astype("float64").tolist(),
            df["MODEL_VERSION"].astype("object").tolist(),
            run_date_values,
        )
    )
    if not records:
        return

    sql = """
        INSERT INTO ML.FCT_DEMAND_FORECAST (
            PICKUP_HOUR,
            PU_LOCATION_ID,
            PICKUP_BOROUGH,
            PREDICTED_TRIP_COUNT,
            MODEL_VERSION,
            _RUN_DATE
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """

    with _connect() as conn:
        with conn.cursor() as cursor:
            try:
                for i in range(0, len(records), 5000):
                    cursor.executemany(sql, records[i : i + 5000])
            except ProgrammingError:
                # Defensive fallback for connector rewrite edge-cases in executemany.
                for record in records:
                    cursor.execute(sql, record)
