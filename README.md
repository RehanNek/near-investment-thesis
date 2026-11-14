# NEAR Investment Thesis

**Track:** NEAR HACKATHON, Investment Thesis (`thesis`). An investment thesis on NEAR in which every number, chart and document is rebuilt from the raw data by one command, `make charts`, with no API keys.

## Our Thesis

### NEAR is an L1 with two fast-growing businesses behind its token. Revenue growth, combined with buybacks, burns and staking, makes it a solid long-term investment.

## Start here

Three documents carry this entry. Everything else in the repo is the data and code behind them.

| | Document | What it is |
|---|---|---|
| 1 | **README.md** (this page) | What this is, and how to rebuild every number, chart and document with one command: `make charts` |
| 2 | **[THESIS.md](THESIS.md)** | The report: the thesis, the evidence for it, the evidence against it, and what would change our mind |
| 3 | **[DASHBOARD.md](DASHBOARD.md)** | Every chart, with one plain sentence on what it shows and the query behind it. `site/index.html` has the same charts with hover readouts, in a site with four tabs (Thesis, Dashboard, Build it yourself, Methods) that is [hosted here](https://rehannek.github.io/near-investment-thesis/site/) |

## What this is

An evidence-based investment thesis on NEAR. The two businesses are NEAR Intents (cross-chain swaps settled on NEAR) and NEAR AI; with the NEAR L1 they make three layers on one token. Every claim is backed by data that can be re-fetched and re-computed from this repo, alongside the evidence against it.

## The problem

NEAR is usually valued as a layer-1 blockchain. Most of its fee revenue now comes from NEAR Intents, and several mechanisms that route value back to the token (inflation cut, Intents fee switch and buybacks, staking for AI credits) were switched on only in the last year. This repo measures how far that shift has gone.

## Try it

You need `make`, a Unix shell and Python 3.11, 3.12, 3.13 or 3.14. You need no API keys and no accounts, because the raw data is committed in `data/raw/`. The first run needs internet once, to install five pinned packages into `.venv/`.

**Do X, see Y.** The five steps in short; each is set out in full below.

| # | Do | See | Takes |
|---|---|---|---|
| 0 | `git clone https://github.com/RehanNek/near-investment-thesis.git`, then `cd near-investment-thesis` | The repo, with `README.md`, `THESIS.md` and `DASHBOARD.md` at the top level | A minute |
| 1 | `make charts` | `Built THESIS.md, METHODS.md, DASHBOARD.md, site/index.html and 21 charts in site/charts/ (data as of 2026-11-14).`, then four key points | About a minute the first time, 20 seconds after |
| 2 | `make check` | `OK: all 53 generated files match the committed copies` | 20 seconds |
| 3 | Open `site/index.html` in a browser, or the [hosted copy](https://rehannek.github.io/near-investment-thesis/site/) | Four tabs: Thesis, Dashboard, Build it yourself, Methods. The Dashboard tab has 21 charts, each with one plain sentence, its sources and the query behind it | |
| 4 | In `config.yaml`, under `scenarios:` then `base:`, change `half_life_years: 2` to `3`. Run `make charts` | The third key point's date moves from "Dec 2028" to "Nov 2028" | 20 seconds |
| 5 | `make verify` | A summary like `31 match, 0 revised, 0 differ, 1 skipped`. The run passes when nothing differs | Under a minute |

### 1. Rebuild everything

```bash
make charts
```

Plain `make` does the same.

**You should see:**

- On the first run only, `First run: creating .venv with Python 3.x.y and installing requirements.txt`. The first run takes about a minute in all.
- Each analysis script printing its key numbers. This takes about 20 seconds, most of it reading 7.7 million swaps.
- At the end, this line and then four key points with the thesis's main figures:

```text
Built THESIS.md, METHODS.md, DASHBOARD.md, site/index.html and 21 charts in site/charts/ (data as of 2026-11-14).
```

If no suitable Python is found, the command says so. Point it at one with `make charts PYTHON=/path/to/python3.13`.

### 2. Confirm the committed files come from the raw data

```bash
make check
```

This deletes all 53 generated files (4 documents, 21 charts and 28 data files in `data/derived/`), rebuilds them with `make charts` and compares each one with the copy that was there before.

**You should see:**

```text
Deleted the 53 generated files; rebuilding them from data/raw/ (make charts) ...

  Kind          Files  Result
  documents         4  4 identical byte for byte
  charts           21  21 identical byte for byte
  data files       28  28 identical byte for byte

OK: all 53 generated files match the committed copies (rebuilt in 20 s).
```

`git status` shows no changes afterwards. If a file doesn't match, the command prints its first differing lines and exits with code 1.

Documents and charts must be identical byte for byte. A data file may differ in the last digits of a floating-point sum on another processor; the check then reports it as equal to 9 significant figures and still passes.

**What this was tested on:** macOS on Apple silicon, with Python 3.11, 3.13 and 3.14. All three give 53 identical files. The 3.13 and 3.14 runs started from a fresh copy of the repo with no `.venv/`. Python 3.12, Linux and other processors were not tested.

### 3. Open the site

Open `site/index.html` in a browser (no server needed), or read [`DASHBOARD.md`](DASHBOARD.md). The same page is hosted at <https://rehannek.github.io/near-investment-thesis/site/>.

**You should see:**

- Four tabs: **Thesis** (`THESIS.md`), **Dashboard**, **Build it yourself** (these steps in short) and **Methods** (`METHODS.md`). The build writes all four into the one page.
- On the Dashboard tab, one section for each row of the thesis table, in the table's order, each opening with the result that would change our mind.
- Under every chart: one plain sentence on what it shows, the source and its date, the data files and code that drew it, and the SQL query or API request behind it.
- A hover readout on every chart and a table of the plotted values under it.

### 4. Change an assumption and re-run the model

The scenario model reads its inputs from [`config.yaml`](config.yaml). Under `scenarios:`, then `base:`, change `half_life_years: 2` to `half_life_years: 3`. Then run `make charts` again.

**You should see:**

- The third key point ends "they offset all of it by Nov 2028". Before the change it ended "by Dec 2028".
- The same date changes in `THESIS.md` and in the chart "Where it could go" (`site/charts/scenarios-hsp.svg`).
- `git diff --stat` lists the eleven files that changed: `config.yaml`, four documents, two charts and four data files.

To undo it, put the value back and run `make charts`. `git status` then shows no changes.

### 5. Check the committed data against the live sources

```bash
make verify
```

This picks random past days, months, blocks and tokens from the committed data, fetches the same points live and prints a table of committed and live values. It takes under a minute and needs no keys.

**You should see** a summary like `31 match, 0 revised, 0 differ, 1 skipped`. The counts change with the random picks; the run passes when nothing differs. It prints its seed, and `make verify SEED=…` repeats the same picks.

- **What's checked:**
  - BigQuery's end-of-day supply and that day's net new supply, against the NEAR archival RPC;
  - the live issuance cap and gas-burn setting;
  - revenue.near.org daily fees, daily volume and monthly revenue;
  - 1Click token chains;
  - DefiLlama, NearBlocks, CoinGecko and OpenRouter series;
  - with a partner JWT, one early day and a recent 15-minute window of swaps from the Explorer API, against `data/raw/explorer/swaps/`.
- **Revised** means the source has updated a value it is known to revise. This doesn't fail the run. There are two cases:
  - revenue.near.org keeps settling a month's net revenue for about three months after it ends. For example, Oct 2026 rose 1.3% between Nov 5 and Nov 7.
  - DefiLlama's category totals grow when it adds protocols, because it adds their history too. Between Nov 5 and Nov 14, 2026 it added five protocols to its bridge-aggregator category, which raised that category's past daily totals by a median of 4%. The check therefore compares the protocols in the committed copy with the same protocols live, which must match, and shows the total over every protocol listed now on the next row.
- **Differs** means a settled past value disagrees, and the run exits with code 1.
- **Skipped** checks:
  - the Explorer API check needs a NEAR Intents partner JWT;
  - the public archival node rate-limits hard, so a second run within a few minutes may skip that check.

## Downloading the raw data again

None of this is needed to check the work. Each command writes to `data/raw/` and logs the fetch with its date in `data/raw/_manifest.json`. Run `make charts` afterwards: the numbers and the "data as of" date then follow the new data.

| Command | What it downloads | What it needs | Time |
|---|---|---|---|
| `make fetch` | revenue.near.org, NEAR RPC, DefiLlama, NearBlocks, CoinGecko, Agent Market, the 1Click token list, NEAR AI and OpenRouter | Nothing | About 4 minutes |
| `make fetch-archival` | Staked NEAR at each month end, each validator's stake around the lowest month end, and the protocol-config history | Nothing. The public archival node is rate-limited; answers are cached, so a rerun is quick | Depends on the node |
| `make fetch-github` | Stars of the `nearai` repositories | The `gh` CLI logged in, or `GITHUB_TOKEN` in `.env` | A few seconds |
| `make fetch-bigquery` | The results of `queries/*.sql` | A Google Cloud project: `GCP_PROJECT_ID` in `.env`, and `gcloud auth application-default login`. Uses about 244 GB of query allowance. It dry-runs every query first and refuses any over 150 GB | About 1 minute |
| `make fetch-explorer` | Every NEAR Intents swap from the Explorer API | A NEAR Intents partner JWT as `NEAR_INTENTS_JWT` in `.env` | About 12 hours, because of the API's rate limit. It can be stopped and resumed |

For the keys, copy `.env.example` to `.env` and fill it in. `.env` is git-ignored and no key is in this repo.

The committed data was last refreshed on 2026-11-14: every download behind `make fetch`, `make fetch-archival`, `make fetch-github` and `make fetch-bigquery` was run that day. The full swap download was made on 2026-11-06; on 2026-11-14, `.venv/bin/python -m fetch.explorer --update` added the 182,641 swaps made since then, in 18 minutes. That command needs the raw pages of the full download on disk and says so if they are missing.

## How a chart is built

`data/raw/` (as fetched) → `analysis/*.py` → `data/derived/*.csv` → `viz/build.py` → `site/charts/*.svg`, the dashboard and the documents.

- **No hand-typed numbers.** `THESIS.md` is generated from `viz/thesis_template.md` and `METHODS.md` from `viz/methods_template.md`. The templates hold no figures, and the build stops if one contains a hand-typed digit. Every number quoted in the text is also written to `data/derived/headline_numbers.json`.
- **Facts no API exposes** (for example, the customers NEAR AI names on its homepage) are in `data/manual/facts.yaml`, each with its source and the date we checked it.
- **The swaps.** `data/raw/explorer/swaps/` holds one row per NEAR Intents swap: 7,656,384 swaps in three parquet files, about 107 MB, with the columns the analysis uses. Each user address is replaced by a 64-bit id taken from the SHA-256 hash of the address. The raw API pages (2.6 GB) are not in the repo; `make fetch-explorer` downloads them again.

## Where each track requirement is met

| The track asks for | Where it is |
|---|---|
| SQL queries against the NEAR BigQuery public dataset for daily active accounts, transaction counts and contract usage, always filtered on `block_date` | [`queries/`](queries/), run by `fetch/bigquery.py`, with results in `data/raw/bigquery/`. Daily active accounts and transaction counts: `queries/l1_activity.sql`, charted in [DASHBOARD.md, "NEAR L1"](DASHBOARD.md#near-l1). Contract usage: the top 25 receiving contracts per month in `l1_activity.sql`, transactions by app in `l1_app_split_daily.sql`, and calls to NEAR AI's staking contract in `nearai_staking_activity_daily.sql`. Every query filters on `block_date`, except the two that read `ft_balances_daily`: that table has `epoch_date` instead, and they filter on it. |
| A pull from the NEAR Intents Explorer API for swap volume (JWT in `.env`) | `fetch/explorer.py` reads `NEAR_INTENTS_JWT` from `.env`. The pull is committed as `data/raw/explorer/swaps/`, and `analysis/c3_intents_breadth.py` turns it into the volume, user and chain charts in [DASHBOARD.md, "3. NEAR Intents"](DASHBOARD.md#near-intents). |
| One command that rebuilds every chart from raw data | `make charts`. `make check` deletes every generated file, rebuilds and confirms the result matches. See "Try it" above. |
| A static dashboard page: each chart, the query behind it, and one plain sentence on what it shows | [`DASHBOARD.md`](DASHBOARD.md), and the same page with hover readouts in the Dashboard tab of `site/index.html` |
| `THESIS.md` with the claim | [`THESIS.md`](THESIS.md), "Thesis" (the first section) |
| The evidence for it, the evidence against it, and what result would change my mind | [`THESIS.md`](THESIS.md), "What would change our mind": one table with a row for each thing the thesis line claims (revenue is growing, burns and buybacks tie that revenue to the token, NEAR Intents is a fast-growing business, NEAR AI is a fast-growing business, staking locks NEAR up) and the columns For, Against and What would change our mind. The detail behind each row is in [`METHODS.md`](METHODS.md), under claims C1 to C6. |
| Never invent numbers | Every figure in the documents and charts is filled in by the build. See "How a chart is built" above. |
| If a metric can't be computed from these sources, say so | [`THESIS.md`](THESIS.md) says where a figure is missing or estimated (NEAR AI publishes neither revenue nor total usage) and links to the full list, [`METHODS.md`, "What we couldn't compute"](METHODS.md#what-we-couldnt-compute). |

## What's where

| File | What it is |
|---|---|
| [`THESIS.md`](THESIS.md) | The thesis, on one page: the thesis in a paragraph, the problem NEAR solves, a diagram of the three layers, why the token has value, the last year business by business, and one table that tests each part of the thesis line: evidence for, evidence against and what would change our mind. |
| [`DASHBOARD.md`](DASHBOARD.md) | The static dashboard: every chart, one plain sentence on what it shows, and the query behind it. |
| `site/index.html` | The site, with four tabs: the thesis, the dashboard with hover readouts and a data table under each chart, the build steps, and the methods. Open it in a browser; no server needed. |
| [`METHODS.md`](METHODS.md) | The reference detail: how each number is computed, each claim's evidence and caveats in full, the scenario assumptions, what we couldn't compute, and every source with its date. |
| `Makefile` | The commands: `make charts`, `make check`, `make verify` and the fetch commands. |
| `queries/` | The SQL run against the NEAR BigQuery public dataset. |
| `fetch/` | One script per source. Each writes to `data/raw/`. |
| `data/raw/` | The data as fetched, with `_manifest.json` logging each fetch and its date. |
| `analysis/` | One script per claim (C1 to C6), the scenario model and the cross-checks. Each reads `data/raw/` and writes `data/derived/`. |
| `config.yaml` | The scenario model's inputs. |
| `viz/` | `build.py` writes the documents, the dashboard and the charts; `svg.py` draws the charts; the two templates hold the text of `THESIS.md` and `METHODS.md`. |
| `verify/` | `rebuild_check.py` (`make check`) and `spot_check.py` (`make verify`). |
| `data/manual/facts.yaml` | Facts that no API exposes, each with its source and the date checked. |
| `versions/` | Earlier versions, kept for reference: `v0/` (the first version, frozen 2026-11-07), `v1/` (a longer memo, then the claims, then an appendix; frozen 2026-11-11) `v2/` (the one-page version that v3 was built from, frozen 2026-11-11) `v3/` (the version with the earlier thesis line, frozen 2026-11-14) `v4/` (the current thesis line, with the last table still organised by the six evidence claims; frozen 2026-11-14) and `v5/` (the last table rebuilt around the thesis line, before the staking history was added; frozen 2026-11-14). The current version, v6, is at the repo root. |

## Data sources

Mostly the sources named in the track prompt and NEAR's own first-party data:

| Source | Type | Fetcher |
|---|---|---|
| NEAR BigQuery public dataset (`bigquery-public-data.crypto_near_mainnet_us`) | Track prompt | `fetch/bigquery.py` + `queries/*.sql` |
| NEAR Intents Explorer API | Track prompt | `fetch/explorer.py` |
| NEAR Revenue Tracker (revenue.near.org) | First-party | `fetch/revenue_tracker.py` |
| NEAR RPC and archival RPC (validator stake today and at each month end, each validator's stake around the lowest month end, protocol-config history) | First-party | `fetch/rpc.py`, `fetch/staking_history.py`, `fetch/staking_validators.py`, `fetch/protocol_history.py` |
| FastNEAR NEAR Data API (headers of past blocks: epoch and total supply, for the staking history) | Third-party index of chain data | `fetch/staking_history.py` |
| NEAR AI: `stake.dao` contract views (via NEAR RPC), NEAR AI Cloud model list | First-party | `fetch/nearai.py` |
| OpenRouter, NEAR AI provider page (tokens per model per day) | Third-party (only public NEAR AI usage data) | `fetch/openrouter.py` |
| GitHub, `nearai` org | Third-party | `fetch/github_stars.py` |
| NEAR Agent Market stats | First-party | `fetch/agent_market.py` |
| DefiLlama | Third-party (cross-check, market totals) | `fetch/defillama.py` |
| NearBlocks | Third-party (cross-check) | `fetch/nearblocks.py` |
| CoinGecko | Third-party (price cross-check) | `fetch/coingecko.py` |

Each fetch is logged with its date in `data/raw/_manifest.json`.

## Our other NEAR HACKATHON entry

We entered a second, independent project: **[Basis Prime](https://github.com/RehanNek/basis-prime)**, a prime brokerage on NEAR, in the Unstoppable DeFi track (`defi`). The two projects share no code.

## Tools used

Python 3.11 to 3.14 with requests, numpy, pandas, pyarrow and PyYAML (versions pinned in `requirements.txt`). Running the BigQuery queries again also needs google-cloud-bigquery (`requirements-bigquery.txt`). Charts are plain SVG drawn by `viz/svg.py` (no plotting library); the dashboard's hover layer is `site/app.js`, vanilla JavaScript with no dependencies. Code written with help from Claude Code (AI). NEAR agent skills from `near/agent-skills`.

## License

Code and writing in this repo: MIT (see `LICENSE`). The data under `data/raw/` was fetched from the sources listed above and stays under each source's own terms; `data/derived/` is computed from it.
