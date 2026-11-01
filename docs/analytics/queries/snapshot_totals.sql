-- Snapshot totals
--
-- Platform totals as of params.as_of. Uses each transaction's current
-- status, so it includes transactions from before status history existed
-- and stays comparable with the October 2026 snapshot.
--
-- Reads:          borrowd_users_borrowduser, borrowd_groups_borrowdgroup,
--                 borrowd_groups_membership, borrowd_items_item,
--                 borrowd_items_transaction
-- Complete from:  all time (no dependency on #632 history)

WITH params AS (
    SELECT
        now() AS as_of  -- count records created before this instant
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

users AS (
    SELECT u.id
    FROM borrowd_users_borrowduser u, params p
    WHERE NOT u.exclude_from_metrics
      AND u.deleted_at IS NULL
      AND u.date_joined < p.as_of
),

groups AS (
    SELECT g.id
    FROM borrowd_groups_borrowdgroup g, params p
    WHERE g.deleted_at IS NULL
      AND g.created_at < p.as_of
      AND (g.created_by_id IS NULL OR g.created_by_id NOT IN (SELECT id FROM excluded_users))
),

group_sizes AS (
    SELECT m.group_id, count(*) AS active_members
    FROM borrowd_groups_membership m
    JOIN groups g ON g.id = m.group_id
    JOIN users u ON u.id = m.user_id
    CROSS JOIN params p
    WHERE m.status = 'ACTIVE'
      AND m.joined_at < p.as_of
    GROUP BY m.group_id
),

items AS (
    SELECT i.id, i.owner_id
    FROM borrowd_items_item i, params p
    WHERE i.deleted_at IS NULL
      AND i.created_at < p.as_of
      AND i.owner_id NOT IN (SELECT id FROM excluded_users)
),

transactions AS (
    SELECT t.id, t.status, t.party1_id, t.party2_id
    FROM borrowd_items_transaction t, params p
    WHERE t.created_at < p.as_of
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
),

totals AS (
    SELECT
        (SELECT count(*) FROM users) AS users,
        (SELECT count(*) FROM groups) AS groups,
        (SELECT coalesce(max(active_members), 0) FROM group_sizes) AS largest_group,
        (SELECT count(*) FROM items) AS items,
        (SELECT count(DISTINCT owner_id) FROM items) AS listers,
        (SELECT count(*) FROM transactions) AS requests,
        (SELECT count(*) FROM transactions WHERE status = 70) AS completed_borrows,  -- RETURNED
        (SELECT count(*) FROM transactions WHERE status = 95) AS completed_giveaways,  -- OWNERSHIP_TRANSFERRED
        (SELECT count(DISTINCT party2_id) FROM transactions WHERE status IN (70, 95)) AS borrowers,
        (SELECT count(DISTINCT party1_id) FROM transactions WHERE status IN (70, 95)) AS lenders,
        (SELECT count(*) FROM transactions
            WHERE status IN (
                20,  -- REJECTED
                70,  -- RETURNED
                80,  -- CANCELLED
                90,  -- RESOLVED
                95   -- OWNERSHIP_TRANSFERRED
            )) AS final_requests
)

SELECT v.metric, v.value
FROM totals,
LATERAL (VALUES
    (1, 'Users', users::numeric),
    (2, 'Groups', groups),
    (3, 'Largest group (active members)', largest_group),
    (4, 'Items (non-deleted)', items),
    (5, 'Distinct listers (owners of non-deleted items)', listers),
    (6, 'Requests', requests),
    (7, 'Completed borrows', completed_borrows),
    (8, 'Completed give-aways', completed_giveaways),
    (9, 'Distinct borrowers (completed borrows and give-aways)', borrowers),
    (10, 'Distinct lenders (completed borrows and give-aways)', lenders),
    (11, 'Completion rate % (completed / requests in a final state)',
        round(100.0 * (completed_borrows + completed_giveaways) / nullif(final_requests, 0), 1))
) AS v(position, metric, value)
ORDER BY v.position;
