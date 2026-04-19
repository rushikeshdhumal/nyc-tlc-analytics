# NYC TLC Data Quality Notes

Known data quality issues in the NYC Yellow Taxi dataset and how the pipeline
handles them. Captured here so future maintainers understand why the Silver
filters exist and what to expect when onboarding new months of data.

---

## 1. Corrupt epoch timestamps (2007, 2009)

### Symptom
A small number of rows in the raw Parquet files have `tpep_pickup_datetime`
values that decode to years like 2007 or 2009 — decades before the trip
actually occurred. These appear in Gold as tiny outlier data points far to
the left of any time series chart.

### Root cause
TLC stores timestamps as INT64 microseconds since epoch. Some records have
corrupt or default-value timestamps that decode to plausible-looking but
historically incorrect dates.

### Fix
Silver filters these out:
```sql
AND YEAR(tpep_pickup_datetime) BETWEEN 2015 AND 2030
```
The lower bound (2015) predates all data in this pipeline. The upper bound
(2030) provides headroom for future years without being unbounded.

---

## 2. Month boundary bleed-over

### Symptom
The TLC Parquet file for month YYYY-MM occasionally contains a small number
of trips whose `tpep_pickup_datetime` falls in the adjacent month. Examples
observed:
- `yellow_tripdata_2025-01.parquet` contained trips with pickup date 2024-12-31
- `yellow_tripdata_2026-01.parquet` contained 1 trip with pickup date 2026-02-01

These bleed-over records cause spurious data points in Gold for months that
have no Bronze batch — e.g., a single $26.69 revenue row appearing for
2026-02 before the actual February 2026 file was published.

### Root cause
TLC batches files by pickup month but does not strictly enforce the boundary.
Trips very close to midnight on the last/first day of a month occasionally
appear in the adjacent month's file.

### Fix
Silver constrains each trip to its batch month:
```sql
AND TO_CHAR(tpep_pickup_datetime, 'YYYY-MM') = _batch_id
```
This is safe because TLC files are organised by pickup month — a trip with
a February pickup belongs in the February file. When the actual February file
is later published and loaded, those trips will appear correctly.

---

## 3. Superset time grain must be set to "Month" for Gold daily charts

### Symptom
A line chart built on `fct_revenue_daily` with `pickup_date` on the X-axis
shows most data points correctly in the $60-90M range but some dates —
particularly the 1st of certain months — show near-zero values ($25-120).

### Root cause
`fct_revenue_daily` has one row per `pickup_date × pu_location_id` (~5,000
rows per month, ~70,000 rows total). If the Superset chart time grain is set
to **Day** (or left unset), each data point represents a single zone's daily
revenue (~$14K), not a monthly total. Boundary dates at the start of
incremental batches may have partial zone coverage, producing near-zero sums
for those specific dates.

### Fix
In the Superset chart builder, set **Time grain → Month** on the X-axis.
This applies `DATE_TRUNC('MONTH', pickup_date)` and aggregates all zones
across the full month, producing one correct data point per month.

Always use **Month** time grain with `fct_revenue_daily`. Use
`fct_revenue_per_zone_hourly` if hour-level or day-level granularity is needed.
