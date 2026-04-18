# NYC Taxi Demand & Revenue Analytics

**Release:** v1.0.0
**Export date:** 2026-04-18
**Artifact:** nyc_taxi_demand_revenue_analytics__v1.0.0__2026-04-18.zip

## Overview

This dashboard provides a Gold-layer view of NYC TLC taxi activity for operational and executive analysis. It is designed to summarize revenue, demand, zone performance, and payment behavior using the `NYC_TLC_DB.GOLD.fct_revenue_per_zone_hourly` model.

## Included Visuals

- Total Revenue KPI
- Trip Count KPI
- Avg Revenue per Trip KPI
- Average Tip % KPI
- Monthly Revenue Trend
- Monthly Trip Volume
- Revenue Share by Borough
- Revenue by Vendor
- Avg Tip % by Borough
- Revenue by Day of Week

## Required Data and Configuration

- Superset database connection to Snowflake `NYC_TLC_DB`
- Dataset sourced from `GOLD.fct_revenue_per_zone_hourly`
- Supporting reference data loaded through `dbt seed`:
  - `silver.taxi_zone_lookup`

## Assumptions

- Gold and Silver dbt models have already been built successfully.
- `taxi_zone_lookup` is present and valid in the target Snowflake environment.
- Dashboard filters are configured for interactive drill-down across all charts.

## Import Notes

- Import the ZIP artifact in Superset through `Dashboards > Import dashboard`.
- If dataset or chart identifiers differ in the target environment, reconnect the imported dashboard to the corresponding Snowflake dataset.
- After import, verify the default time range, chart time grain, and filter scoping.

## Maintenance Guidance

- Bump the version for any structural dashboard change, such as chart additions, removals, or filter changes.
- Use patch releases for formatting, label, or color adjustments that do not alter dashboard semantics.
- Keep this note and the ZIP artifact together under `viz/superset` for traceability.