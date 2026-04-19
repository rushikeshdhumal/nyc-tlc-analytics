"""Snowflake I/O utilities for ML scripts.

All ML outputs go to NYC_TLC_DB.ML schema (CLAUDE.md §4).
Features are read from NYC_TLC_DB.GOLD schema only — never Silver or Bronze.
"""
from __future__ import annotations

import os

import pandas as pd
import snowflake.connector
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
        return pd.read_sql(query, conn)


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
            auto_create_table=True,
            overwrite=overwrite,
        )
    if not success:
        raise RuntimeError(
            f"write_pandas failed writing to ML.{table_name}: "
            f"{nchunks} chunk(s), {nrows} row(s)"
        )
