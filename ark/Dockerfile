# The exporter and loader run here, so a laptop needs only Docker and the AWS
# CLI. httpfs is installed at build time so an export never depends on DuckDB's
# extension server being reachable in the middle of a demo.
FROM python:3.12-slim
RUN pip install --no-cache-dir duckdb==1.5.6 \
 && python -c "import duckdb; duckdb.sql('INSTALL httpfs')"
WORKDIR /ark
COPY export.py load.py ./
