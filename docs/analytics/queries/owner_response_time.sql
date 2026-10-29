-- Owner response time
--
-- For requests created in the period: median hours from the request to the
-- item owner's first status change (accept, reject, approve or decline).
-- Requests the owner hasn't acted on yet are counted but have no time.
--
-- Reads:          borrowd_items_transactionstatuschange, borrowd_items_transaction,
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

-- Only requests whose creation was recorded in status history; older ones
-- have a single backfilled row and no timings.
requests AS (
    SELECT
        t.id,
        t.party1_id,
        t.created_at,
        CASE created.to_status
            WHEN 10 THEN 'Borrow'     -- REQUESTED
            WHEN 15 THEN 'Give-away'  -- GIVEAWAY_REQUESTED
        END AS request_type
    FROM borrowd_items_transaction t
    JOIN borrowd_items_transactionstatuschange created
      ON created.transaction_id = t.id
     AND created.from_status IS NULL
     AND NOT created.backfilled
    CROSS JOIN params p
    WHERE t.created_at >= p.start_at AND t.created_at < p.end_at
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
),

first_owner_change AS (
    SELECT c.transaction_id, min(c.changed_at) AS changed_at
    FROM borrowd_items_transactionstatuschange c
    JOIN requests r ON r.id = c.transaction_id
    WHERE NOT c.backfilled
      AND c.from_status IS NOT NULL
      AND c.actor_id = r.party1_id  -- party1 is the item owner
    GROUP BY c.transaction_id
),

response_hours AS (
    SELECT
        r.request_type,
        extract(epoch FROM f.changed_at - r.created_at) / 3600 AS hours
    FROM requests r
    LEFT JOIN first_owner_change f ON f.transaction_id = r.id
)

SELECT
    coalesce(request_type, 'All') AS request_type,
    count(*) AS requests,
    count(hours) AS owner_responded,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY hours)::numeric, 1) AS median_hours
FROM response_hours
GROUP BY GROUPING SETS ((request_type), ())
ORDER BY request_type NULLS LAST;
