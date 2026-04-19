# =============================================================================
# NYC TLC Pipeline — Apache Superset Service Image
# Base: Apache Superset 3.1.3
#
# Extends the official image with:
#   - snowflake-sqlalchemy  (Superset <> Snowflake Gold layer connector)
#
# NOTE: The Snowflake connection is configured through the Superset UI
#       (Data > Databases > + Database) using the URI format:
#       snowflake://<USER>:<PASS>@<ACCOUNT>/<DATABASE>/<SCHEMA>?role=<ROLE>&warehouse=<WH>
# =============================================================================
FROM apache/superset:3.1.3

# Switch to root to install the Snowflake driver
USER root
RUN pip install --no-cache-dir \
    "snowflake-sqlalchemy==1.5.3" \
    "snowflake-connector-python>=3.6.0" \
    "pandas>=2.0.3,<2.1" \
    "cryptography>=42.0.4,<43.0.0"

# Return to the superset runtime user
USER superset
