-- Completed borrows
--
-- Borrows that reached RETURNED in the period.
--
-- Reads:          borrowd_items_transactionstatuschange, borrowd_items_transaction,
--                 borrowd_users_borrowduser
-- Complete from:  2026-10-26 (transaction status history)

WITH params AS (
    SELECT
        now() - interval '30 days' AS start_at,  -- inclusive; or e.g. timestamptz '2026-11-01 00:00:00+00'
        now() AS end_at     -- exclusive
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
)

SELECT count(*) AS completed_borrows
FROM borrowd_items_transactionstatuschange c
JOIN borrowd_items_transaction t ON t.id = c.transaction_id
CROSS JOIN params p
WHERE NOT c.backfilled
  AND c.to_status = 70  -- RETURNED
  AND c.changed_at >= p.start_at AND c.changed_at < p.end_at
  AND t.party1_id NOT IN (SELECT id FROM excluded_users)
  AND t.party2_id NOT IN (SELECT id FROM excluded_users);
