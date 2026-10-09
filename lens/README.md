# 🔎 Ark Ledger Lens

A Claude artifact for exploring Ark's dev ledger: headline numbers, a party explorer, a raw table browser, and **Ask**, where Claude answers questions by running SQL in the page. It reads the Parquet files that `ark/export.py` writes to `ark/out/`; the viewer picks them in the browser, and they are never uploaded. Only query results go to Claude, on the viewer's own claude.ai account.

---

## ⚙️ How it runs inside an artifact

```
 ark/out/*.parquet ──picked by viewer──> DuckDB-WASM (in a page worker) <──run_sql── Claude (sample capability)
                                              │
 artifact sandbox: scripts only from the CDN  ├─ engine: duckdb-eh.gz.wasm, published beside the page
                   ✗ any other fetch          └─ Parquet extension: ext/<core>/wasm_eh/, published beside the page
```

- **The engine is published with the page.** The sandbox loads scripts from jsDelivr but blocks every other request there, including DuckDB's own fetch of its `.wasm`. The worker answers that fetch with the gzipped copy beside the page and decompresses it in the browser.
- **So is the Parquet extension.** This DuckDB-WASM build fetches Parquet support from `extensions.duckdb.org`; the page points DuckDB's extension repository at its own `ext/` folder instead.
- **Ask** uses the artifact's `sample` capability with one page tool, `run_sql`, which accepts a single `SELECT` and returns at most 50 rows.

## 🚀 Publishing

`index.html` is the page; `fetch-vendor.sh` downloads the two engine files into `vendor/` (gitignored, about 11 MB). Publish with Claude's Artifact tool:

- `file_path`: `lens/index.html`, with `capabilities: {sample: {}}`
- `files`: `duckdb-eh.gz.wasm` from `vendor/duckdb-eh.gz.wasm`, and `ext/v1.4.3/wasm_eh/parquet.duckdb_extension.wasm` from the same path under `vendor/`

Publishing again to the same artifact keeps the engine files unless they change. Bumping DuckDB-WASM means changing `DUCK_VER` and `DUCK_CORE` in both `index.html` and `fetch-vendor.sh`, and republishing both files.

## 🔒 Data

The exported files hold dev-stage personal data (party names, beneficial owners). They stay in the viewer's browser memory and are gone when the tab closes. Sharing the artifact shares only the app: each viewer loads their own export.
