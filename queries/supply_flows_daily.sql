-- Daily NEAR burned and NEAR minted since 2025-01-01, from block-to-block changes in total supply.
-- Within an epoch, total supply only falls: by the NEAR burned in each block (70% of L1 gas fees;
-- the other 30% is paid to contract developers and stays in supply). At each epoch boundary it
-- jumps up by the newly minted NEAR (validator rewards, i.e. inflation). So:
--   burned = sum of block-to-block decreases, minted = sum of increases.
-- Reads two numeric columns from the 32 GB blocks table, far cheaper than summing fees from the
-- 9.8 TB execution_outcomes table (173 GB). Differences are taken within each calendar month, so one
-- block-to-block change per month (the first block of the month) is not counted.
-- Used for: C1 (L1 side of the revenue mix: burned NEAR) and C6 (burn and issuance in the capture ratio).
WITH b AS (
  SELECT
    block_date,
    total_supply - LAG(total_supply) OVER (PARTITION BY DATE_TRUNC(block_date, MONTH) ORDER BY block_height) AS d
  FROM `bigquery-public-data.crypto_near_mainnet_us.blocks`
  WHERE block_date >= '2025-01-01'
)
SELECT
  block_date,
  SUM(IF(d < 0, -d, 0)) / 1e24 AS burned_near,
  SUM(IF(d > 0, d, 0)) / 1e24 AS minted_near,
  COUNTIF(d > 0) AS mint_blocks
FROM b
GROUP BY block_date
ORDER BY block_date
