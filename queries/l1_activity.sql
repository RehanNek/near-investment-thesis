-- L1 activity since 2025-01-01, from one scan of the transactions table (two result shapes):
--   level = 'daily':    one row per day with total transactions, distinct signers (proxy for
--                       daily active accounts), transactions sent directly to intents.near,
--                       and NEAR burnt converting transactions to receipts.
--   level = 'receiver': one row per month and receiving account (top 25 per month), to see
--                       which apps drive L1 activity and which large app left in early 2026.
-- GROUPING SETS lets both come from a single pass over four columns, which roughly halves the
-- bytes scanned compared with two separate queries. Longer L1 history (2020+) comes from NearBlocks.
-- Used for: C2 and the L1 layer in Part 2.
WITH grouped AS (
  SELECT
    IF(GROUPING(block_date) = 0, 'daily', 'receiver') AS level,
    block_date,
    month,
    receiver_account_id,
    COUNT(*) AS transactions,
    COUNT(DISTINCT signer_account_id) AS signers,
    COUNTIF(receiver_account_id = 'intents.near') AS tx_to_intents,
    COUNT(DISTINCT IF(receiver_account_id = 'intents.near', signer_account_id, NULL)) AS signers_to_intents,
    SUM(receipt_conversion_tokens_burnt) / 1e24 AS tx_conversion_burnt_near
  FROM (
    SELECT block_date, DATE_TRUNC(block_date, MONTH) AS month, receiver_account_id,
           signer_account_id, receipt_conversion_tokens_burnt
    FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
    WHERE block_date >= '2025-01-01'
  )
  GROUP BY GROUPING SETS ((block_date), (month, receiver_account_id))
)
SELECT *
FROM grouped
WHERE TRUE
QUALIFY level = 'daily'
     OR ROW_NUMBER() OVER (PARTITION BY level, month ORDER BY transactions DESC) <= 25
ORDER BY level, block_date, month, transactions DESC
