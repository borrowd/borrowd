-- Messaging effect
--
-- For requests created in the period: the share with at least 1 message
-- written by a person (not a system message), and the completion rate with
-- versus without messages. Messages sent before the request exists count,
-- because the conversation thread is linked to the request when it's made.
-- Completion rate = completed / requests in a final state.
--
-- Reads:          borrowd_items_transaction, borrowd_messaging_chatthread,
--                 borrowd_messaging_message, borrowd_users_borrowduser
-- Complete from:  all time (uses current status, not history)

WITH params AS (
    SELECT
        now() - interval '30 days' AS start_at,  -- inclusive; or e.g. timestamptz '2026-11-01 00:00:00+00'
        now() AS end_at     -- exclusive
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

messaged_transactions AS (
    SELECT DISTINCT th.transaction_id
    FROM borrowd_messaging_chatthread th
    JOIN borrowd_messaging_message msg ON msg.thread_id = th.id
    WHERE th.transaction_id IS NOT NULL
      AND NOT msg.is_system
),

requests AS (
    SELECT
        t.status,
        mt.transaction_id IS NOT NULL AS has_messages
    FROM borrowd_items_transaction t
    LEFT JOIN messaged_transactions mt ON mt.transaction_id = t.id
    CROSS JOIN params p
    WHERE t.created_at >= p.start_at AND t.created_at < p.end_at
      AND t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
)

SELECT
    CASE WHEN has_messages THEN 'With messages' ELSE 'Without messages' END AS requests_group,
    count(*) AS requests,
    round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS share_pct,
    count(*) FILTER (WHERE status IN (20, 70, 80, 90, 95)) AS final_requests,  -- REJECTED, RETURNED, CANCELLED, RESOLVED, OWNERSHIP_TRANSFERRED
    count(*) FILTER (WHERE status IN (70, 95)) AS completed,                    -- RETURNED, OWNERSHIP_TRANSFERRED
    round(
        100.0 * count(*) FILTER (WHERE status IN (70, 95))
        / nullif(count(*) FILTER (WHERE status IN (20, 70, 80, 90, 95)), 0),
        1
    ) AS completion_rate_pct
FROM requests
GROUP BY has_messages
ORDER BY has_messages DESC;
