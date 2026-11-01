-- Active groups (30-day)
--
-- As of params.as_of: groups with at least 1 handover in the previous 30
-- days, and groups with 3 or more. A handover counts toward each group the
-- item is shared with in which both parties were members at the time; see
-- README.md "Group attribution".
--
-- Reads:          borrowd_items_transactionstatuschange, borrowd_items_transaction,
--                 borrowd_items_item, borrowd_items_item_shared_with_groups,
--                 borrowd_groups_borrowdgroup, borrowd_groups_membership,
--                 borrowd_groups_membershipdeparture, borrowd_users_borrowduser
-- Complete from:  2026-10-26 (status history and membership departures)

WITH params AS (
    SELECT
        now() AS as_of,  -- the 30 days end just before this instant
        interval '30 days' AS window_length,
        3 AS busy_threshold
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

groups AS (
    SELECT g.id
    FROM borrowd_groups_borrowdgroup g
    WHERE g.deleted_at IS NULL
      AND (g.created_by_id IS NULL OR g.created_by_id NOT IN (SELECT id FROM excluded_users))
),

-- Who was in which group, and when. Pending join requests aren't
-- memberships yet; departures cover members who have since left.
member_spans AS (
    SELECT m.user_id, m.group_id, m.joined_at, NULL::timestamptz AS left_at
    FROM borrowd_groups_membership m
    WHERE m.status <> 'PENDING'
    UNION ALL
    SELECT d.departed_user_id, d.group_id, d.joined_at, d.left_at
    FROM borrowd_groups_membershipdeparture d
    WHERE d.group_id IS NOT NULL
),

handovers AS (
    SELECT c.transaction_id, c.changed_at, t.item_id, t.party1_id, t.party2_id
    FROM borrowd_items_transactionstatuschange c
    JOIN borrowd_items_transaction t ON t.id = c.transaction_id
    CROSS JOIN params p
    WHERE NOT c.backfilled
      AND (
          (c.from_status = 40 AND c.to_status = 50)     -- COLLECTION_ASSERTED -> COLLECTED
          OR (c.from_status = 15 AND c.to_status = 95)  -- GIVEAWAY_REQUESTED -> OWNERSHIP_TRANSFERRED
      )
      AND c.changed_at >= p.as_of - p.window_length AND c.changed_at < p.as_of
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
),

handover_groups AS (
    SELECT h.transaction_id, g.id AS group_id
    FROM handovers h
    JOIN borrowd_items_item i ON i.id = h.item_id
    JOIN groups g
      ON i.share_with_all_groups
      OR EXISTS (
          SELECT 1 FROM borrowd_items_item_shared_with_groups s
          WHERE s.item_id = i.id AND s.borrowdgroup_id = g.id
      )
    WHERE EXISTS (
            SELECT 1 FROM member_spans ms
            WHERE ms.group_id = g.id AND ms.user_id = h.party1_id
              AND ms.joined_at <= h.changed_at
              AND (ms.left_at IS NULL OR ms.left_at > h.changed_at)
        )
      AND EXISTS (
            SELECT 1 FROM member_spans ms
            WHERE ms.group_id = g.id AND ms.user_id = h.party2_id
              AND ms.joined_at <= h.changed_at
              AND (ms.left_at IS NULL OR ms.left_at > h.changed_at)
        )
),

handovers_per_group AS (
    SELECT group_id, count(*) AS handovers
    FROM handover_groups
    GROUP BY group_id
)

SELECT
    (SELECT count(*) FROM groups) AS groups,
    count(*) FILTER (WHERE hg.handovers >= 1) AS active_groups,
    count(*) FILTER (WHERE hg.handovers >= p.busy_threshold) AS groups_with_3_plus_handovers
FROM handovers_per_group hg, params p;
