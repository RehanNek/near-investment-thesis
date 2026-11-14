-- Per-epoch balance of the nearai.pool.near staking pool (found among current validators via RPC).
-- Hypothesis to test: this is the pool behind NEAR AI's "Staking for Inference" (launched 2026-07-30,
-- https://near.ai/blog/staking-for-near-ai). NEAR AI's docs don't name the pool, so this is evidence,
-- not confirmation. The table is clustered by account_id, so the scan is small.
-- Used for: C5 (NEAR AI as a working third layer).
SELECT epoch_date, account_id, liquid, staked, unstaked_not_liquid
FROM `bigquery-public-data.crypto_near_mainnet_us.ft_balances_daily`
WHERE account_id = 'nearai.pool.near'
  AND epoch_date >= '2025-01-01'  -- partition filter (this table has epoch_date, not block_date)
ORDER BY epoch_date
