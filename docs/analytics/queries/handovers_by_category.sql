-- Handovers by category
--
-- Handovers in the period per item category. An item with several
-- categories counts once in each, so category rows can add up to more than
-- the "All handovers" row, which counts each handover once.
--
-- Reads:          borrowd_items_transactionstatuschange, borrowd_items_transaction,
--                 borrowd_items_item_categories, borrowd_items_itemcategory,
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
        t.item_id,
        CASE c.to_status WHEN 50 THEN 'Borrow' ELSE 'Give-away' END AS kind
    FROM borrowd_items_transactionstatuschange c
    JOIN borrowd_items_transaction t ON t.id = c.transaction_id
    CROSS JOIN params p
    WHERE NOT c.backfilled
      AND (
          (c.from_status = 40 AND c.to_status = 50)     -- COLLECTION_ASSERTED -> COLLECTED
          OR (c.from_status = 15 AND c.to_status = 95)  -- GIVEAWAY_REQUESTED -> OWNERSHIP_TRANSFERRED
      )
      AND c.changed_at >= p.start_at AND c.changed_at < p.end_at
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
),

by_category AS (
    SELECT
        coalesce(cat.name, '(no category)') AS category,
        count(*) AS handovers,
        count(*) FILTER (WHERE h.kind = 'Borrow') AS borrows,
        count(*) FILTER (WHERE h.kind = 'Give-away') AS giveaways
    FROM handovers h
    LEFT JOIN borrowd_items_item_categories ic ON ic.item_id = h.item_id
    LEFT JOIN borrowd_items_itemcategory cat ON cat.id = ic.itemcategory_id
    GROUP BY 1
)

SELECT category, handovers, borrows, giveaways
FROM (
    SELECT 1 AS position, category, handovers, borrows, giveaways FROM by_category
    UNION ALL
    SELECT
        2,
        'All handovers (each counted once)',
        count(*),
        count(*) FILTER (WHERE kind = 'Borrow'),
        count(*) FILTER (WHERE kind = 'Give-away')
    FROM handovers
) AS result
ORDER BY position, handovers DESC, category;
