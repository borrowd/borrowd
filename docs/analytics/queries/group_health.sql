-- Group health
--
-- One row per group. User IDs only, never names or emails.
--   creator_user_id         member who created the group (NULL if they have left)
--   moderator_user_ids      current active moderators
--   active_members          current active members
--   items_shared            non-deleted items currently shared to the group
--   requests_30d            requests in the 30 days before params.end_at
--   handovers_30d           handovers in the 30 days before params.end_at
--   sharing_members         distinct members party to a handover in the period
--   joins / departures      memberships started and ended in the period
-- Requests and handovers count toward each group the item is shared with in
-- which both parties were members at the time; see README.md "Group
-- attribution".
--
-- Reads:          borrowd_groups_borrowdgroup, borrowd_groups_membership,
--                 borrowd_groups_membershipdeparture, borrowd_items_item,
--                 borrowd_items_item_shared_with_groups, borrowd_items_transaction,
--                 borrowd_items_transactionstatuschange, borrowd_users_borrowduser
-- Complete from:  2026-10-26 (status history, join method and departures)

WITH params AS (
    SELECT
        now() - interval '30 days' AS start_at,  -- inclusive; or e.g. timestamptz '2026-11-01 00:00:00+00'
        now() AS end_at,    -- exclusive
        interval '30 days' AS recent_window
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

groups AS (
    SELECT g.id, g.name
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

active_memberships AS (
    SELECT m.group_id, m.user_id, m.is_moderator, m.join_method
    FROM borrowd_groups_membership m
    WHERE m.status = 'ACTIVE'
      AND m.user_id NOT IN (SELECT id FROM excluded_users)
),

-- Requests and handovers, each with the moment it happened.
events AS (
    SELECT 'request' AS kind, t.id AS transaction_id, t.created_at AS happened_at,
           t.item_id, t.party1_id, t.party2_id
    FROM borrowd_items_transaction t
    WHERE t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
    UNION ALL
    SELECT 'handover', t.id, c.changed_at, t.item_id, t.party1_id, t.party2_id
    FROM borrowd_items_transactionstatuschange c
    JOIN borrowd_items_transaction t ON t.id = c.transaction_id
    WHERE NOT c.backfilled
      AND (
          (c.from_status = 40 AND c.to_status = 50)     -- COLLECTION_ASSERTED -> COLLECTED
          OR (c.from_status = 15 AND c.to_status = 95)  -- GIVEAWAY_REQUESTED -> OWNERSHIP_TRANSFERRED
      )
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
),

event_groups AS (
    SELECT e.kind, e.transaction_id, e.happened_at, e.party1_id, e.party2_id, g.id AS group_id
    FROM events e
    JOIN borrowd_items_item i ON i.id = e.item_id
    JOIN groups g
      ON i.share_with_all_groups
      OR EXISTS (
          SELECT 1 FROM borrowd_items_item_shared_with_groups s
          WHERE s.item_id = i.id AND s.borrowdgroup_id = g.id
      )
    WHERE EXISTS (
            SELECT 1 FROM member_spans ms
            WHERE ms.group_id = g.id AND ms.user_id = e.party1_id
              AND ms.joined_at <= e.happened_at
              AND (ms.left_at IS NULL OR ms.left_at > e.happened_at)
        )
      AND EXISTS (
            SELECT 1 FROM member_spans ms
            WHERE ms.group_id = g.id AND ms.user_id = e.party2_id
              AND ms.joined_at <= e.happened_at
              AND (ms.left_at IS NULL OR ms.left_at > e.happened_at)
        )
),

items_shared AS (
    SELECT g.id AS group_id, count(*) AS items
    FROM groups g
    JOIN borrowd_items_item i
      ON i.deleted_at IS NULL
     AND i.owner_id NOT IN (SELECT id FROM excluded_users)
     AND (
         EXISTS (
             SELECT 1 FROM borrowd_items_item_shared_with_groups s
             WHERE s.item_id = i.id AND s.borrowdgroup_id = g.id
         )
         OR (
             i.share_with_all_groups
             AND EXISTS (
                 SELECT 1 FROM active_memberships am
                 WHERE am.group_id = g.id AND am.user_id = i.owner_id
             )
         )
     )
    GROUP BY g.id
),

recent_activity AS (
    SELECT
        eg.group_id,
        count(*) FILTER (WHERE eg.kind = 'request') AS requests,
        count(*) FILTER (WHERE eg.kind = 'handover') AS handovers
    FROM event_groups eg, params p
    WHERE eg.happened_at >= p.end_at - p.recent_window AND eg.happened_at < p.end_at
    GROUP BY eg.group_id
),

sharing_members AS (
    SELECT sm.group_id, count(DISTINCT sm.user_id) AS members
    FROM (
        SELECT eg.group_id, eg.party1_id AS user_id, eg.happened_at
        FROM event_groups eg WHERE eg.kind = 'handover'
        UNION ALL
        SELECT eg.group_id, eg.party2_id, eg.happened_at
        FROM event_groups eg WHERE eg.kind = 'handover'
    ) AS sm, params p
    WHERE sm.happened_at >= p.start_at AND sm.happened_at < p.end_at
    GROUP BY sm.group_id
),

joins AS (
    SELECT ms.group_id, count(*) AS joins
    FROM member_spans ms, params p
    WHERE ms.joined_at >= p.start_at AND ms.joined_at < p.end_at
      AND ms.user_id NOT IN (SELECT id FROM excluded_users)
    GROUP BY ms.group_id
),

departures AS (
    SELECT d.group_id, count(*) AS departures
    FROM borrowd_groups_membershipdeparture d, params p
    WHERE d.left_at >= p.start_at AND d.left_at < p.end_at
      AND d.departed_user_id NOT IN (SELECT id FROM excluded_users)
    GROUP BY d.group_id
)

SELECT
    g.id AS group_id,
    g.name AS group_name,
    (SELECT min(am.user_id) FROM active_memberships am
        WHERE am.group_id = g.id AND am.join_method = 'GROUP_CREATOR') AS creator_user_id,
    (SELECT array_agg(am.user_id ORDER BY am.user_id) FROM active_memberships am
        WHERE am.group_id = g.id AND am.is_moderator) AS moderator_user_ids,
    (SELECT count(*) FROM active_memberships am WHERE am.group_id = g.id) AS active_members,
    coalesce(isd.items, 0) AS items_shared,
    coalesce(ra.requests, 0) AS requests_30d,
    coalesce(ra.handovers, 0) AS handovers_30d,
    coalesce(sm.members, 0) AS sharing_members,
    coalesce(j.joins, 0) AS joins,
    coalesce(d.departures, 0) AS departures
FROM groups g
LEFT JOIN items_shared isd ON isd.group_id = g.id
LEFT JOIN recent_activity ra ON ra.group_id = g.id
LEFT JOIN sharing_members sm ON sm.group_id = g.id
LEFT JOIN joins j ON j.group_id = g.id
LEFT JOIN departures d ON d.group_id = g.id
ORDER BY active_members DESC, g.id;
