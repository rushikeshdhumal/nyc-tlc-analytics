# NYC Taxi Intelligence Hub

**Release:** v2.0.0
**Export date:** 2026-04-28
**Artifact:** nyc_taxi_demand_revenue_analytics__v2.0.0__2026-04-28.zip

## Overview

Major revision of the v1.0.0 demand & revenue dashboard. This release promotes the dashboard to a full **Intelligence Hub** with three analytical layers: fleet economics KPIs, zone-level density and borough breakdowns, and a congestion policy impact view. The title header includes a markdown banner — *"Strategic Monitoring of 2025 Congestion Policies & Fleet Economics"* — establishing the executive framing.

Both Gold datasets are used: `GOLD.fct_revenue_daily` drives KPI and zone/borough charts; `GOLD.fct_revenue_per_zone_hourly` drives the vendor and heatmap charts.

## Changes from v1.0.0

| Area | v1.0.0 | v2.0.0 |
|---|---|---|
| Dashboard title | NYC Taxi Demand & Revenue Analytics | NYC Taxi Intelligence Hub |
| Charts | 10 | 10 (redesigned set) |
| Congestion fee KPI | Not present | Added (`TOTAL_CONGESTION_FEES`, filtered `>= 2025-01-01`) |
| Congestion policy trend | Not present | Added (mixed time-series with event annotation) |
| Sunburst drill-down | Not present | Added (Service Zone → Borough hierarchy) |
| Revenue Density table | Not present | Added (zone-level trip count, $/mile, tip %) |
| Monthly trend charts | 2 separate | Replaced by Avg Revenue/Mile & Tip % by Borough bar chart |
| Vendor chart | Revenue by Vendor | Vendor Efficiency Comparison (avg revenue/trip + avg duration) |
| Borough avg tip % | Separate chart | Merged into borough efficiency chart |
| Dashboard markdown | None | Header banner row added |

## Dashboard Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ## NYC Taxi Intelligence Hub  (markdown banner, full width) │
├────────────┬────────────────────────────────────────────────┤
│ Vendor     │  Revenue by Zone & Borough                      │
│ Efficiency │  (Sunburst — Service Zone → Borough)           │
│ Comparison │                                                  │
├──────┬─────┴──────────────────────────────┬─────────────────┤
│ Total │ Trip   │ Congestion │ Average Tip │  (KPI row, w=3  │
│Revenue│ Count  │ Fees       │ %           │   each)         │
├───────┴────────┴────────────┴─────────────┴─────────────────┤
│ Congestion Fee Policy Impact on Demand  │  Revenue by       │
│ (mixed time-series with event line)     │  Time & Day       │
│                                         │  (heatmap)        │
├─────────────────────────────────────────┴─────────────────┤
│ Avg Revenue/Mile & Tip % by Borough   │ Revenue Density   │
│ (grouped bar, by borough)              │ by Zone (table)   │
└────────────────────────────────────────┴──────────────────┘
```

## Charts

### Row 1 — Header
- **Markdown banner**: "NYC Taxi Intelligence Hub / Strategic Monitoring of 2025 Congestion Policies & Fleet Economics"

### Row 2 — Fleet & Zone Overview
| Chart | Type | Dataset | Key Metrics / Dimensions |
|---|---|---|---|
| Vendor Efficiency Comparison | Grouped bar | `fct_revenue_per_zone_hourly` | `avg_revenue_per_trip`, `avg_trip_duration` by `VENDOR_NAME` |
| Revenue by Zone & Borough | Sunburst | `fct_revenue_daily` | Hierarchy: `SERVICE_ZONE` → `PICKUP_BOROUGH` |

### Row 3 — KPI Strip
| Chart | Type | Dataset | Metric | Notes |
|---|---|---|---|---|
| Total Revenue | Big Number | `fct_revenue_daily` | `TOTAL_REVENUE` | Respects global time filter |
| Trip Count | Big Number | `fct_revenue_daily` | `TRIP_COUNT` | Respects global time filter |
| Congestion Fees | Big Number | `fct_revenue_daily` | `TOTAL_CONGESTION_FEES` | Hard-coded filter `PICKUP_DATE >= 2025-01-01` |
| Average Tip % | Big Number | `fct_revenue_daily` | `AVG_TIP_PCT` | Respects global time filter |

### Row 4 — Policy & Temporal Analysis
| Chart | Type | Dataset | Key Config |
|---|---|---|---|
| Congestion Fee Policy Impact on Demand | Mixed time-series | `fct_revenue_daily` | Metric: `total_trip_count`; event annotation layer (dashed line, id=1) marks policy effective date |
| Revenue by Time & Day | Heatmap | `fct_revenue_per_zone_hourly` | X: hour of day, Y: day of week; source column: `PICKUP_HOUR` |

### Row 5 — Borough & Zone Drilldown
| Chart | Type | Dataset | Key Config |
|---|---|---|---|
| Avg Revenue/Mile & Tip % by Borough | Grouped bar | `fct_revenue_daily` | Metrics: `avg_revenue_per_mile`, `tip_pct`; X: `PICKUP_BOROUGH` |
| Revenue Density by Zone | Table | `fct_revenue_daily` | Metrics: `total_trip_count`, `avg_revenue_per_mile`, `tip_pct`; Group by: `PICKUP_ZONE` |

## Required Data and Configuration

- Superset database connection to Snowflake `NYC_TLC_DB`
- Datasets from two Gold tables:
  - `GOLD.fct_revenue_daily` — KPI strip, zone/borough charts, policy trend, density table
  - `GOLD.fct_revenue_per_zone_hourly` — vendor efficiency, heatmap
- Supporting seed loaded via `dbt seed`:
  - `silver.taxi_zone_lookup` (zone names and borough mapping)
- **Congestion Fees KPI**: requires `TOTAL_CONGESTION_FEES` column in `fct_revenue_daily` — available after the Phase 8 dbt model update

## Event Annotation Setup

The **Congestion Fee Policy Impact on Demand** chart uses a native Superset event annotation (id=1, dashed line). Before importing:

1. Create a Native Annotation Layer in Superset (`Manage > Annotation Layers`).
2. Add an event annotation for `2025-01-05` (NYC Congestion Pricing effective date).
3. After importing the ZIP, open the chart and connect the annotation layer.

The annotation renders as a dashed vertical line marking the policy change, splitting the time-series into pre- and post-treatment periods for visual inspection.

## Import Notes

- Import via `Dashboards > Import dashboard` in Superset.
- If dataset UUIDs differ in the target environment, re-link the two datasets (`fct_revenue_daily`, `fct_revenue_per_zone_hourly`) after import.
- Verify the default time range and filter scoping across all charts after import.
- The Congestion Fees KPI has a hard-coded `PICKUP_DATE >= 2025-01-01` filter — intentional; do not remove.

## Assumptions

- Gold and Silver dbt models have been built successfully in the target environment.
- `TOTAL_CONGESTION_FEES` is present in `fct_revenue_daily` (requires Phase 8 schema).
- `taxi_zone_lookup` is present and valid in the Silver schema.
- Congestion Pricing effective date (`2025-01-05`) is used as the annotation event boundary.

## Maintenance Guidance

- Bump version for structural changes (chart additions, removals, filter changes, dataset schema changes).
- Use patch releases for label, color, or formatting-only changes.
- Keep this notes file and the ZIP artifact together in `viz/superset/` for traceability.
- The v1.0.0 ZIP and notes are retained for rollback reference.
