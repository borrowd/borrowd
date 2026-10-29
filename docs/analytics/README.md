# Analytics queries

Read-only SQL (PostgreSQL 17) that turns the activity data captured in
[#632](https://github.com/borrowd/borrowd/issues/632) into Borrow'd's
activity metrics. One file per metric lives in [`queries/`](queries/). There
is no report command or dashboard: run the queries by hand against
production.

## Running a query

1. Open a tunnel to the production database with the Platform.sh CLI, for
   example `platform tunnel:single --relationship db`. It prints the local
   host, port, user and password to use.
2. In pgAdmin, register a server with those details and open the **Query
   Tool** on it.
3. Start the session in read-only mode, so nothing can write to production
   by accident:

   ```sql
   SET default_transaction_read_only = on;
   ```

4. Open a file from `queries/` (**Open File** in the Query Tool, or paste its
   contents), change the values in its `params` block if needed, and run it
   (F5). Edit nothing outside `params`.

Each file is a single `SELECT`, so it also runs unchanged in `psql`.

### Before the first run

Accounts with `exclude_from_metrics` set are left out of every metric. Tick
it in the Django admin (Users → the user → *Exclude from metrics*) for the
`system` user and for any test or staff test accounts. To see which accounts
are excluded (IDs only):

```sql
SELECT id, username = 'system' AS is_system_user
FROM borrowd_users_borrowduser
WHERE exclude_from_metrics OR username = 'system';
```

The `system` user appears whether or not it's flagged; check that
`exclude_from_metrics` is set on it.

## Conventions

- **`params`:** every file starts with a `params` block holding its date
  range and thresholds. By default, period metrics cover the last 30 days
  ending now and "as of" metrics use now, so a file gives current results
  when run unchanged. Status history only starts on 2026-10-26, so until
  2026-11-25 the default 30 days include days with no recorded history.
- **Dates:** ranges are half-open (`>= start_at`, `< end_at`) and in UTC.
  Monthly results use UTC calendar months.
- **Exclusions:** excluded users, their items, any transaction where either
  party is excluded, and groups they created are left out.
- **Deleted records:** soft-deleted users, groups and items are left out of
  current totals but kept in historical activity (a handover that happened
  still counts).
- **Statuses:** written as integers with the status name in a comment beside
  each, so they can be checked against `borrowd_items/statuses.py` whenever
  statuses change.
- **Headers:** each file lists the tables it reads and the date its results
  are complete from.

## When results are complete

The three #632 changes were deployed to production on **2026-10-26**:

- **Transaction status history** (`TransactionStatusChange`): can't time
  anything before that date. Every transaction that existed then got one
  backfilled row (`backfilled = true`) recording its status at the time;
  queries treat those as current state only, never as a timed change.
- **Activity tracking** (`UserActivityDay`): October 2026 is a partial
  month, so November 2026 is the first complete one.
- **Join method and departures** (`Membership.join_method`,
  `MembershipDeparture`): members who left a group before that date left no
  record.

Metrics that use current status (snapshot totals, growth, request outcomes,
stale requests, messaging effect, item request rate) are complete for all
time.

### When to expect results

Empty or zero results from a history-based query soon after the deploy are
expected, not a bug.

- **Meaningful for all time:** `snapshot_totals`, `growth`,
  `request_outcomes`, `stale_requests`, `messaging_effect`,
  `item_request_rate`, the lifetime columns of `repeat_sharers`, the group,
  item and request steps of `activation`, and the member, item, request and
  join columns of `group_health`.
- **Count activity since 2026-10-26 only:** `handovers`,
  `completed_borrows`, `active_groups`, `handovers_by_category`,
  `owner_response_time`, the 90-day columns of `repeat_sharers`, and the
  handover, sharing-member and departure columns of `group_health`. Their
  default 30-day window is fully covered from 2026-11-25.
- **Need whole periods to pass first:**

  | Query | First complete result |
  |---|---|
  | `monthly_active_users` | 2026-12-01 (November 2026); the current month shows as partial |
  | `cohort_retention` | 2026-12-01 for each cohort's first month from November 2026, then one more month each month |
  | `activation` (handover step) | About 2026-12-25 (signups from 2026-10-26 plus 60 days) |

## Shared definitions

| Term | Definition |
|---|---|
| Handover | A non-backfilled status change from `COLLECTION_ASSERTED` (40) to `COLLECTED` (50), a borrow, or from `GIVEAWAY_REQUESTED` (15) to `OWNERSHIP_TRANSFERRED` (95), a give-away. A transaction has at most one. |
| Completed borrow | A status change to `RETURNED` (70) |
| Completed give-away | A transaction whose status is `OWNERSHIP_TRANSFERRED` (95), by either route below |
| Request | A transaction, counted at its `created_at`. Every transaction starts as a borrow or give-away request. |
| Final state | `REJECTED` (20), `RETURNED` (70), `CANCELLED` (80), `RESOLVED` (90) or `OWNERSHIP_TRANSFERRED` (95) |
| Completion rate | Completed (70 or 95) divided by requests in a final state |
| Sharing member | A user who was either party to at least 1 handover |

**Why only those two routes count as handovers:** status history also
reaches 50 and 95 in ways where nothing changes hands:

- `GIVEAWAY_OFFERED` (52) → `COLLECTED` (50): the borrower declined a gift
  offer for an item they already hold.
- `GIVEAWAY_OFFERED` (52) → `OWNERSHIP_TRANSFERRED` (95): the borrower
  accepted the gift of an item they already hold; the handover was the
  original borrow.

Counting every change to 50 or 95 would count one physical handover two or
three times.

### Group attribution

`Transaction` has no group column, so a handover or request counts toward
every group that:

- the item is shared with (its *Shared with* groups, or every group when it's
  shared with all groups), and
- both parties were members of at that moment (current memberships plus
  `MembershipDeparture` records; pending join requests don't count).

One handover can count toward several groups; platform totals count it once.

Limitations:

- Item sharing settings are only stored as they are now, so an item's
  current settings apply to past activity too.
- A member approved after a pending join request has `joined_at` set to when
  they asked to join, not when they were approved.
- `ChatThread.conversation_group` records the group a requester picked when
  starting a conversation. It only exists for requests with a conversation,
  so it isn't used here, but it could refine attribution later.

### Request outcome buckets

| Bucket | Statuses |
|---|---|
| Completed | 70 `RETURNED`, 95 `OWNERSHIP_TRANSFERRED` |
| In progress, after handover | 50 `COLLECTED`, 55 `RETURN_REQUESTED`, 60 `RETURN_ASSERTED` |
| Open, before handover | 10 `REQUESTED`, 15 `GIVEAWAY_REQUESTED`, 30 `ACCEPTED`, 40 `COLLECTION_ASSERTED`, 52 `GIVEAWAY_OFFERED` |
| Rejected | 20 `REJECTED` |
| Cancelled | 80 `CANCELLED` |
| Disputed | 65 `DISPUTED` |
| Force-resolved | 90 `RESOLVED`, split by `resolution_reason` |

## Metrics

### Snapshot and growth

| File | Metric | Definition | Complete from |
|---|---|---|---|
| [`snapshot_totals.sql`](queries/snapshot_totals.sql) | Platform totals | As of `as_of`: users, groups, largest group (active members), non-deleted items, distinct listers (owners of non-deleted items), requests, completed borrows and give-aways, distinct borrowers and lenders (parties to completed borrows and give-aways), and completion rate. Uses current status, so it stays comparable with the October 2026 snapshot. | All time |
| [`growth.sql`](queries/growth.sql) | New in period | New users, groups, items (including items later deleted) and requests, by month | All time |

### Core activity

| File | Metric | Definition | Complete from |
|---|---|---|---|
| [`handovers.sql`](queries/handovers.sql) | Handovers | Handovers in the period, split borrow versus give-away | 2026-10-26 |
| [`completed_borrows.sql`](queries/completed_borrows.sql) | Completed borrows | Changes to `RETURNED` in the period | 2026-10-26 |
| [`active_groups.sql`](queries/active_groups.sql) | Active groups (30-day) | As of `as_of`: groups with at least 1 handover in the previous 30 days, and groups with 3 or more | 2026-10-26 |
| [`request_outcomes.sql`](queries/request_outcomes.sql) | Request outcomes | Requests created in the period, by the bucket of their current status | All time |
| [`stale_requests.sql`](queries/stale_requests.sql) | Stale requests | Requests still `REQUESTED` or `GIVEAWAY_REQUESTED` more than 7 days after creation; one row each. Uses current status, so leave `as_of` at `now()`. | All time |
| [`owner_response_time.sql`](queries/owner_response_time.sql) | Owner response time | For requests created in the period: median hours from the request to the item owner's first status change, overall and by request type | 2026-10-26 |
| [`messaging_effect.sql`](queries/messaging_effect.sql) | Messaging effect | For requests created in the period: share with at least 1 non-system message, and completion rate with versus without messages. Messages sent before the request count once the conversation is linked to it. | All time |

### Engagement and retention

| File | Metric | Definition | Complete from |
|---|---|---|---|
| [`activation.sql`](queries/activation.sql) | Activation funnel | Per monthly signup cohort: share that joined or created a group within 7 days, listed an item within 14 (including items later deleted), made or received a request within 30, and was party to a handover within 60. Users whose window hasn't fully passed are left out of that step. | Group step can miss groups left before 2026-10-26; handover step counts only users who signed up from 2026-10-26 |
| [`monthly_active_users.sql`](queries/monthly_active_users.sql) | Monthly active users | Distinct users with at least 1 `UserActivityDay` in each month | November 2026 |
| [`cohort_retention.sql`](queries/cohort_retention.sql) | Cohort retention | Share of each signup cohort active in months 1, 2 and 3 after their signup month. Empty until the month has passed, and for months before November 2026. | November 2026 |
| [`repeat_sharers.sql`](queries/repeat_sharers.sql) | Repeat sharers | Users party to 2 or more handovers, lifetime and in the 90 days before `as_of`. Lifetime counts infer handovers before status history from current status; the file lists which statuses it treats as post-handover. | Lifetime: all time (inferred); 90 days: 2026-10-26 |

### Liquidity and groups

| File | Metric | Definition | Complete from |
|---|---|---|---|
| [`item_request_rate.sql`](queries/item_request_rate.sql) | Item request rate | Share of non-deleted items that existed at the start of the 90 days before `as_of` and received at least 1 request during them | All time |
| [`handovers_by_category.sql`](queries/handovers_by_category.sql) | Handovers by category | Handovers in the period per item category. Items with several categories count in each, so a final row gives the total with each handover counted once. | 2026-10-26 |
| [`group_health.sql`](queries/group_health.sql) | Group health | One row per group: ID and name, creator user ID (`join_method = GROUP_CREATOR`), moderator user IDs, active members, items shared to the group, requests and handovers in the last 30 days, distinct sharing members, and joins and departures in the period. User IDs only, no names or emails. | 2026-10-26 |

## Out of scope

- Champion and badge metrics (no model yet).
- Push and notification metrics (arrive with the PWA).
- Environmental impact estimates; `handovers_by_category.sql` is an input to
  that methodology, not the methodology itself.
- Any report command, dashboard or scheduled run.
