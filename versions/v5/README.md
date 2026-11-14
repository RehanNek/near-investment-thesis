# v5 (frozen 2026-11-14)

The first version whose last table, "What would change our mind", follows the thesis line: one row for each thing
the line claims (NEAR Intents is a fast-growing business, NEAR AI is a fast-growing business, revenue is growing,
burns and buybacks tie that revenue to the token, staking locks NEAR up). In this version the staking row rested on
one day's snapshot of staked NEAR. On 2026-11-14 the table was reordered and trimmed and a month-by-month history of
staked NEAR was added, and this version was frozen first so nothing is lost. It is not rebuilt by `make charts`; the
numbers are the data as of Nov 6, 2026.

- `THESIS.md`: the thesis paragraph, the problem NEAR solves, the three layers, why the token has value, the last
  year business by business, and one table that tests each part of the thesis line: for, against, what would change
  our mind.
- `METHODS.md`: how each number is computed, each claim's evidence in detail, scenarios, sources.
- `DASHBOARD.md`: every chart with one plain sentence and the query behind it.
- `site/index.html`: the same dashboard with hover readouts (open it in a browser; the code links point back to the repo).
- `viz/`: the build code and templates that produced them.
- `data/headline_numbers.json`: every number quoted in v5.

The current version is v6: `THESIS.md`, `METHODS.md` and `DASHBOARD.md` at the repo root. Earlier versions are in
`../v4/`, `../v3/`, `../v2/`, `../v1/` and `../v0/`.
