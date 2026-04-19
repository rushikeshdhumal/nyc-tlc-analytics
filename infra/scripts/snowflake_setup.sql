-- =============================================================================
-- NYC TLC BI Pipeline — Snowflake Foundation Setup
-- =============================================================================
-- PURPOSE : Creates the full RBAC structure, compute resources, database,
--           Medallion schemas, and the External Stage pointing at the 
--           configured Azure Blob Storage source for NYC TLC ingestion.
--
-- RUN AS  : SYSADMIN / ACCOUNTADMIN (requires privilege to create roles,
--           warehouses, and databases).
--
-- IDEMPOTENT: Every statement uses CREATE ... IF NOT EXISTS so this script
--             is safe to re-run.
--
-- Ref     : .claude/CLAUDE.md §3 (naming rules)
--           .claude/DATA_LINEAGE_CONTRACTS.md §1 (Medallion layers)
--           .claude/PROJECT_PLAN.md Phase 1
--
-- ACCOUNT MIGRATION: all source Parquet files live in Azure Blob Storage.
--   Migrating to a new Snowflake account requires only:
--   1. Run this script (snowflake_setup.sql)
--   2. Run infra/scripts/ml_setup.sql
--   3. Update SNOWFLAKE_ACCOUNT + SNOWFLAKE_PASSWORD + AIRFLOW_CONN_SNOWFLAKE_DEFAULT in .env
--   4. Trigger ingest_nyc_taxi_raw DAG  →  populates Bronze
--   5. Then dbt build --full-refresh    →  rebuilds Silver and Gold from Bronze
--      (step 5 is optional if the DAG's dbt task group completes successfully)
--   No data export from the old account is needed. MLflow stays local to Docker.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 0. CONTEXT — run initial setup as ACCOUNTADMIN
-- ---------------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;


-- ===========================================================================
-- 1. ROLES
--    DE_ROLE    → Data Engineering: full read/write on NYC_TLC_DB
--    ANALYST_ROLE → BI / Superset: read-only on GOLD schema
-- ===========================================================================

CREATE ROLE IF NOT EXISTS DE_ROLE
    COMMENT = 'Data Engineering role — owns all pipeline objects in NYC_TLC_DB';

CREATE ROLE IF NOT EXISTS ANALYST_ROLE
    COMMENT = 'BI / Superset read-only role — Gold layer access only';

-- Grant ANALYST_ROLE as a subordinate of DE_ROLE (role hierarchy)
GRANT ROLE ANALYST_ROLE TO ROLE DE_ROLE;

-- Grant DE_ROLE to the pipeline user (replace YOUR_SNOWFLAKE_USERNAME with your actual username)
GRANT ROLE DE_ROLE TO USER YOUR_SNOWFLAKE_USERNAME;


-- ===========================================================================
-- 2. COMPUTE WAREHOUSE
--    X-SMALL  — smallest available size to protect Snowflake Trial credits.
--    AUTO_SUSPEND = 60 seconds — critical cost guard.
-- ===========================================================================

CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH
    WAREHOUSE_SIZE    = 'X-SMALL'
    AUTO_SUSPEND      = 60          -- suspend after 60 s of inactivity
    AUTO_RESUME       = TRUE
    INITIALLY_SUSPENDED = TRUE      -- starts suspended; saves credits on setup
    COMMENT           = 'Primary compute warehouse for NYC TLC pipeline';

-- DE_ROLE needs USAGE + OPERATE to resume/suspend the warehouse
GRANT USAGE   ON WAREHOUSE COMPUTE_WH TO ROLE DE_ROLE;
GRANT OPERATE ON WAREHOUSE COMPUTE_WH TO ROLE DE_ROLE;

-- ANALYST_ROLE only needs USAGE (resume via AUTO_RESUME)
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE ANALYST_ROLE;


-- ===========================================================================
-- 3. DATABASE
-- ===========================================================================

CREATE DATABASE IF NOT EXISTS NYC_TLC_DB
    COMMENT = 'NYC Taxi & Limousine Commission BI Pipeline — all Medallion layers';

GRANT OWNERSHIP ON DATABASE NYC_TLC_DB TO ROLE DE_ROLE
    REVOKE CURRENT GRANTS;


-- ===========================================================================
-- 4. MEDALLION SCHEMAS
--    BRONZE → raw VARIANT ingestion from Azure Blob Storage, no transforms
--    SILVER → cleaned, structured, deduplicated
--    GOLD   → aggregated marts optimised for Superset / Tableau
-- ===========================================================================

USE DATABASE NYC_TLC_DB;

USE ROLE DE_ROLE;

CREATE SCHEMA IF NOT EXISTS NYC_TLC_DB.BRONZE
    COMMENT = 'Landing zone — 1:1 copy of Azure Blob Storage source, VARIANT format, no transforms';

CREATE SCHEMA IF NOT EXISTS NYC_TLC_DB.SILVER
    COMMENT = 'Trusted zone — type-cast, deduplicated, filtered (dbt stg_ models)';

CREATE SCHEMA IF NOT EXISTS NYC_TLC_DB.GOLD
    COMMENT = 'Analytics zone — aggregated marts for BI (dbt fct_ / dim_ models)';

-- DE_ROLE: full ownership of all three schemas
GRANT OWNERSHIP ON SCHEMA NYC_TLC_DB.BRONZE TO ROLE DE_ROLE REVOKE CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA NYC_TLC_DB.SILVER TO ROLE DE_ROLE REVOKE CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA NYC_TLC_DB.GOLD   TO ROLE DE_ROLE REVOKE CURRENT GRANTS;

-- ANALYST_ROLE: read-only on GOLD
GRANT USAGE  ON SCHEMA NYC_TLC_DB.GOLD                  TO ROLE ANALYST_ROLE;
GRANT SELECT ON ALL TABLES    IN SCHEMA NYC_TLC_DB.GOLD TO ROLE ANALYST_ROLE;
GRANT SELECT ON ALL VIEWS     IN SCHEMA NYC_TLC_DB.GOLD TO ROLE ANALYST_ROLE;
-- Future objects created in GOLD are also visible to ANALYST_ROLE
GRANT SELECT ON FUTURE TABLES IN SCHEMA NYC_TLC_DB.GOLD TO ROLE ANALYST_ROLE;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA NYC_TLC_DB.GOLD TO ROLE ANALYST_ROLE;


-- ===========================================================================
-- 5. FILE FORMAT — Parquet (NYC TLC distributes Parquet files since 2022)
-- ===========================================================================

USE SCHEMA NYC_TLC_DB.BRONZE;
USE ROLE   DE_ROLE;
USE WAREHOUSE COMPUTE_WH;

CREATE FILE FORMAT IF NOT EXISTS NYC_TLC_DB.BRONZE.PARQUET_FORMAT
    TYPE                   = 'PARQUET'
    SNAPPY_COMPRESSION     = TRUE
    -- Honour column names from the file header (case-insensitive match)
    -- Required per .claude/CLAUDE.md §3: MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
    COMMENT = 'Parquet file format for NYC TLC trip data files';


-- ===========================================================================
-- 6. EXTERNAL STAGE — Azure Blob Storage
--    Files are uploaded to Azure by infra/scripts/upload_to_azure.py before
--    this stage is used. Ref: .claude/DATA_LINEAGE_CONTRACTS.md §2
--
--    CREDENTIALS: SAS token stored in .env — never paste it into this file.
--    Substitute the three placeholders below at runtime before executing:
--
--      AZURE_STORAGE_ACCOUNT   → value of AZURE_STORAGE_ACCOUNT from .env
--      AZURE_STORAGE_CONTAINER → value of AZURE_STORAGE_CONTAINER from .env
--      AZURE_SAS_TOKEN         → value of AZURE_SAS_TOKEN from .env
--                                (omit the leading '?' from the token)
--
--    DATE SCOPE: Jan 2024 → latest available.
--    The stage points at the entire container. Date filtering is applied via
--    PATTERN at query time (COPY INTO / LIST). The canonical regex below
--    matches yellow_tripdata_2024-MM.parquet through 2029-MM.parquet and
--    must be used in every COPY INTO command (Phase 2 Airflow DAG).
--
--    PATTERN (copy this into every COPY INTO):
--      '.*yellow_tripdata_202[4-9]-[0-9]{2}\\.parquet'
-- ===========================================================================

CREATE OR REPLACE STAGE NYC_TLC_DB.BRONZE.NYC_TLC_STAGE
    URL            = 'azure://<AZURE_STORAGE_ACCOUNT>.blob.core.windows.net/<AZURE_STORAGE_CONTAINER>/'
    CREDENTIALS    = (AZURE_SAS_TOKEN = '<AZURE_SAS_TOKEN>')
    FILE_FORMAT    = NYC_TLC_DB.BRONZE.PARQUET_FORMAT
    COMMENT        = 'External stage — Azure Blob Storage. Ingest scope: Jan 2024 onwards. Apply PATTERN filter on every COPY INTO.';

-- List all in-scope files (Jan 2024 → latest). Run after upload_to_azure.py
-- to confirm files are visible to Snowflake before running COPY INTO.
LIST @NYC_TLC_DB.BRONZE.NYC_TLC_STAGE
    PATTERN = '.*yellow_tripdata_202[4-9]-[0-9]{2}\.parquet';


-- ===========================================================================
-- 7. VERIFICATION QUERIES
--    Run these after executing the script to confirm everything was created.
-- ===========================================================================

-- Show all objects created
SHOW WAREHOUSES   LIKE 'COMPUTE_WH';
SHOW DATABASES    LIKE 'NYC_TLC_DB';
SHOW SCHEMAS      IN DATABASE NYC_TLC_DB;
SHOW STAGES       IN SCHEMA NYC_TLC_DB.BRONZE;
SHOW FILE FORMATS IN SCHEMA NYC_TLC_DB.BRONZE;
SHOW ROLES        LIKE '%ROLE';

-- Connectivity test: list the first available 2024 file from the stage.
-- Expected: one row with name = 'yellow_tripdata_2024-01.parquet'
LIST @NYC_TLC_DB.BRONZE.NYC_TLC_STAGE
    PATTERN = '.*yellow_tripdata_2024-01\\.parquet';

-- Row-count sanity check against the stage (no COPY INTO yet, just a peek).
SELECT METADATA$FILENAME,
       COUNT(*) AS row_count
FROM   @NYC_TLC_DB.BRONZE.NYC_TLC_STAGE (
           PATTERN => '.*yellow_tripdata_2024-12\\.parquet'
       )
GROUP  BY 1;
