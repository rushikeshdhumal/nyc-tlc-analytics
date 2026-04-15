# Data Lineage & Medallion Contracts

## 1. The Medallion Standard
This project strictly follows the Medallion Architecture to ensure data reliability and traceability.


| Layer | Name | Format | Responsibility |
| :--- | :--- | :--- | :--- |
| **Bronze** | `RAW_TLC` | VARIANT (JSON/Parquet) | 1:1 copy of S3 source. No transformations. Includes `_ingested_at` metadata. |
| **Silver** | `CLEANED_TLC` | Relational (Structured) | Type casting, deduplication, and filtering. Data is "cleaned" but not yet aggregated. |
| **Gold** | `MART_TLC` | Relational (Aggregated) | Business-level logic. Joins and aggregations optimized for Superset/Tableau performance. |

## 2. Layer Definitions & Rules

### Bronze (The Landing Zone)
- **Source**: `s3://nyc-tlc/trip data/` via Snowflake External Stage.
- **Rule**: Data is loaded into a single `VARIANT` column to prevent pipeline failure if the source schema changes.
- **Audit**: Every row must have `_source_file_name` and `_ingested_at`.

### Silver (The Trusted Zone)
- **Deduplication**: Use `pickup_datetime`, `vendor_id`, and `pulocationid` to ensure no duplicate trips exist.
- **Filtering**: 
    - Remove trips with `passenger_count = 0`.
    - Remove trips with `trip_distance <= 0`.
    - Remove trips with invalid `fare_amount` (must be > 0).
- **Standards**: All column names must be `lower_snake_case`. Timestamps must be in `UTC`.

### Gold (The Analytics Zone)
- **Grain**: Aggregated by `hour`, `pickup_zone`, and `vendor`.
- **Enrichment**: Must join with `taxi_zone_lookup` to provide human-readable neighborhood names (e.g., "Upper West Side" instead of "Zone 230").
- **Final Metrics**: Must include `total_revenue`, `avg_tip_percentage`, and `trip_count`.

## 3. Quality Assurance (The Contract)
- **Primary Keys**: Every Silver and Gold model must have a tested unique, non-null primary key.
- **Tests**: Every dbt run must be followed by `dbt test`. If a test fails in Silver, the Gold layer must not be updated (preventing bad data from hitting dashboards).