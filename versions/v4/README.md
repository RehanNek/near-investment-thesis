# v4 (frozen 2026-11-14)

The version with the current thesis line: "NEAR is an L1 with two fast-growing businesses behind its token. Revenue
growth, combined with buybacks, burns and staking, makes it a solid long-term investment." Its last table, "What
would change our mind", still had one row for each of the six evidence claims (C1 to C6) from v3. On 2026-11-14 that
table was rebuilt around the thesis line, and this version was frozen first so nothing is lost. It is not rebuilt by
`make charts`; the numbers are the data as of Nov 6, 2026.

- `THESIS.md`: the thesis paragraph, the problem NEAR solves, the three layers, why the token has value, the last
  year business by business, and one table with a row per claim: for, against, what would change our mind.
- `METHODS.md`: how each number is computed, each claim's evidence in detail, scenarios, sources.
- `DASHBOARD.md`: every chart with one plain sentence and the query behind it.
- `site/index.html`: the same dashboard with hover readouts (open it in a browser; the code links point back to the repo).
- `viz/`: the build code and templates that produced them.
- `data/headline_numbers.json`: every number quoted in v4.

The current version is v6 (v5 is in `../v5/`): `THESIS.md`, `METHODS.md` and `DASHBOARD.md` at the repo root. Earlier versions are in
`../v3/`, `../v2/`, `../v1/` and `../v0/`.
