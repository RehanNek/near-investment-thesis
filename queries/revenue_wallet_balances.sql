-- Daily (per-epoch) NEAR balances of the wallets that receive NEAR Intents revenue,
-- as listed on revenue.near.org. The table is clustered by account_id, so this is cheap.
-- Used for: C6 (buybacks held vs burned) and cross-checking the revenue tracker.
SELECT
  epoch_date,
  account_id,
  liquid,
  staked,
  unstaked_not_liquid,
  reward
FROM `bigquery-public-data.crypto_near_mainnet_us.ft_balances_daily`
WHERE account_id IN (
  'buybacks.multisignature.near',
  'fefundsadmin.sputnik-dao.near',
  '1csfundsadmin.sputnik-dao.near'
)
  AND epoch_date >= '2025-01-01'  -- partition filter (this table has epoch_date, not block_date)
ORDER BY account_id, epoch_date
