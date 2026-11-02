-- Handovers
--
-- Handovers in the period, split borrow versus give-away. A handover is
-- COLLECTION_ASSERTED -> COLLECTED (borrow) or GIVEAWAY_REQUESTED ->
-- OWNERSHIP_TRANSFERRED (give-away). Other routes into those statuses are
-- not handovers: a declined gift offer returns to COLLECTED, and an accepted
-- gift offer moves an item the borrower already holds. See README.md.
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
),

handovers AS (
    SELECT
        c.transaction_id,
        c.changed_at,
        CASE c.to_status WHEN 50 THEN 'Borrow' ELSE 'Give-away' END AS kind
    FROM borrowd_items_transactionstatuschange c
    JOIN borrowd_items_transaction t ON t.id = c.transaction_id
    WHERE NOT c.backfilled
      AND (
          (c.from_status = 40 AND c.to_status = 50)     -- COLLECTION_ASSERTED -> COLLECTED
          OR (c.from_status = 15 AND c.to_status = 95)  -- GIVEAWAY_REQUESTED -> OWNERSHIP_TRANSFERRED
      )
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
)

SELECT
    count(*) AS handovers,
    count(*) FILTER (WHERE h.kind = 'Borrow') AS borrows,
    count(*) FILTER (WHERE h.kind = 'Give-away') AS giveaways
FROM handovers h, params p
WHERE h.changed_at >= p.start_at AND h.changed_at < p.end_at;
