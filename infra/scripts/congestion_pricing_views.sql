-- =============================================================================
-- Congestion Pricing DiD — Superset Presentation Views
-- =============================================================================
-- PURPOSE : Provide clean, pre-aggregated views over ML.FCT_CONGESTION_PRICING_IMPACT
--           for the Congestion Pricing Impact dashboard in Superset.
--
-- RUN AS  : DE_ROLE
-- IDEMPOTENT: CREATE OR REPLACE is safe to re-run.
--
-- Views created:
--   1. V_CONGESTION_DID_BETA_SERIES   — one row per _run_date, DiD β₃ over time
--   2. V_CONGESTION_BOROUGH_SUMMARY   — borough × period × run_date aggregates
-- =============================================================================

USE ROLE      DE_ROLE;
USE WAREHOUSE COMPUTE_WH;
USE DATABASE  NYC_TLC_DB;
USE SCHEMA    ML;

-- ---------------------------------------------------------------------------
-- 1. V_CONGESTION_DID_BETA_SERIES
--    Grain : one row per _run_date (one DiD run)
--    Use   : "Treatment effect over time" line chart (β₃ as post-treatment
--            window grows each month).
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW NYC_TLC_DB.ML.V_CONGESTION_DID_BETA_SERIES AS
SELECT DISTINCT
    _RUN_DATE               AS run_date,
    DID_TRIP_COUNT          AS beta_trip_count,
    DID_REVENUE             AS beta_revenue,
    P_VALUE_TRIP_COUNT      AS p_value_trip_count,
    P_VALUE_REVENUE         AS p_value_revenue,
    R2_TRIP_COUNT           AS r2_trip_count,
    R2_REVENUE              AS r2_revenue
FROM NYC_TLC_DB.ML.FCT_CONGESTION_PRICING_IMPACT
ORDER BY run_date;


-- ---------------------------------------------------------------------------
-- 2. V_CONGESTION_BOROUGH_SUMMARY
--    Grain : pickup_borough × period (pre/post) × _run_date
--    Use   : "Pre/Post avg trip count by borough" grouped bar chart.
--            Filter to the latest _run_date for point-in-time view.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW NYC_TLC_DB.ML.V_CONGESTION_BOROUGH_SUMMARY AS
SELECT
    PICKUP_BOROUGH          AS borough,
    PERIOD                  AS period,
    TREATED                 AS is_treated,
    _RUN_DATE               AS run_date,
    SUM(AVG_TRIP_COUNT)     AS total_avg_daily_trips,
    SUM(AVG_REVENUE)        AS total_avg_daily_revenue,
    AVG(DID_TRIP_COUNT)     AS did_beta_trip_count,
    AVG(P_VALUE_TRIP_COUNT) AS did_p_value
FROM NYC_TLC_DB.ML.FCT_CONGESTION_PRICING_IMPACT
GROUP BY
    PICKUP_BOROUGH, PERIOD, TREATED, _RUN_DATE
ORDER BY
    PICKUP_BOROUGH, PERIOD;


-- ---------------------------------------------------------------------------
-- Grant read access to ANALYST_ROLE for Superset
-- ---------------------------------------------------------------------------

GRANT SELECT ON NYC_TLC_DB.ML.V_CONGESTION_DID_BETA_SERIES  TO ROLE ANALYST_ROLE;
GRANT SELECT ON NYC_TLC_DB.ML.V_CONGESTION_BOROUGH_SUMMARY  TO ROLE ANALYST_ROLE;

SHOW VIEWS IN SCHEMA NYC_TLC_DB.ML;
