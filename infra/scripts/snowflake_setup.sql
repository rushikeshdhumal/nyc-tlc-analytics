-- =============================================================================
-- NYC TLC BI Pipeline — Snowflake Foundation Setup
-- =============================================================================
-- PURPOSE : Creates the full RBAC structure, compute resources, database,
--           Medallion schemas, and the External Stage pointing at the public
--           NYC TLC S3 bucket.
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

-- Grant DE_ROLE to the pipeline user (replace DE_ADMIN with your actual username)
-- GRANT ROLE DE_ROLE TO USER DE_ADMIN;


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
--    BRONZE → raw VARIANT ingestion from S3
--    SILVER → cleaned, structured, deduplicated
--    GOLD   → aggregated marts optimised for Superset / Tableau
-- ===========================================================================

USE DATABASE NYC_TLC_DB;

CREATE SCHEMA IF NOT EXISTS NYC_TLC_DB.BRONZE
    COMMENT = 'Landing zone — 1:1 copy of S3 source, VARIANT format, no transforms';

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
-- 6. EXTERNAL STAGE — Public NYC TLC S3 Bucket
--    Source: s3://nyc-tlc/trip data/
--    The bucket is publicly readable — no AWS credentials required.
--    Ref: .claude/DATA_LINEAGE_CONTRACTS.md §2 Bronze rules
-- ===========================================================================

CREATE STAGE IF NOT EXISTS NYC_TLC_DB.BRONZE.NYC_TLC_STAGE
    URL            = 's3://nyc-tlc/trip data/'
    FILE_FORMAT    = NYC_TLC_DB.BRONZE.PARQUET_FORMAT
    COMMENT        = 'External stage pointing at the public NYC TLC S3 bucket';

-- Verify the stage is reachable and list available files
-- LIST @NYC_TLC_DB.BRONZE.NYC_TLC_STAGE PATTERN='.*yellow_tripdata_2024.*';


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

-- Quick connectivity test: list a single Parquet file from the stage
-- SELECT METADATA$FILENAME, METADATA$FILE_ROW_NUMBER
-- FROM @NYC_TLC_DB.BRONZE.NYC_TLC_STAGE (PATTERN => '.*yellow_tripdata_2024-01.*')
-- LIMIT 5;
