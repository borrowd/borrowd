-- Activation funnel
--
-- Per monthly signup cohort (UTC): the share of new users who
--   1. joined or created a group within 7 days of signing up,
--   2. listed an item within 14 days (including items later deleted),
--   3. made or received a request within 30 days,
--   4. were party to a handover within 60 days.
-- A user only counts toward a step once that step's window has fully
-- passed by params.as_of. Step 4 also needs status history for the whole
-- window, so it only includes users who signed up on or after
-- params.history_complete_from.
--
-- Reads:          borrowd_users_borrowduser, borrowd_groups_membership,
--                 borrowd_groups_membershipdeparture, borrowd_items_item,
--                 borrowd_items_transaction, borrowd_items_transactionstatuschange
-- Complete from:  steps 1-3 for any cohort (step 1 can miss groups left
--                 before 2026-10-26); step 4 from 2026-10-26 signups

WITH params AS (
    SELECT
        timestamptz '2026-01-01 00:00:00+00' AS start_at,  -- signups from (inclusive); use the first of a month
        timestamptz '2027-01-01 00:00:00+00' AS end_at,    -- signups until (exclusive); use the first of a month
        now() AS as_of,
        timestamptz '2026-10-26 00:00:00+00' AS history_complete_from
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

new_users AS (
    SELECT u.id, u.date_joined, date_trunc('month', u.date_joined AT TIME ZONE 'UTC') AS cohort
    FROM borrowd_users_borrowduser u, params p
    WHERE NOT u.exclude_from_metrics
      AND u.date_joined >= p.start_at AND u.date_joined < p.end_at
),

-- Every group membership a user has had, including ones since ended.
-- Pending join requests aren't memberships yet.
member_spans AS (
    SELECT m.user_id, m.joined_at
    FROM borrowd_groups_membership m
    WHERE m.status <> 'PENDING'
    UNION ALL
    SELECT d.departed_user_id, d.joined_at
    FROM borrowd_groups_membershipdeparture d
),

handovers AS (
    SELECT c.changed_at, t.party1_id, t.party2_id
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

steps AS (
    SELECT
        nu.cohort,
        nu.date_joined + interval '7 days' <= p.as_of AS group_eligible,
        EXISTS (
            SELECT 1 FROM member_spans ms
            WHERE ms.user_id = nu.id
              AND ms.joined_at < nu.date_joined + interval '7 days'
        ) AS joined_group,
        nu.date_joined + interval '14 days' <= p.as_of AS item_eligible,
        EXISTS (
            SELECT 1 FROM borrowd_items_item i
            WHERE i.created_by_id = nu.id
              AND i.created_at < nu.date_joined + interval '14 days'
        ) AS listed_item,
        nu.date_joined + interval '30 days' <= p.as_of AS request_eligible,
        EXISTS (
            SELECT 1 FROM borrowd_items_transaction t
            WHERE nu.id IN (t.party1_id, t.party2_id)
              AND t.created_at < nu.date_joined + interval '30 days'
              AND t.party1_id NOT IN (SELECT id FROM excluded_users)
              AND t.party2_id NOT IN (SELECT id FROM excluded_users)
        ) AS had_request,
        nu.date_joined + interval '60 days' <= p.as_of
            AND nu.date_joined >= p.history_complete_from AS handover_eligible,
        EXISTS (
            SELECT 1 FROM handovers h
            WHERE nu.id IN (h.party1_id, h.party2_id)
              AND h.changed_at < nu.date_joined + interval '60 days'
        ) AS had_handover
    FROM new_users nu, params p
)

SELECT
    cohort::date AS signup_month,
    count(*) AS new_users,
    count(*) FILTER (WHERE group_eligible) AS group_step_users,
    round(100.0 * count(*) FILTER (WHERE group_eligible AND joined_group)
        / nullif(count(*) FILTER (WHERE group_eligible), 0), 1) AS joined_group_7d_pct,
    count(*) FILTER (WHERE item_eligible) AS item_step_users,
    round(100.0 * count(*) FILTER (WHERE item_eligible AND listed_item)
        / nullif(count(*) FILTER (WHERE item_eligible), 0), 1) AS listed_item_14d_pct,
    count(*) FILTER (WHERE request_eligible) AS request_step_users,
    round(100.0 * count(*) FILTER (WHERE request_eligible AND had_request)
        / nullif(count(*) FILTER (WHERE request_eligible), 0), 1) AS request_30d_pct,
    count(*) FILTER (WHERE handover_eligible) AS handover_step_users,
    round(100.0 * count(*) FILTER (WHERE handover_eligible AND had_handover)
        / nullif(count(*) FILTER (WHERE handover_eligible), 0), 1) AS handover_60d_pct
FROM steps
GROUP BY cohort
ORDER BY cohort;
