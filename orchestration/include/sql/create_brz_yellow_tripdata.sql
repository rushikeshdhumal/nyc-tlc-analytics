-- =============================================================================
-- Bronze DDL — brz_yellow_tripdata
-- =============================================================================
-- Schema-on-read: each Parquet row lands in raw_data (VARIANT).
-- _source_file, _ingested_at, _batch_id satisfy DATA_LINEAGE_CONTRACTS.md §2.
-- IDEMPOTENT: CREATE TABLE IF NOT EXISTS — safe to re-run.
-- =============================================================================

CREATE TABLE IF NOT EXISTS NYC_TLC_DB.BRONZE.brz_yellow_tripdata (
    raw_data        VARIANT         NOT NULL,
    _source_file    VARCHAR(512)    NOT NULL,
    _ingested_at    TIMESTAMP_NTZ   NOT NULL DEFAULT SYSDATE(),
    _batch_id       VARCHAR(32)     NOT NULL
)
COMMENT = 'Bronze landing table — raw Yellow Taxi Parquet rows as VARIANT. Source: Azure Blob Storage via NYC_TLC_STAGE.';
