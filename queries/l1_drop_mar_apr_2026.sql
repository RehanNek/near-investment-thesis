-- What caused L1 transactions to fall from ~3.5M/day (Mar 2026) to ~0.95M/day (Apr 2026)?
-- Groups March and April 2026 transactions by the *parent* of the signing and receiving accounts,
-- so an app that spreads activity across many user accounts (e.g. 12345.tg, x.sweat) shows up as one row.
--   64-hex implicit accounts        -> '(implicit)'
--   0x... accounts                  -> '(eth-implicit)'
--   .near / .tg names with 3+ labels -> last two labels  (game.hot.tg -> hot.tg)
--   .near / .tg names with 2 labels  -> '*.near' / '*.tg' (alice.near, 12345.tg)
--   anything else                   -> its top-level name (wallet.kaiching -> kaiching)
-- Two months only, so the scan is small. Used for: C2 counterpoint.
CREATE TEMP FUNCTION parent(a STRING) AS (
  CASE
    WHEN REGEXP_CONTAINS(a, r'^[0-9a-f]{64}$') THEN '(implicit)'
    WHEN REGEXP_CONTAINS(a, r'^0x[0-9a-f]{40}$') THEN '(eth-implicit)'
    WHEN REGEXP_CONTAINS(a, r'\.(near|tg)$') AND ARRAY_LENGTH(SPLIT(a, '.')) >= 3
      THEN CONCAT(ARRAY_REVERSE(SPLIT(a, '.'))[OFFSET(1)], '.', ARRAY_REVERSE(SPLIT(a, '.'))[OFFSET(0)])
    WHEN REGEXP_CONTAINS(a, r'\.(near|tg)$') THEN CONCAT('*.', ARRAY_REVERSE(SPLIT(a, '.'))[OFFSET(0)])
    ELSE ARRAY_REVERSE(SPLIT(a, '.'))[OFFSET(0)]
  END
);

WITH t AS (
  SELECT
    FORMAT_DATE('%Y-%m', block_date) AS month,
    parent(signer_account_id) AS signer_parent,
    parent(receiver_account_id) AS receiver_parent
  FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
  WHERE block_date BETWEEN '2026-03-01' AND '2026-04-30'
),
grouped AS (
  SELECT
    IF(GROUPING(signer_parent) = 0, 'signer', 'receiver') AS side,
    month,
    COALESCE(signer_parent, receiver_parent) AS account_parent,
    COUNT(*) AS transactions
  FROM t
  GROUP BY GROUPING SETS ((month, signer_parent), (month, receiver_parent))
)
SELECT *
FROM grouped
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY side, month ORDER BY transactions DESC) <= 30
ORDER BY side, month, transactions DESC
