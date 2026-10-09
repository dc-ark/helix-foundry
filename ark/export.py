"""Export a curated slice of Ark's published dev ledger to Parquet.

The source is ark-data's published serving bundle (`serving.duckdb`), the same
read-only file Metabase attaches. It is attached straight from S3 with the
caller's AWS credentials, so nothing here needs the VPC, the catalog password or
a running ark-data service. Every dataset is a SELECT over that bundle, renamed
so the same id carries the same column name everywhere (`party_id`, `txn_id`,
`instrument_id`): Helix Foundry's ontology suggestion links datasets by matching
key names and values, so consistent names are what make the graph connect.

Personal data is kept on purpose. This reads the dev stage only, and names,
beneficial owners and senders are much of what makes the demo legible. The
Parquet files it writes therefore hold personal data: ark/out is gitignored and
goes nowhere but the local Helix Foundry on the laptop that ran the export.
Grants and principals are left out because they describe access control, not
the business.

Usage: python export.py SOURCE OUT_DIR
SOURCE is an s3:// URL or a local path to a serving.duckdb.
"""

import json
import os
import sys
import time

import duckdb

# Minor units become decimal amounts per (asset, scale); summing raw units
# across scales would be meaningless, so every amount is divided by its own scale.
AMOUNT = "units / power(10, scale)"

# ark-data marts call the ledger party `entity_id`, and it always means
# dim_party.party_hid, so every one is renamed to party_id here. The ownership
# tables have their own `party_id` for a person or company inside a customer's
# ownership chain; that one becomes owner_id so it never links to a ledger party.
#
# One entry per exported dataset: (file name, SQL). A dataset whose source
# table is missing in this stage's bundle is skipped, so a schema that moved
# on ahead of this script still exports everything else.
DATASETS = {
    "parties": f"""
        SELECT party_hid AS party_id, kind AS party_kind, display_name AS party_name,
               kyc_status, tenancy,
               coalesce(jur_ultimate_party_country, jur_debtor_address) AS country
        FROM src.dim_party""",
    "accounts": f"""
        SELECT addr AS account_address, addr_root AS account_type,
               addr_holder AS party_id, addr_class AS account_class,
               bucket AS ledger, asset,
               sum({AMOUNT}) FILTER (WHERE layer = 'settled') AS settled_balance,
               sum({AMOUNT}) FILTER (WHERE layer <> 'settled') AS pending_balance,
               count(*) AS posting_count,
               min(effective_ts) AS first_activity_at,
               max(effective_ts) AS last_activity_at
        FROM src.fct_postings
        GROUP BY ALL""",
    "transactions": """
        SELECT txn_id, verb AS transaction_type, book, effective_ts, recorded_at
        FROM src.dim_transaction""",
    "postings": f"""
        SELECT posting_id, txn_id, addr AS account_address, addr_holder AS party_id,
               bucket AS ledger, asset, {AMOUNT} AS amount, layer, effective_ts
        FROM src.fct_postings""",
    "daily_volume": """
        SELECT entity_id AS party_id, bucket AS ledger, period_day, period_month,
               rail, direction, txn_count, volume_cents / 100.0 AS volume_usd
        FROM src.totals_over_period""",
    "revenue": """
        SELECT entity_id AS party_id, period_month, book, rail, fee_regime, asset,
               revenue_cents / 100.0 AS revenue_usd,
               base_volume_cents / 100.0 AS volume_usd, txn_count, avg_rate_bps
        FROM src.revenue_per_customer""",
    "fees": """
        SELECT entry_id AS fee_id, txn_id, entity_id AS party_id, effective_ts, rail,
               fee_regime, base_amount_cents / 100.0 AS base_amount_usd, rate_bps,
               revenue_cents / 100.0 AS revenue_usd
        FROM src.fee_entries""",
    "payment_corridors": """
        SELECT entity_id AS party_id, entity_jurisdiction, counterparty_jurisdiction,
               direction, rail, period_month, txn_count,
               volume_cents / 100.0 AS volume_usd, currency
        FROM src.geography_summary""",
    "payments_in_flight": """
        SELECT payment_id, entity_id AS party_id, rail, status, direction,
               amount_cents / 100.0 AS amount_usd, currency, jurisdiction,
               latest_stage, stage_at, created_at, updated_at
        FROM src.in_flight_payment_state""",
    "reserve_positions": """
        SELECT p.lot_id, p.instrument_id, p.asset_class, p.valuation_method,
               p.custody_location, p.qty, p.cost_basis, p.accreted,
               m.px AS mark_price, m.as_of AS marked_at,
               p.acquired_as_of, p.closed_at
        FROM src.dim_position p
        LEFT JOIN (
            SELECT * FROM src.marks QUALIFY row_number() OVER (
                PARTITION BY instrument_id ORDER BY as_of DESC) = 1
        ) m USING (instrument_id)""",
    "senders": """
        SELECT entity_id AS party_id, sender_id, sender_name, sender_type,
               sender_country, sender_status, direction, rail, period_month,
               txn_count, volume_cents / 100.0 AS volume_usd, currency,
               pending_count, oldest_pending_age_minutes
        FROM src.sender_flows""",
    "beneficial_owners": """
        SELECT entity_id AS party_id, entity_name AS party_name,
               party_id AS owner_id, parent_party_id AS parent_owner_id,
               party_name AS owner_name, kind AS owner_kind, role, ownership_pct,
               chain_depth, chain_path, jurisdiction_of_incorporation,
               screening_state, id_document_expiry, lei, primary_regulator,
               ultimate_parent_legal_name, ultimate_parent_jurisdiction,
               last_review_at, next_review_due
        FROM src.ownership_profile""",
    "ownership_links": """
        SELECT entity_id AS party_id, src AS owner_node_id, dst AS owned_node_id,
               role, ownership_bps / 100.0 AS ownership_pct, hop, basis
        FROM src.network_ownership_edge""",
    "ownership_nodes": """
        SELECT entity_id AS party_id, node_id AS owner_node_id, legal_name,
               kind AS node_kind, jur AS jurisdiction, role
        FROM src.network_ownership_node""",
}


def main(source: str, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    con = duckdb.connect()
    if source.startswith("s3://"):
        con.sql("LOAD httpfs")
        region = os.environ.get("AWS_REGION", "us-east-1")
        con.sql(f"CREATE SECRET ark (TYPE s3, PROVIDER credential_chain, REGION '{region}')")
    con.execute(f"ATTACH '{source}' AS src (READ_ONLY)")

    manifest = {"source": source, "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "datasets": {}}
    for name, sql in DATASETS.items():
        path = os.path.join(out, f"{name}.parquet")
        try:
            rows = con.sql(f"SELECT count(*) FROM ({sql})").fetchone()[0]
        except duckdb.CatalogException as e:
            print(f"  skip {name}: {str(e).splitlines()[0]}")
            continue
        if rows == 0:
            # An empty dataset gives the ontology nothing to link and shows up
            # as a blank card, so it is left out rather than uploaded.
            print(f"  skip {name}: no rows in this stage")
            if os.path.exists(path):
                os.remove(path)
            continue
        con.sql(sql).write_parquet(path)
        manifest["datasets"][name] = rows
        print(f"  {name}: {rows:,} rows")

    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
