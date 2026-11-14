# NEAR investment thesis. One command rebuilds everything:
#
#   make charts           (or just `make`) rebuild every number, chart and document from the raw data in data/raw/
#                         (about 20 seconds, no keys). The first run also creates .venv and installs requirements.txt.
#
# Checking the work:
#   make check            delete every generated file, rebuild, and confirm each one matches the committed copy
#   make verify           spot-check random slices of the committed data against the live sources (~1 min, no keys)
#
# Downloading the raw data again (not needed to rebuild; data/raw/ is committed):
#   make fetch            the quick sources (a few minutes, no keys)
#   make fetch-archival   staking and protocol history from the NEAR archival RPC (no keys; the public node is slow)
#   make fetch-github     GitHub stars (needs the gh CLI logged in, or GITHUB_TOKEN in .env)
#   make fetch-bigquery   run queries/*.sql against the NEAR BigQuery public dataset (needs a Google Cloud project)
#   make fetch-explorer   every NEAR Intents swap from the Explorer API (needs a partner JWT in .env; about 12 hours)
#   make all              fetch, then charts

.DEFAULT_GOAL := charts

VENV := .venv
PY := $(VENV)/bin/python -W ignore
READY := $(VENV)/.ready
READY_BQ := $(VENV)/.ready-bigquery

# The Python that creates .venv: the first of these that is version 3.11 to 3.14.
# To choose another: make charts PYTHON=/path/to/python
PYTHON ?= $(shell for p in python3.13 python3.12 python3.11 python3.14 python3 python; do \
	if $$p -c 'import sys; sys.exit(not (3, 11) <= sys.version_info[:2] <= (3, 14))' 2>/dev/null; then echo $$p; break; fi; done)

.PHONY: setup fetch fetch-archival fetch-explorer fetch-bigquery fetch-github analysis charts check verify all

# Builds THESIS.md, METHODS.md, DASHBOARD.md, site/index.html, site/charts/*.svg and data/derived/headline_numbers.json.
charts: analysis
	$(PY) -m viz.build

# Turns data/raw/ into data/derived/ (no keys). Each script prints its key numbers.
# C3 reads the 7.7 million swaps in data/raw/explorer/swaps/ and takes most of the time.
analysis: $(READY)
	$(PY) -m analysis.c1_revenue_mix
	$(PY) -m analysis.c2_l1_settlement
	$(PY) -m analysis.c3_intents_breadth
	$(PY) -m analysis.c4_market_share
	$(PY) -m analysis.c5_near_ai
	$(PY) -m analysis.c6_capture
	$(PY) -m analysis.scenarios
	$(PY) -m analysis.crosschecks

# Creates .venv and installs the pinned packages. Runs once, and again only if requirements.txt changes.
setup: $(READY)

$(READY): requirements.txt
	@if [ ! -x $(VENV)/bin/python ]; then \
		if [ -z "$(PYTHON)" ]; then \
			echo "This needs Python 3.11, 3.12, 3.13 or 3.14, and none was found (tried python3.13, python3.12," >&2; \
			echo "python3.11, python3.14, python3 and python). Install one, or point at one:" >&2; \
			echo "    make charts PYTHON=/path/to/python3.13" >&2; \
			exit 1; \
		fi; \
		echo "First run: creating $(VENV) with $$($(PYTHON) --version 2>&1) and installing requirements.txt"; \
		$(PYTHON) -m venv $(VENV) || { rm -rf $(VENV); exit 1; }; \
	fi
	@$(VENV)/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt
	@touch $@

# The Google libraries are only needed to run the BigQuery queries again.
$(READY_BQ): requirements-bigquery.txt $(READY)
	@$(VENV)/bin/python -m pip install -q --disable-pip-version-check -r requirements-bigquery.txt
	@touch $@

# Deletes every generated file, rebuilds, then compares each file with the copy that was there before
# (see verify/rebuild_check.py). Fails if a document, chart or data file no longer matches the raw data and the code.
check: $(READY)
	@MAKE="$(MAKE)" $(PY) -m verify.rebuild_check

# Picks random past points from data/raw/, fetches the same points live and compares them. Prints the seed;
# `make verify SEED=123` repeats the same picks. Exits 1 if any value differs. The Explorer check needs the partner JWT
# and is skipped without it.
verify: $(READY)
	$(PY) -m verify.spot_check $(if $(SEED),--seed $(SEED))

fetch: $(READY)
	$(PY) -m fetch.revenue_tracker
	$(PY) -m fetch.rpc
	$(PY) -m fetch.defillama
	$(PY) -m fetch.nearblocks
	$(PY) -m fetch.coingecko
	$(PY) -m fetch.agent_market
	$(PY) -m fetch.oneclick_tokens
	$(PY) -m fetch.nearai
	$(PY) -m fetch.openrouter

# Total NEAR staked at each month end, each validator's stake around the lowest month end, and the protocol-config
# history. The public archival node allows only a few calls at a time; answers are cached, so a rerun is quick.
fetch-archival: $(READY)
	$(PY) -m fetch.staking_history
	$(PY) -m fetch.staking_validators
	$(PY) -m fetch.protocol_history

# Needs the gh CLI logged in (or GITHUB_TOKEN in .env).
fetch-github: $(READY)
	$(PY) -m fetch.github_stars

# Needs NEAR_INTENTS_JWT in .env. Resumable; the first run takes about 12 hours because of the API's rate limit.
# It then refills any window the API's cursor skipped. Afterwards `make charts` rebuilds the swap table from the pages.
fetch-explorer: $(READY)
	$(PY) -u -m fetch.explorer
	$(PY) -u -m fetch.explorer --fill-gaps

# Needs Google sign-in (gcloud auth application-default login) and GCP_PROJECT_ID in .env.
# Dry-runs every query first and refuses any over 150 GB.
fetch-bigquery: $(READY_BQ)
	$(PY) -m fetch.bigquery --max-gb 150

all: fetch charts
