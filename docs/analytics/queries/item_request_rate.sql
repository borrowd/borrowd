-- Item request rate
--
-- Of the non-deleted items that already existed at the start of the 90 days
-- before params.as_of, the share that received at least 1 request during
-- those 90 days.
--
-- Reads:          borrowd_items_item, borrowd_items_transaction, borrowd_users_borrowduser
-- Complete from:  all time (no dependency on #632 history)

WITH params AS (
    SELECT
        now() AS as_of,
        interval '90 days' AS window_length
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

items AS (
    SELECT i.id
    FROM borrowd_items_item i, params p
    WHERE i.deleted_at IS NULL
      AND i.created_at < p.as_of - p.window_length
      AND i.owner_id NOT IN (SELECT id FROM excluded_users)
),

requested_items AS (
    SELECT DISTINCT t.item_id
    FROM borrowd_items_transaction t, params p
    WHERE t.created_at >= p.as_of - p.window_length AND t.created_at < p.as_of
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
)

SELECT
    count(*) AS items,
    count(ri.item_id) AS items_requested,
    round(100.0 * count(ri.item_id) / nullif(count(*), 0), 1) AS request_rate_pct
FROM items i
LEFT JOIN requested_items ri ON ri.item_id = i.id;
