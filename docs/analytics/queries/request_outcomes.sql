-- Request outcomes
--
-- Requests created in the period, grouped by the bucket of their current
-- status. Force-resolved requests are split by resolution reason.
--
-- Reads:          borrowd_items_transaction, borrowd_users_borrowduser
-- Complete from:  all time (uses current status, not history)

WITH params AS (
    SELECT
        now() - interval '30 days' AS start_at,  -- inclusive; or e.g. timestamptz '2026-11-01 00:00:00+00'
        now() AS end_at     -- exclusive
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

requests AS (
    SELECT
        CASE
            WHEN t.status IN (70, 95) THEN '1. Completed'  -- RETURNED, OWNERSHIP_TRANSFERRED
            WHEN t.status IN (50, 55, 60) THEN '2. In progress, after handover'  -- COLLECTED, RETURN_REQUESTED, RETURN_ASSERTED
            WHEN t.status IN (10, 15, 30, 40, 52) THEN '3. Open, before handover'  -- REQUESTED, GIVEAWAY_REQUESTED, ACCEPTED, COLLECTION_ASSERTED, GIVEAWAY_OFFERED
            WHEN t.status = 20 THEN '4. Rejected'  -- REJECTED
            WHEN t.status = 80 THEN '5. Cancelled'  -- CANCELLED
            WHEN t.status = 65 THEN '6. Disputed'  -- DISPUTED
            WHEN t.status = 90 THEN '7. Force-resolved: ' || coalesce(t.resolution_reason, 'no reason recorded')  -- RESOLVED
            ELSE '8. Unknown status ' || t.status
        END AS bucket
    FROM borrowd_items_transaction t, params p
    WHERE t.created_at >= p.start_at AND t.created_at < p.end_at
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
)

SELECT
    bucket,
    count(*) AS requests,
    round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS share_pct
FROM requests
GROUP BY bucket
ORDER BY bucket;
