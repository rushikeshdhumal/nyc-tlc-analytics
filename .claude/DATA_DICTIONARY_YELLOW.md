# Official NYC TLC Yellow Taxi Dictionary (Updated March 2025)

## 1. Primary Identifiers & Times
- **VendorID**: 1=CMT, 2=Curb, 6=Myle, 7=Helix.
- **tpep_pickup_datetime**: Meter engaged.
  - *Bronze storage*: Parquet timestamps land in VARIANT as INT64 (microseconds since epoch). Casting directly via `::TIMESTAMP` in Bronze returns null/"Invalid date". Use `TO_TIMESTAMP_NTZ(raw_data:tpep_pickup_datetime::NUMBER, 6)` in Silver dbt models.
- **tpep_dropoff_datetime**: Meter disengaged. Same INT64 cast rule applies.
- **PULocationID / DOLocationID**: Join with TLC Taxi Zones lookup.

## 2. Rate & Payment Codes (Critical for Filtering)
- **RatecodeID**: 1=Standard, 2=JFK, 3=Newark, 4=Nassau/Westchester, 5=Negotiated, 6=Group. 
  - *Note*: `99` is Null/Unknown.
- **payment_type**: 0=Flex, 1=Card, 2=Cash, 3=No Charge, 4=Dispute, 5=Unknown, 6=Void.
  - *Logic Rule*: Metrics involving `tip_amount` are only valid for `payment_type = 1`.

## 3. Financial Breakdown (Revenue Logic)
- **fare_amount**: Base time-and-distance fare.
- **Surcharges**: `extra`, `mta_tax`, `improvement_surcharge`, `congestion_surcharge`.
- **New 2025 Fees**: 
    - `airport_fee`: Only for JFK/LaGuardia pickups.
    - `cbd_congestion_fee`: Per-trip charge for MTA Congestion Relief Zone (Starts Jan 5, 2025).
- **total_amount**: Sum of all fees. **Does not include cash tips.**

## 4. Data Quality & Cleaning Rules (For Silver Layer)
- **Trip Validity**: 
    - Filter out `payment_type` 3, 4, or 6 for revenue reports.
    - Filter out `trip_distance <= 0`.
    - Filter out `fare_amount <= 0`.
- **Temporal Check**: Ensure `tpep_dropoff_datetime > tpep_pickup_datetime`.
- **CBD Analysis**: Use `cbd_congestion_fee` to identify trips entering/staying in the Manhattan congestion zone for specialized 2025 reports.

## 5. Taxi Zone Lookup (Reference Table)
- **Source**: Static CSV located in `transform/seeds/taxi_zone_lookup.csv`.
- **Handling**: Managed via `dbt seed`.
- **Schema**:
    - `LocationID`: Primary Key (corresponds to PULocationID/DOLocationID).
    - `Borough`: NYC Borough (Manhattan, Brooklyn, etc.).
    - `Zone`: Neighborhood name (e.g., "JFK Airport", "Central Park").
    - `service_zone`: Category of service (e.g., "Yellow Zone", "Boro Zone").
