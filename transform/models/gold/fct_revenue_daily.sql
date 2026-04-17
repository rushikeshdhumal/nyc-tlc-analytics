-- =============================================================================
-- Gold model: fct_revenue_daily
-- =============================================================================
-- Grain: one row per (pickup_date × pu_location_id).
-- Pre-collapses fct_revenue_per_zone_hourly by summing across all hours and
-- vendors for a given day + zone. Superset time-series and bar charts query
-- this model instead of the hourly table, reducing rows scanned by ~24×.
--
-- Weighted averages are used for rate metrics so the daily figures are
-- mathematically consistent with the underlying hourly data.
-- =============================================================================

WITH hourly AS (

    SELECT *
    FROM {{ ref('fct_revenue_per_zone_hourly') }}

),

aggregated AS (

    SELECT
        -- Surrogate PK
        MD5(
            CONCAT_WS('|',
                pickup_date::VARCHAR,
                pu_location_id::VARCHAR
            )
        )                                                                   AS fct_id,

        -- Dimensions
        pickup_date,
        day_of_week,
        pu_location_id,
        pickup_borough,
        pickup_zone,
        service_zone,

        -- Volume
        SUM(trip_count)                                                     AS trip_count,
        SUM(total_passengers)                                               AS total_passengers,
        ROUND(SUM(total_passengers) / NULLIF(SUM(trip_count), 0), 2)        AS avg_passengers_per_trip,

        -- Revenue
        ROUND(SUM(total_revenue), 2)                                        AS total_revenue,
        ROUND(SUM(total_fare), 2)                                           AS total_fare,
        ROUND(SUM(total_revenue) / NULLIF(SUM(trip_count), 0), 2)           AS revenue_per_trip,

        -- Distance & efficiency
        ROUND(SUM(total_distance_miles), 2)                                 AS total_distance_miles,
        ROUND(SUM(total_distance_miles) / NULLIF(SUM(trip_count), 0), 2)    AS avg_distance_miles,
        ROUND(SUM(total_revenue) / NULLIF(SUM(total_distance_miles), 0), 2) AS revenue_per_mile,

        -- Duration (weighted average across hourly buckets)
        ROUND(
            SUM(avg_trip_duration_minutes * trip_count) / NULLIF(SUM(trip_count), 0),
        1)                                                                  AS avg_trip_duration_minutes,

        -- Tips (weighted average — NULL hourly buckets excluded by SUM)
        ROUND(
            SUM(avg_tip_pct * trip_count) / NULLIF(SUM(trip_count), 0),
        1)                                                                  AS avg_tip_pct,

        -- Payment mix (weighted average: cc_pct × trips recovers cc trip count)
        ROUND(
            SUM(credit_card_trip_pct * trip_count) / NULLIF(SUM(trip_count), 0),
        1)                                                                  AS credit_card_trip_pct,

        -- 2025 surcharges
        ROUND(SUM(total_congestion_fees), 2)                                AS total_congestion_fees,
        ROUND(SUM(total_airport_fees), 2)                                   AS total_airport_fees

    FROM hourly
    GROUP BY
        pickup_date,
        day_of_week,
        pu_location_id,
        pickup_borough,
        pickup_zone,
        service_zone

)

SELECT * FROM aggregated
