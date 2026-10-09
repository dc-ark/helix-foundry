# 📊 Ark dev-data demo

One command turns a laptop into a Helix Foundry workspace built on Ark's **dev** ledger: parties, accounts and balances, transactions, postings, volumes, revenue, payment corridors, reserve positions, senders and beneficial owners, linked into one ontology you can explore and ask questions of. It is for one trusted person with dev-account access (an exec, an engineer) running an investor-style demo on their own machine.

```sh
./ark/demo.sh
```

---

## 🧰 What you need

- **Docker** with Compose v2, running.
- **AWS CLI v2** with an SSO profile for the ark-data dev account. The script uses the profile `ark-data-dev` (override with `ARK_AWS_PROFILE`) and runs `aws sso login` if the session has expired. It refuses any account other than dev.
- **Optional: `ANTHROPIC_API_KEY`** in your shell. With it, setup uses Claude, which writes far better descriptions and answers. Without it, a local model runs in Docker (a ~2.5 GB download, and slow on a laptop CPU).

## ⚙️ How it works

```
 laptop SSO ──short-lived keys──> ark container ──ATTACH read-only──> s3://ark-data-dev-lake-…/serving/serving.duckdb
                                       │
                         export.py: curated SELECTs ──> ark/out/*.parquet   (personal data, stays local)
                                       │
                         load.py: provider → uploads → ontology → confirm ──> Helix Foundry on 127.0.0.1
                                                                    ✗ an import fails → script stops, app shows why
```

- **The source** is ark-data's published serving bundle, the same read-only file Metabase attaches. Nothing needs the VPC, a catalog password or a running ark-data service, and nothing writes to AWS.
- **The export** (`export.py`) renames ids so they match across datasets (`party_id`, `txn_id`, `instrument_id`); Helix Foundry's ontology suggestion links datasets on matching key names and values. Amounts are converted from minor units per asset and scale. A table that is missing or empty in the bundle is skipped.
- **The load** (`load.py`) drives the app's guided setup through its API, so the browser opens on a built workspace rather than a wizard.

## 🔒 Personal data

The export deliberately keeps personal data: party names, sender names, beneficial owners with addresses and ID-document expiry. That is why it reads dev only. `ark/out/` is gitignored and dockerignored; it never leaves the laptop except into the local Helix Foundry, which listens on loopback only. Delete `ark/out/` after the demo, and run `./ark/demo.sh --reset` to wipe the workspace.

## 🔁 Other runs

| Command                                | Does                                                                   |
| -------------------------------------- | ---------------------------------------------------------------------- |
| `./ark/demo.sh --skip-export`          | Reload the last export, with no AWS call                               |
| `./ark/demo.sh --fixture FILE`         | Export from a local `serving.duckdb`, such as ark-data's fixture build |
| `./ark/demo.sh --reset`                | Delete every Helix Foundry workspace on this computer first (asks)     |
| `ARK_DEMO_SOURCE=s3://… ./ark/demo.sh` | Read a different serving bundle in the dev account                     |

Loading into a workspace that is already set up does nothing; reset first to load fresh data. Everyday stack commands (status, logs, stop) are in the main [README](../README.md#everyday-commands); pass `-f compose.yaml -f compose.ark.yaml` to them.
