-- Daily block counts, height range and end-of-day total supply, since genesis.
-- Used for: supply history (C6, scenarios) and checking BigQuery completeness against block heights.
SELECT
  block_date,
  COUNT(*) AS blocks,
  MIN(block_height) AS first_height,
  MAX(block_height) AS last_height,
  ARRAY_AGG(total_supply ORDER BY block_height DESC LIMIT 1)[OFFSET(0)] / 1e24 AS end_of_day_total_supply_near
FROM `bigquery-public-data.crypto_near_mainnet_us.blocks`
WHERE block_date >= '2020-07-21'
GROUP BY block_date
ORDER BY block_date
