-- Stale requests
--
-- Requests still waiting on the owner (REQUESTED or GIVEAWAY_REQUESTED)
-- more than 7 days after creation. The row count is the metric. Uses
-- current status, so run it with params.as_of left at now().
--
-- Reads:          borrowd_items_transaction, borrowd_users_borrowduser
-- Complete from:  all time (uses current status, not history)

WITH params AS (
    SELECT
        now() AS as_of,
        interval '7 days' AS stale_after
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
)

SELECT
    t.id AS transaction_id,
    t.item_id,
    CASE t.status
        WHEN 10 THEN 'REQUESTED'
        WHEN 15 THEN 'GIVEAWAY_REQUESTED'
    END AS status,
    t.created_at,
    round(extract(epoch FROM p.as_of - t.created_at) / 86400, 1) AS days_waiting
FROM borrowd_items_transaction t, params p
WHERE t.status IN (
        10,  -- REQUESTED
        15   -- GIVEAWAY_REQUESTED
    )
  AND t.created_at < p.as_of - p.stale_after
  AND t.party1_id NOT IN (SELECT id FROM excluded_users)
  AND t.party2_id NOT IN (SELECT id FROM excluded_users)
ORDER BY t.created_at;
