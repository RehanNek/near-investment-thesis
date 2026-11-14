-- NEAR's daily circulating and total supply, as computed in the public dataset.
-- A reference table: the build does not read it (new supply comes from blocks_daily.sql and supply_flows_daily.sql).
-- The table has one row per day and starts on 2023-01-01, so the block_date filter keeps every row.
SELECT *
FROM `bigquery-public-data.crypto_near_mainnet_us.circulating_supply`
WHERE block_date >= '2023-01-01'
ORDER BY block_date
