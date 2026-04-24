-- =============================================================================
-- NYC TLC Analytics Pipeline — ML Schema Setup
-- =============================================================================
-- PURPOSE : Creates the ML schema and all ML output tables in NYC_TLC_DB.
--           Run this once before executing any ML training or scoring scripts.
--
-- RUN AS  : DE_ROLE (schema and table ownership)
--
-- IDEMPOTENT: Every statement uses CREATE ... IF NOT EXISTS so this script
--             is safe to re-run.
--
-- Ref     : .claude/CLAUDE.md §4 (ML & MLOps Standards)
--           .claude/ML_FEATURE_CONTRACTS.md (output schemas)
--           .claude/MODULAR_MONOLITH_STRUCTURE.md §3 (schema ownership)
-- =============================================================================

USE ROLE      DE_ROLE;
USE WAREHOUSE COMPUTE_WH;
USE DATABASE  NYC_TLC_DB;


-- ===========================================================================
-- 1. ML SCHEMA
--    Owned by DE_ROLE. All ML script outputs land here.
--    ANALYST_ROLE gets read access so Superset can visualise predictions
--    and anomaly flags.
-- ===========================================================================

CREATE SCHEMA IF NOT EXISTS NYC_TLC_DB.ML
    COMMENT = 'ML outputs — demand forecasts, anomaly flags, causal inference results';

-- ANALYST_ROLE: read-only on ML (for Superset dashboards)
GRANT USAGE  ON SCHEMA NYC_TLC_DB.ML                  TO ROLE ANALYST_ROLE;
GRANT SELECT ON ALL TABLES    IN SCHEMA NYC_TLC_DB.ML TO ROLE ANALYST_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA NYC_TLC_DB.ML TO ROLE ANALYST_ROLE;

USE SCHEMA NYC_TLC_DB.ML;


-- ===========================================================================
-- 2. FCT_DEMAND_FORECAST
--    Written by: ml/models/demand_forecast/predict.py
--    Grain     : pickup_hour × pu_location_id
--    Ref       : PROJECT_PLAN.md Phase 7
-- ===========================================================================

CREATE TABLE IF NOT EXISTS NYC_TLC_DB.ML.FCT_DEMAND_FORECAST (
    PICKUP_HOUR             TIMESTAMP_NTZ   NOT NULL COMMENT 'Hour being forecast (UTC)',
    PU_LOCATION_ID          INTEGER         NOT NULL COMMENT 'TLC taxi zone ID',
    PICKUP_BOROUGH          VARCHAR(50)              COMMENT 'Borough name',
    PREDICTED_TRIP_COUNT    FLOAT           NOT NULL COMMENT 'Model predicted trip count',
    MODEL_VERSION           VARCHAR(50)     NOT NULL COMMENT 'MLflow registered model version',
    _RUN_DATE               DATE            NOT NULL COMMENT 'Date this prediction batch was generated'
);


-- ===========================================================================
-- 3. FCT_ANOMALIES
--    Written by: ml/models/anomaly_detection/score.py
--    Grain     : pickup_date × pu_location_id
--    Ref       : ML_FEATURE_CONTRACTS.md §Model 2
-- ===========================================================================

CREATE TABLE IF NOT EXISTS NYC_TLC_DB.ML.FCT_ANOMALIES (
    ANOMALY_DATE            DATE            NOT NULL COMMENT 'Date being scored',
    PU_LOCATION_ID          INTEGER         NOT NULL COMMENT 'TLC taxi zone ID',
    PICKUP_BOROUGH          VARCHAR(50)              COMMENT 'Borough name',
    TRIP_COUNT              INTEGER         NOT NULL COMMENT 'Actual trip count on this date',
    Z_SCORE                 FLOAT           NOT NULL COMMENT 'Trip count z-score vs rolling 30-day baseline',
    REVENUE_Z_SCORE         FLOAT                    COMMENT 'Revenue z-score vs rolling 30-day baseline',
    IS_ANOMALY              BOOLEAN         NOT NULL COMMENT 'True if z_score > 3.0',
    _SCORED_AT              TIMESTAMP_NTZ   NOT NULL COMMENT 'Timestamp when this row was scored'
);


-- ===========================================================================
-- 4. FCT_CONGESTION_PRICING_IMPACT
--    Written by: ml/models/causal_inference/congestion_pricing_did.py
--    Grain     : pu_location_id × period (pre/post) × _run_date
--    Ref       : ML_FEATURE_CONTRACTS.md §Model 3
--
--    NOTE: Uses CREATE OR REPLACE so re-running this script always applies
--    the current schema. Drop any existing table before re-running if needed.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS NYC_TLC_DB.ML.FCT_CONGESTION_PRICING_IMPACT (
    PU_LOCATION_ID          INTEGER         NOT NULL COMMENT 'TLC taxi zone ID',
    PICKUP_BOROUGH          VARCHAR(50)              COMMENT 'Borough name',
    SERVICE_ZONE            VARCHAR(50)              COMMENT 'Service zone (e.g. Yellow Zone)',
    PERIOD                  VARCHAR(10)     NOT NULL COMMENT 'pre (before 2025-01-05) or post',
    TREATED                 BOOLEAN         NOT NULL COMMENT 'True = Manhattan CBD zone',
    AVG_TRIP_COUNT          FLOAT                    COMMENT 'Average daily trip count in this period',
    AVG_REVENUE             FLOAT                    COMMENT 'Average daily revenue ($) in this period',
    AVG_CONGESTION_FEES     FLOAT                    COMMENT 'Average daily congestion fees ($) in this period',
    DID_TRIP_COUNT          FLOAT                    COMMENT 'DiD β₃ for trip_count — causal demand effect',
    DID_REVENUE             FLOAT                    COMMENT 'DiD β₃ for total_revenue — causal revenue effect',
    P_VALUE_TRIP_COUNT      FLOAT                    COMMENT 'p-value of DiD trip_count estimate',
    P_VALUE_REVENUE         FLOAT                    COMMENT 'p-value of DiD revenue estimate',
    R2_TRIP_COUNT           FLOAT                    COMMENT 'R² of trip_count DiD regression',
    R2_REVENUE              FLOAT                    COMMENT 'R² of revenue DiD regression',
    _RUN_DATE               DATE            NOT NULL COMMENT 'Date this analysis was run'
);


-- ===========================================================================
-- 5. VERIFICATION
-- ===========================================================================

SHOW SCHEMAS IN DATABASE NYC_TLC_DB;
SHOW TABLES  IN SCHEMA  NYC_TLC_DB.ML;
