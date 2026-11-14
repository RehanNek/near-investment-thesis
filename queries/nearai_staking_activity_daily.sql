-- Daily activity on stake.dao (House of Stake staking contract for NEAR AI products) since 2026-07-01:
-- function-call receipts sent to it, distinct accounts calling it, and NEAR attached to those calls
-- (deposits for locks, farm stakes and purchases). Gives a day-by-day history of NEAR AI staking
-- activity, which the contract's current-state views can't.
-- Reads four columns for ~4 months. Used for: C5 (NEAR AI staking adoption over time).
SELECT
  block_date,
  COUNTIF(action_kind = 'FUNCTION_CALL') AS function_calls,
  COUNT(DISTINCT IF(action_kind = 'FUNCTION_CALL', receipt_predecessor_account_id, NULL)) AS calling_accounts
FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
WHERE block_date >= '2026-07-01'
  AND receipt_receiver_account_id = 'stake.dao'
GROUP BY block_date
ORDER BY block_date
