-- Monthly active users
--
-- Distinct users who used the app on at least 1 day in each calendar month
-- (UTC). A day of use is recorded the first time a signed-in user makes a
-- request that day.
--
-- Reads:          borrowd_users_useractivityday, borrowd_users_borrowduser
-- Complete from:  2026-10-26 (activity tracking); October 2026 is partial,
--                 so November 2026 is the first complete month

WITH params AS (
    SELECT
        timestamptz '2026-10-01 00:00:00+00' AS start_at,  -- inclusive; use the first of a month (October 2026 is partial)
        now() AS end_at  -- exclusive; the current month shows as a partial month
),

months AS (
    SELECT generate_series(
        date_trunc('month', p.start_at AT TIME ZONE 'UTC'),
        (p.end_at AT TIME ZONE 'UTC') - interval '1 microsecond',
        interval '1 month'
    ) AS month_start
    FROM params p
),

active AS (
    SELECT date_trunc('month', a.date) AS month_start, count(DISTINCT a.user_id) AS users
    FROM borrowd_users_useractivityday a
    JOIN borrowd_users_borrowduser u ON u.id = a.user_id
    CROSS JOIN params p
    WHERE NOT u.exclude_from_metrics
      AND a.date >= (p.start_at AT TIME ZONE 'UTC')::date
      AND a.date < (p.end_at AT TIME ZONE 'UTC')::date
    GROUP BY 1
)

SELECT m.month_start::date AS month, coalesce(a.users, 0) AS monthly_active_users
FROM months m
LEFT JOIN active a ON a.month_start = m.month_start
ORDER BY m.month_start;
