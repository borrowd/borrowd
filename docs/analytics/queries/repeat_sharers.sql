-- Repeat sharers
--
-- Users who were party (as lender or borrower) to 2 or more handovers:
-- lifetime, and in the 90 days before params.as_of. A transaction has at
-- most one handover.
--
-- Lifetime counts include transactions from before status history existed
-- by inferring a handover from current status. These statuses only occur
-- after a handover:
--   50 COLLECTED, 52 GIVEAWAY_OFFERED, 55 RETURN_REQUESTED,
--   60 RETURN_ASSERTED, 65 DISPUTED, 70 RETURNED, 95 OWNERSHIP_TRANSFERRED
-- 90 RESOLVED is left out: a transaction can be force-resolved before or
-- after its handover, so it only counts when history records the handover.
--
-- Reads:          borrowd_items_transactionstatuschange, borrowd_items_transaction,
--                 borrowd_users_borrowduser
-- Complete from:  lifetime: all time (inferred before 2026-10-26);
--                 trailing 90 days: 2026-10-26 (transaction status history)

WITH params AS (
    SELECT
        now() AS as_of,
        interval '90 days' AS trailing_window
),

excluded_users AS (
    SELECT id FROM borrowd_users_borrowduser WHERE exclude_from_metrics
),

transactions AS (
    SELECT t.id, t.status, t.party1_id, t.party2_id
    FROM borrowd_items_transaction t
    WHERE t.party1_id NOT IN (SELECT id FROM excluded_users)
      AND t.party2_id NOT IN (SELECT id FROM excluded_users)
),

recorded_handovers AS (
    SELECT c.transaction_id, c.changed_at
    FROM borrowd_items_transactionstatuschange c
    WHERE NOT c.backfilled
      AND (
          (c.from_status = 40 AND c.to_status = 50)     -- COLLECTION_ASSERTED -> COLLECTED
          OR (c.from_status = 15 AND c.to_status = 95)  -- GIVEAWAY_REQUESTED -> OWNERSHIP_TRANSFERRED
      )
),

handed_over AS (
    SELECT
        t.id,
        t.party1_id,
        t.party2_id,
        rh.changed_at  -- NULL when the handover is inferred from current status
    FROM transactions t
    LEFT JOIN recorded_handovers rh ON rh.transaction_id = t.id
    WHERE rh.transaction_id IS NOT NULL
       OR t.status IN (50, 52, 55, 60, 65, 70, 95)
),

participation AS (
    SELECT party1_id AS user_id, id, changed_at FROM handed_over
    UNION ALL
    SELECT party2_id, id, changed_at FROM handed_over
),

per_user AS (
    SELECT
        pa.user_id,
        count(DISTINCT pa.id) AS lifetime_handovers,
        count(DISTINCT pa.id) FILTER (
            WHERE pa.changed_at >= p.as_of - p.trailing_window AND pa.changed_at < p.as_of
        ) AS trailing_handovers
    FROM participation pa, params p
    GROUP BY pa.user_id
)

SELECT
    count(*) FILTER (WHERE lifetime_handovers >= 1) AS sharing_members_lifetime,
    count(*) FILTER (WHERE lifetime_handovers >= 2) AS repeat_sharers_lifetime,
    count(*) FILTER (WHERE trailing_handovers >= 1) AS sharing_members_90d,
    count(*) FILTER (WHERE trailing_handovers >= 2) AS repeat_sharers_90d
FROM per_user;
