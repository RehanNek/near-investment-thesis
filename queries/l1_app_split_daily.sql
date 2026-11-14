-- Daily L1 transactions since 2025-01-01, split by the two consumer apps that dominated L1 activity:
--   KaiChing: signer is 'kaiching' or any *.kaiching account (65% of March 2026 transactions; left in April 2026)
--   HOT:      signer is any *.tg account (HOT's Telegram game and wallet accounts)
-- Signer-based, because these apps sign their users' transactions from their own sub-accounts
-- (queries/l1_drop_mar_apr_2026.sql shows signer and receiver totals for KaiChing are identical).
-- Reads only the signer column. Intents transactions per day come from l1_activity.sql.
-- Used for: C2 (L1 activity with the largest apps removed).
SELECT
  block_date,
  COUNT(*) AS transactions,
  COUNTIF(signer_account_id = 'kaiching' OR ENDS_WITH(signer_account_id, '.kaiching')) AS kaiching_tx,
  COUNTIF(ENDS_WITH(signer_account_id, '.tg')) AS hot_tg_tx
FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
WHERE block_date >= '2025-01-01'
GROUP BY block_date
ORDER BY block_date
