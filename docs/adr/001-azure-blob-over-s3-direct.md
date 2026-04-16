# ADR-001: Use Azure Blob Storage as External Stage Instead of Direct S3 Access

| Field       | Value                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Date**    | 2026-04-16                   |
| **Author**  | Rushikesh Dhumal             |

---

## Context

The NYC TLC Yellow Taxi dataset is hosted on a public AWS S3 bucket
(`s3://nyc-tlc/trip data/`). The original pipeline design pointed the
Snowflake External Stage directly at this S3 bucket, which appeared to be
the simplest path — no intermediate storage, no upload step.

During implementation, two blockers emerged:

1. **Access denied on anonymous reads.** Despite being documented as public,
   the S3 bucket rejected unauthenticated requests from Snowflake's stage.
   Anonymous access (`AUTHENTICATION_TYPE = 'ANONYMOUS'`) returned permission
   errors when Snowflake attempted to list or read files.

2. **AWS account requirement.** Obtaining static AWS credentials (Access Key
   ID + Secret Access Key) to authenticate the stage required creating and
   managing an AWS account solely for read access to a third-party public
   dataset. This introduced unnecessary credential surface area and cost
   risk with no architectural benefit.

---

## Decision

Replace the S3 External Stage with an **Azure Blob Storage External Stage**.

The revised data flow is:

```
NYC TLC CDN (CloudFront)
        │
        │  HTTPS download (no auth — CDN is fully public)
        ▼
infra/scripts/upload_to_azure.py   ← one-time bootstrap + future monthly runs
        │
        │  azure-storage-blob SDK + SAS token
        ▼
Azure Blob Storage (nyc-tlc-raw container)
        │
        │  Snowflake External Stage (AZURE_SAS_TOKEN)
        ▼
NYC_TLC_DB.BRONZE (Snowflake)
```

Files are downloaded directly from the TLC's CloudFront CDN
(`https://d37ci6vzurychx.cloudfront.net/trip-data/`), which requires no
authentication, then staged in Azure Blob Storage under our control.

---

## Options Considered

| Option | Pros | Cons |
|--------|------|------|
| **S3 direct stage (original)** | No intermediate storage | S3 anonymous access blocked; requires AWS credentials; adds AWS account overhead |
| **Azure Blob Storage (chosen)** | Full control over the data; single cloud vendor (Azure); SAS token is scoped and rotatable; CDN download requires no credentials | Extra upload step; ~15–30 min one-time bootstrap |
| **Snowflake internal stage** | No external storage needed | Files stored inside Snowflake — increases storage costs on trial; not suitable for large Parquet files |
| **Azure Data Factory** | Fully managed ingestion | Significant setup overhead; overkill for a single dataset source |

---

## Consequences

**Positive**
- No AWS account or IAM credentials required in the pipeline.
- The Azure SAS token is scoped to the container, rotatable, and has an
  expiry — least-privilege by design.
- `upload_to_azure.py` is idempotent: re-running skips already-uploaded
  blobs, making it safe for scheduled monthly runs in Phase 2.
- All data assets (Blob Storage + Snowflake) live in a single cloud
  ecosystem, simplifying networking and access control.

**Trade-offs**
- An explicit upload step (`upload_to_azure.py`) is now required before
  new monthly files are available to Snowflake. This will be automated
  as part of the Phase 2 Airflow DAG (`ingest_nyc_taxi_raw`).
- Azure Blob Storage incurs minor storage costs (~$0.02/GB/month for LRS),
  acceptable for a ~15 GB dataset.

---

## Files Changed

| File | Change |
|------|--------|
| `infra/scripts/snowflake_setup.sql` | Stage URL changed from `s3://` to `azure://`; credential changed from `AWS_KEY_ID/AWS_SECRET_KEY` to `AZURE_SAS_TOKEN` |
| `infra/scripts/upload_to_azure.py` | New — bootstraps Azure with TLC Parquet files (Jan 2025 → latest) |
| `.env.example` | Removed `AWS_KEY_ID`, `AWS_SECRET_KEY`; added `AZURE_STORAGE_ACCOUNT`, `AZURE_STORAGE_CONTAINER`, `AZURE_SAS_TOKEN` |
| `requirements.txt` | Added `azure-storage-blob>=12.19.0`, `requests>=2.31.0`; bumped `pyarrow` to `>=16.0.0` for Python 3.13 wheel compatibility |
