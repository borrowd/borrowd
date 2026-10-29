-- Growth
--
-- New users, groups, items and requests per calendar month (UTC). Items
-- count when created, including items later deleted.
--
-- Reads:          borrowd_users_borrowduser, borrowd_groups_borrowdgroup,
--                 borrowd_items_item, borrowd_items_transaction
-- Complete from:  all time (no dependency on #632 history)

WITH params AS (
    SELECT
        timestamptz '2026-01-01 00:00:00+00' AS start_at,  -- inclusive; use the first of a month
        now() AS end_at  -- exclusive; the current month shows as a partial month
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

months AS (
    SELECT generate_series(
        date_trunc('month', p.start_at AT TIME ZONE 'UTC'),
        (p.end_at AT TIME ZONE 'UTC') - interval '1 microsecond',
        interval '1 month'
    ) AS month_start
    FROM params p
),

new_users AS (
    SELECT date_trunc('month', u.date_joined AT TIME ZONE 'UTC') AS month_start, count(*) AS n
    FROM borrowd_users_borrowduser u, params p
    WHERE NOT u.exclude_from_metrics
      AND u.date_joined >= p.start_at AND u.date_joined < p.end_at
    GROUP BY 1
),

new_groups AS (
    SELECT date_trunc('month', g.created_at AT TIME ZONE 'UTC') AS month_start, count(*) AS n
    FROM borrowd_groups_borrowdgroup g, params p
    WHERE (g.created_by_id IS NULL OR g.created_by_id NOT IN (SELECT id FROM excluded_users))
      AND g.created_at >= p.start_at AND g.created_at < p.end_at
    GROUP BY 1
),

new_items AS (
    SELECT date_trunc('month', i.created_at AT TIME ZONE 'UTC') AS month_start, count(*) AS n
    FROM borrowd_items_item i, params p
    WHERE i.created_by_id NOT IN (SELECT id FROM excluded_users)
      AND i.created_at >= p.start_at AND i.created_at < p.end_at
    GROUP BY 1
),

new_requests AS (
    SELECT date_trunc('month', t.created_at AT TIME ZONE 'UTC') AS month_start, count(*) AS n
    FROM borrowd_items_transaction t, params p
    WHERE t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
      AND t.created_at >= p.start_at AND t.created_at < p.end_at
    GROUP BY 1
)

SELECT
    m.month_start::date AS month,
    coalesce(nu.n, 0) AS new_users,
    coalesce(ng.n, 0) AS new_groups,
    coalesce(ni.n, 0) AS new_items,
    coalesce(nr.n, 0) AS new_requests
FROM months m
LEFT JOIN new_users nu ON nu.month_start = m.month_start
LEFT JOIN new_groups ng ON ng.month_start = m.month_start
LEFT JOIN new_items ni ON ni.month_start = m.month_start
LEFT JOIN new_requests nr ON nr.month_start = m.month_start
ORDER BY m.month_start;
