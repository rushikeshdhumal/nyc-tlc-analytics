-- =============================================================================
-- Gold model: fct_revenue_per_zone_hourly
-- =============================================================================
-- Grain: one row per (pickup_hour × pu_location_id × vendor_id).
-- Joins with taxi_zone_lookup (dbt seed) for human-readable zone names.
-- Excludes payment_type 3 (No Charge), 4 (Dispute), 6 (Void) from revenue.
-- tip_amount is already NULL for non-credit-card rows in Silver.
-- =============================================================================

WITH silver AS (

    SELECT
        DATE_TRUNC('HOUR', tpep_pickup_datetime)    AS pickup_hour,
        pu_location_id,
        vendor_id,
        payment_type,
        passenger_count,
        fare_amount,
        tip_amount,
        total_amount,
        trip_distance,
        cbd_congestion_fee,
        airport_fee,
        tpep_pickup_datetime,
        tpep_dropoff_datetime
    FROM {{ ref('stg_yellow_tripdata') }}
    WHERE payment_type NOT IN (3, 4, 6)     -- exclude no-charge, dispute, void

),

zones AS (

    SELECT
        LocationID,
        Borough         AS pickup_borough,
        Zone            AS pickup_zone,
        service_zone
    FROM {{ ref('taxi_zone_lookup') }}

),

aggregated AS (

    SELECT
        -- Surrogate PK
        MD5(
            CONCAT_WS('|',
                s.pickup_hour::VARCHAR,
                s.pu_location_id::VARCHAR,
                s.vendor_id::VARCHAR
            )
        )                                                               AS fct_id,

        -- Dimensions
        s.pickup_hour,
        s.pu_location_id,
        s.vendor_id,
        z.pickup_borough,
        z.pickup_zone,
        z.service_zone,

        -- Volume
        COUNT(*)                                                        AS trip_count,
        SUM(s.passenger_count)                                          AS total_passengers,
        AVG(s.passenger_count)                                          AS avg_passengers_per_trip,

        -- Revenue
        SUM(s.total_amount)                                             AS total_revenue,
        SUM(s.fare_amount)                                              AS total_fare,
        SUM(s.total_amount) / NULLIF(COUNT(*), 0)                       AS revenue_per_trip,

        -- Distance & efficiency
        SUM(s.trip_distance)                                            AS total_distance_miles,
        AVG(s.trip_distance)                                            AS avg_distance_miles,
        SUM(s.total_amount) / NULLIF(SUM(s.trip_distance), 0)           AS revenue_per_mile,

        -- Duration
        AVG(
            DATEDIFF('minute', s.tpep_pickup_datetime, s.tpep_dropoff_datetime)
        )                                                               AS avg_trip_duration_minutes,

        -- Tips (credit card trips only — NULL rows excluded by AVG automatically)
        AVG(
            CASE
                WHEN s.tip_amount IS NOT NULL AND s.fare_amount > 0
                THEN (s.tip_amount / s.fare_amount) * 100.0
                ELSE NULL
            END
        )                                                               AS avg_tip_pct,

        -- Payment mix
        SUM(CASE WHEN s.payment_type = 1 THEN 1 ELSE 0 END)
            * 100.0 / NULLIF(COUNT(*), 0)                               AS credit_card_trip_pct,

        -- 2025 surcharges (CBD congestion pricing + airport fees)
        SUM(COALESCE(s.cbd_congestion_fee, 0))                          AS total_congestion_fees,
        SUM(COALESCE(s.airport_fee, 0))                                 AS total_airport_fees

    FROM silver AS s
    LEFT JOIN zones AS z
        ON s.pu_location_id = z.LocationID
    GROUP BY
        s.pickup_hour,
        s.pu_location_id,
        s.vendor_id,
        z.pickup_borough,
        z.pickup_zone,
        z.service_zone

)

SELECT * FROM aggregated
