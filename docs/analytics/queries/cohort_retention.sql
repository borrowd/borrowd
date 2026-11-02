-- Cohort retention
--
-- For each monthly signup cohort (UTC): the share of its users who used the
-- app at least once in month 1, 2 and 3 after their signup month. A month
-- shows as empty (NULL) until it has fully passed by params.as_of, and for
-- months before activity tracking was complete.
--
-- Reads:          borrowd_users_borrowduser, borrowd_users_useractivityday
-- Complete from:  2026-10-26 (activity tracking); only months from
--                 November 2026 onward count

WITH params AS (
    SELECT
        timestamptz '2026-08-01 00:00:00+00' AS start_at,  -- signups from (inclusive); use the first of a month
        timestamptz '2027-01-01 00:00:00+00' AS end_at,    -- signups until (exclusive); use the first of a month
        now() AS as_of,
        date '2026-11-01' AS first_complete_month  -- first full month of activity tracking
),

new_users AS (
    SELECT u.id, date_trunc('month', u.date_joined AT TIME ZONE 'UTC')::date AS cohort
    FROM borrowd_users_borrowduser u, params p
    WHERE NOT u.exclude_from_metrics
      AND u.date_joined >= p.start_at AND u.date_joined < p.end_at
),

offsets AS (
    SELECT generate_series(1, 3) AS month_offset
),

cohort_months AS (
    SELECT
        nu.cohort,
        nu.id AS user_id,
        o.month_offset,
        (nu.cohort + o.month_offset * interval '1 month')::date AS month_start,
        (nu.cohort + (o.month_offset + 1) * interval '1 month')::date AS month_end
    FROM new_users nu
    CROSS JOIN offsets o
),

measured AS (
    SELECT
        cm.cohort,
        cm.month_offset,
        cm.month_start >= p.first_complete_month
            AND cm.month_end <= (p.as_of AT TIME ZONE 'UTC')::date AS countable,
        EXISTS (
            SELECT 1 FROM borrowd_users_useractivityday a
            WHERE a.user_id = cm.user_id
              AND a.date >= cm.month_start AND a.date < cm.month_end
        ) AS was_active
    FROM cohort_months cm, params p
),

retention AS (
    SELECT
        cohort,
        month_offset,
        CASE WHEN bool_and(countable)
            THEN round(100.0 * count(*) FILTER (WHERE was_active) / count(*), 1)
        END AS active_pct
    FROM measured
    GROUP BY cohort, month_offset
)

SELECT
    r.cohort AS signup_month,
    (SELECT count(*) FROM new_users nu WHERE nu.cohort = r.cohort) AS new_users,
    max(r.active_pct) FILTER (WHERE r.month_offset = 1) AS month_1_pct,
    max(r.active_pct) FILTER (WHERE r.month_offset = 2) AS month_2_pct,
    max(r.active_pct) FILTER (WHERE r.month_offset = 3) AS month_3_pct
FROM retention r
GROUP BY r.cohort
ORDER BY r.cohort;
