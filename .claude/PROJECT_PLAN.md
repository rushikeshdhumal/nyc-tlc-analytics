# NYC TLC BI Pipeline: Project Plan

## Phase 1: Environment & Snowflake Foundation
- [ ] Initialize local development with Docker (Airflow & Apache Superset).
- [ ] Set up Snowflake account and RBAC (Roles: DE_ROLE, ANALYST_ROLE).
- [ ] Create Snowflake External Stage pointing to `s3://nyc-tlc/trip data/`.
- [ ] Verify connection by querying metadata from the public S3 bucket.

## Phase 2: Ingestion & Bronze Layer (Raw)
- [ ] Create Airflow DAG `ingest_nyc_taxi_raw` using SnowflakeOperator.
- [ ] Implement `COPY INTO` logic for Yellow Taxi Parquet files.
- [ ] Validate Bronze tables for schema-on-read performance and VARIANT data handling.

## Phase 3: Transformation & Medallion Architecture (dbt)
- [ ] Initialize dbt project within the repository.
- [ ] **Silver Layer**: Clean data (filter nulls, invalid distances < 0, fare > 0).
- [ ] **Gold Layer**: Create aggregated Marts (e.g., `revenue_per_zone_hourly`).
- [ ] Implement `dbt test` for unique keys and relationship integrity.

## Phase 4: Orchestration & Quality
- [ ] Integrate dbt into Airflow using **Astronomer Cosmos**.
- [ ] Set up data quality sensors to fail the pipeline if Silver layer tests fail.
- [ ] Configure automatic "Monthly Ingestion" triggers based on TLC release schedule.

## Phase 5: Visualization & Serving
- [ ] Connect Apache Superset/Tableau to Snowflake Gold tables.
- [ ] Build interactive Dashboard: "NYC Taxi Demand & Revenue Analytics."
- [ ] Finalize README.md with system architecture diagram and GIF of the dashboard.