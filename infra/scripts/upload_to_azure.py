"""
upload_to_azure.py — NYC TLC BI Pipeline bootstrap loader

Downloads Yellow Taxi Parquet files from the NYC TLC CloudFront CDN for the
date scope Jan 2025 → latest available, then uploads them to Azure Blob
Storage for use as a Snowflake External Stage.

USAGE
-----
    # From the repo root with .env loaded:
    source .env                          # or: set -a && . .env && set +a
    python infra/scripts/upload_to_azure.py

    # Dry-run (lists months without downloading):
    python infra/scripts/upload_to_azure.py --dry-run

    # Single month:
    python infra/scripts/upload_to_azure.py --month 2025-03

REQUIRED ENV VARS (from .env)
------------------------------
    AZURE_STORAGE_ACCOUNT   e.g. nyctlcstorage
    AZURE_STORAGE_CONTAINER e.g. nyc-tlc-raw
    AZURE_SAS_TOKEN         SAS token (without leading '?')

IDEMPOTENCY
-----------
    Blobs that already exist in the container are skipped automatically.
    Safe to re-run after a partial failure.
"""

import argparse
import os
import sys
from datetime import date
from typing import Iterator

import requests
from azure.storage.blob import BlobServiceClient, BlobClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TLC_CDN_URL = (
    "https://d37ci6vzurychx.cloudfront.net/trip-data/"
    "yellow_tripdata_{month}.parquet"
)
INGEST_START = date(2025, 1, 1)
# TLC publishes with a ~2-month lag; stop before the current month to avoid
# requesting files that don't exist yet.
TLC_RELEASE_LAG_MONTHS = 2
CHUNK_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB streaming chunks


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def _advance_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def months_in_scope() -> Iterator[str]:
    """Yield YYYY-MM strings from INGEST_START up to (today - lag)."""
    today = date.today()
    cutoff = today
    for _ in range(TLC_RELEASE_LAG_MONTHS):
        cutoff = date(cutoff.year, cutoff.month, 1)
        # step back one month
        if cutoff.month == 1:
            cutoff = date(cutoff.year - 1, 12, 1)
        else:
            cutoff = date(cutoff.year, cutoff.month - 1, 1)

    current = INGEST_START
    while current < cutoff:
        yield current.strftime("%Y-%m")
        current = _advance_month(current)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def download_parquet(month: str) -> bytes | None:
    """
    Stream a Parquet file from the TLC CDN.
    Returns raw bytes, or None if the file is not yet published (404).
    Raises on all other HTTP errors.
    """
    url = TLC_CDN_URL.format(month=month)
    print(f"  → downloading {url}")
    with requests.get(url, stream=True, timeout=120) as resp:
        if resp.status_code == 404:
            print("     not published yet — skipping")
            return None
        resp.raise_for_status()
        chunks = []
        downloaded = 0
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE_BYTES):
            chunks.append(chunk)
            downloaded += len(chunk)
            print(f"     {downloaded / 1_048_576:.1f} MB", end="\r")
        print(f"     {downloaded / 1_048_576:.1f} MB — done          ")
        return b"".join(chunks)


# ---------------------------------------------------------------------------
# Azure upload
# ---------------------------------------------------------------------------
def get_blob_service_client() -> BlobServiceClient:
    account = os.getenv("AZURE_STORAGE_ACCOUNT")
    sas_token = os.getenv("AZURE_SAS_TOKEN")
    if not account or not sas_token:
        sys.exit(
            "ERROR: AZURE_STORAGE_ACCOUNT and AZURE_SAS_TOKEN must be set. "
            "Have you sourced your .env file?"
        )
    account_url = f"https://{account}.blob.core.windows.net"
    return BlobServiceClient(account_url=account_url, credential=sas_token)


def blob_exists(client: BlobServiceClient, container: str, name: str) -> bool:
    blob: BlobClient = client.get_blob_client(container=container, blob=name)
    return blob.exists()


def upload_blob(
    client: BlobServiceClient,
    container: str,
    name: str,
    data: bytes,
) -> None:
    blob: BlobClient = client.get_blob_client(container=container, blob=name)
    blob.upload_blob(data, overwrite=False)
    print(f"     uploaded → {container}/{name}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(dry_run: bool, single_month: str | None) -> None:
    container = os.getenv("AZURE_STORAGE_CONTAINER")
    if not container:
        sys.exit("ERROR: AZURE_STORAGE_CONTAINER must be set.")

    target_months = [single_month] if single_month else list(months_in_scope())

    if not target_months:
        print("No months in scope — nothing to do.")
        return

    print(f"Months in scope ({len(target_months)}): {target_months[0]} → {target_months[-1]}")

    if dry_run:
        print("\n[dry-run] No files will be downloaded or uploaded.")
        for month in target_months:
            print(f"  would process: yellow_tripdata_{month}.parquet")
        return

    az_client = get_blob_service_client()
    skipped = uploaded = failed = 0

    for month in target_months:
        blob_name = f"yellow_tripdata_{month}.parquet"
        print(f"\n[{month}] {blob_name}")

        if blob_exists(az_client, container, blob_name):
            print("  already in Azure — skipping")
            skipped += 1
            continue

        try:
            data = download_parquet(month)
            if data is None:
                skipped += 1
                continue
            upload_blob(az_client, container, blob_name, data)
            uploaded += 1
        except Exception as exc:
            print(f"  ERROR: {exc}")
            failed += 1

    print(
        f"\n{'='*50}\n"
        f"Done. uploaded={uploaded}  skipped={skipped}  failed={failed}\n"
        f"{'='*50}"
    )
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download NYC TLC Parquet files and upload to Azure Blob Storage."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List months in scope without downloading or uploading.",
    )
    parser.add_argument(
        "--month",
        metavar="YYYY-MM",
        help="Process a single month only (e.g. 2025-03).",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, single_month=args.month)


if __name__ == "__main__":
    main()
