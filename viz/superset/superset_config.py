# =============================================================================
# Superset Runtime Configuration — NYC TLC BI Pipeline
# =============================================================================
# Mounted into the container at /app/pythonpath/superset_config.py.
# Superset loads this file automatically on startup.
#
# Cache strategy
# --------------
# DATA_CACHE_CONFIG caches Snowflake query results inside the container.
# Charts served from cache do not hit Snowflake at all — zero compute cost.
# CACHE_DEFAULT_TIMEOUT = 86400s (24 hours): one cold Snowflake query per
# chart per day. Matches the pipeline's monthly cadence; data does not change
# intraday so a 24h TTL is safe.
#
# FileSystemCache requires no extra services (no Redis). Cache files are
# written to /app/superset_home/cache, which lives on the superset-home
# named Docker volume and survives container restarts.
# =============================================================================

CACHE_CONFIG = {
    "CACHE_TYPE": "FileSystemCache",
    "CACHE_DIR": "/app/superset_home/cache",
    "CACHE_DEFAULT_TIMEOUT": 86400,
}

DATA_CACHE_CONFIG = CACHE_CONFIG
