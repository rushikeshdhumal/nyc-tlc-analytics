-- =============================================================================
-- COPY INTO — brz_yellow_tripdata (Bronze layer)
-- =============================================================================
-- Jinja placeholders substituted by the Airflow DAG at runtime:
--   {{ batch_id }}   — YYYY-MM string, e.g. '2025-01'
--   {{ pattern }}    — regex scoped to the target month,
--                      e.g. '.*yellow_tripdata_2025-01\\.parquet'
--
-- IDEMPOTENCY: Snowflake tracks loaded files in the load history. Re-running
-- this statement for the same stage path is a no-op (files are not reloaded
-- unless FORCE = TRUE, which must never be used outside of a manual hotfix).
--
-- Note: MATCH_BY_COLUMN_NAME is intentionally omitted. It is incompatible with
-- copy transforms (SELECT subqueries). Column mapping is explicit in the SELECT.
-- =============================================================================

COPY INTO NYC_TLC_DB.BRONZE.brz_yellow_tripdata (
    raw_data,
    _source_file,
    _ingested_at,
    _batch_id
)
FROM (
    SELECT
        $1                              AS raw_data,
        METADATA$FILENAME               AS _source_file,
        SYSDATE()                       AS _ingested_at,
        '{{ batch_id }}'                AS _batch_id
    FROM @NYC_TLC_DB.BRONZE.NYC_TLC_STAGE
)
PATTERN     = '{{ pattern }}'
FILE_FORMAT = (FORMAT_NAME = 'NYC_TLC_DB.BRONZE.PARQUET_FORMAT')
ON_ERROR    = 'ABORT_STATEMENT';
