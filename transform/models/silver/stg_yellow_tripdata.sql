-- =============================================================================
-- Silver model: stg_yellow_tripdata
-- =============================================================================
-- Reads from Bronze VARIANT, casts all columns to typed representations,
-- deduplicates on (vendor_id, tpep_pickup_datetime, pu_location_id), and
-- removes trips that fail data quality rules from DATA_LINEAGE_CONTRACTS.md.
--
-- Incremental strategy: on each run only Bronze rows whose _batch_id is
-- greater than the maximum _batch_id already in Silver are processed.
-- _batch_id is YYYY-MM (lexicographic ordering works correctly).
-- First run (or dbt run --full-refresh) processes all Bronze rows.
--
-- Timestamp note: Parquet timestamps land in VARIANT as INT64 microseconds.
-- Use TO_TIMESTAMP_NTZ(::NUMBER, 6) — not ::TIMESTAMP. See DATA_DICTIONARY_YELLOW.md.
-- =============================================================================

{{ config(
    materialized         = 'incremental',
    unique_key           = 'trip_id',
    incremental_strategy = 'merge'
) }}

WITH source AS (

    SELECT
        raw_data,
        _source_file,
        _ingested_at,
        _batch_id
    FROM {{ source('bronze', 'brz_yellow_tripdata') }}
    {% if is_incremental() %}
    WHERE _batch_id > (SELECT MAX(_batch_id) FROM {{ this }})
    {% endif %}

),

casted AS (

    SELECT
        -- Surrogate primary key (dedup key fields)
        MD5(
            CONCAT_WS('|',
                raw_data:VendorID::VARCHAR,
                raw_data:tpep_pickup_datetime::VARCHAR,
                raw_data:PULocationID::VARCHAR
            )
        )                                                           AS trip_id,

        -- Identifiers
        raw_data:VendorID::INT                                      AS vendor_id,
        raw_data:RatecodeID::INT                                    AS rate_code_id,
        raw_data:PULocationID::INT                                  AS pu_location_id,
        raw_data:DOLocationID::INT                                  AS do_location_id,

        -- Timestamps: INT64 microseconds since epoch → TIMESTAMP_NTZ UTC
        TO_TIMESTAMP_NTZ(raw_data:tpep_pickup_datetime::NUMBER, 6)  AS tpep_pickup_datetime,
        TO_TIMESTAMP_NTZ(raw_data:tpep_dropoff_datetime::NUMBER, 6) AS tpep_dropoff_datetime,

        -- Trip metrics
        raw_data:passenger_count::INT                               AS passenger_count,
        raw_data:trip_distance::FLOAT                               AS trip_distance,
        raw_data:store_and_fwd_flag::VARCHAR                        AS store_and_fwd_flag,

        -- Payment
        raw_data:payment_type::INT                                  AS payment_type,
        raw_data:fare_amount::FLOAT                                 AS fare_amount,
        raw_data:extra::FLOAT                                       AS extra,
        raw_data:mta_tax::FLOAT                                     AS mta_tax,
        -- tip_amount is only recorded for credit card payments (payment_type = 1);
        -- nulled out for all other payment types to prevent misleading averages.
        CASE
            WHEN raw_data:payment_type::INT = 1
            THEN raw_data:tip_amount::FLOAT
            ELSE NULL
        END                                                         AS tip_amount,
        raw_data:tolls_amount::FLOAT                                AS tolls_amount,
        raw_data:improvement_surcharge::FLOAT                       AS improvement_surcharge,
        raw_data:congestion_surcharge::FLOAT                        AS congestion_surcharge,
        raw_data:airport_fee::FLOAT                                 AS airport_fee,
        raw_data:cbd_congestion_fee::FLOAT                          AS cbd_congestion_fee,
        raw_data:total_amount::FLOAT                                AS total_amount,

        -- Audit columns (carried through from Bronze)
        _source_file,
        _ingested_at,
        _batch_id

    FROM source

),

deduplicated AS (

    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY vendor_id, tpep_pickup_datetime, pu_location_id
            ORDER BY _ingested_at DESC
        ) AS _row_num
    FROM casted

),

filtered AS (

    SELECT * EXCLUDE (_row_num)
    FROM deduplicated
    WHERE
        _row_num = 1                                        -- keep latest on duplicate
        AND passenger_count > 0                             -- DATA_LINEAGE_CONTRACTS §2
        AND trip_distance > 0
        AND fare_amount > 0
        AND tpep_dropoff_datetime > tpep_pickup_datetime    -- temporal sanity
        AND rate_code_id != 99                              -- exclude unknown rate codes

)

SELECT * FROM filtered
