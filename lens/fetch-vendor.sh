#!/usr/bin/env bash
# Downloads the two engine files the page serves beside itself (see README.md):
# DuckDB-WASM's engine, gzipped under a .wasm name, and its Parquet extension.
# The versions must match DUCK_VER and DUCK_CORE in index.html.
set -euo pipefail
cd "$(dirname "$0")"
DUCK_VER=1.32.0 DUCK_CORE=v1.4.3
mkdir -p vendor/ext/$DUCK_CORE/wasm_eh
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://registry.npmjs.org/@duckdb/duckdb-wasm/-/duckdb-wasm-$DUCK_VER.tgz" | tar xz -C "$tmp" package/dist/duckdb-eh.wasm
gzip -9 -c "$tmp/package/dist/duckdb-eh.wasm" > vendor/duckdb-eh.gz.wasm
curl -fsSL -o vendor/ext/$DUCK_CORE/wasm_eh/parquet.duckdb_extension.wasm \
  "https://extensions.duckdb.org/$DUCK_CORE/wasm_eh/parquet.duckdb_extension.wasm"
ls -la vendor vendor/ext/$DUCK_CORE/wasm_eh
