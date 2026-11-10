# PR summary

Shared by the PR skills (`triplicate-review`, `pr-followup`). A short,
plain-language orientation printed to the human in the terminal. It is never
posted to GitHub and never goes into a review body.

## Rules

- Write it from the diff and the code. The PR description is a hint only; if it
  disagrees with the diff, say so under "Worth knowing".
- Describe the final state of the change, not the session. No verdict: the
  recommendation comes later in the skill.
- Plain language. No file-by-file lists, and no jargon the reader would have to
  look up. Use the project's own terms (Item, Transaction, BorrowdGroup,
  Membership, group sharing, the state machines, object-level permissions,
  notifications, the beta wall).
- Keep the full form to about 8 to 12 lines.
- Use the template exactly: the header line, then each bold label on its own
  line, in order. Do not merge sections into a paragraph. `Touches` is always
  present, even if only to say nothing core is touched.
- Print it as the last message of a turn, with no tool call after it. Text
  written between tool calls can be collapsed to a one-line recap; a turn's
  final message is shown in full. Gather the facts first, then print.

## Full form

Used by `triplicate-review`.

```
### PR #<n> — <title>   (<author>, <files> files, +<add>/−<del>, draft|ready)

**What it does**
One to three sentences on the change, for someone who has not opened the diff.
Say what changes for users or behavior, not which files moved.

**Where it fits in Borrow'd**
One to three sentences placing it in the system: which part of the app it
touches and why that matters.

**Touches**
<areas that apply, separated by " · ", each with a few words of specifics>

**Worth knowing before reviewing**
- <only if there is something; at most two bullets>
```

### Filled example

```
### PR #660 — feat/one open transaction per item   (vguzman812, 12 files, +378/−406, draft)

**What it does**
Makes the database guarantee that an Item has at most one open Transaction at
a time. Code that coped with "what if there are several?" is removed. A request
that loses a race to another request now gets "already requested" instead of
an error.

**Where it fits in Borrow'd**
This is the core of the Item/Transaction lifecycle, the path every request,
accept, pickup and return goes through. It builds on the locking work in its
base branch, `fix/item-lifecycle-locking`, so the diff is only the changes on
top of that.

**Touches**
Data & queries (new unique constraint, migration that aborts on duplicates,
needs a Postgres run) · Item/Transaction state machines (request path) ·
Notifications (messaging tests adjusted)

**Worth knowing before reviewing**
- Draft, stacked on another branch, with an unfilled description template.
- The migration fails on databases that already have duplicate open
  transactions, so data cleanup comes first.
```

### Touches

Choose from these areas. List only the ones that apply; an unlisted area means
"not touched". Do not write "no" lines: a wrong "no" reads as reassurance.

1. **Data & queries**: migrations, locking (`select_for_update`), raw SQL.
   These need a Postgres run, since SQLite does not enforce the same rules.
2. **Permissions, auth & personal data**: guardian object-level permissions,
   login, profile data, photos.
3. **Groups & sharing**: Item visibility (`share_with_all_groups`,
   `shared_with_groups`), Membership lifecycle.
4. **Item/Transaction state machines**: statuses, actions, dual confirmation,
   availability subscriptions.
5. **Notifications**: what is sent, to whom, and when.
6. **Config, dependencies & deploy**: settings, env vars, pinned packages, CI,
   platform.sh.
7. **User-facing UI**: templates, components, styling.

Example line: `Groups & sharing (who sees an Item) · Permissions (view check)`

If none apply: `nothing in the app's core paths (docs/tooling/tests only)`.

### Worth knowing

Anything that makes the PR riskier or larger than it looks: a migration, a
locking change, a mismatch between description and diff, an area with no tests.
Omit the section when there is nothing.

## Short form

Used by `pr-followup`. The reader already knows the PR, so give a reminder and
the delta, not an introduction. Omit "Touches" and "Worth knowing", except for
areas newly touched since the last review (reviewer mode).

```
### PR #<n> — <title>   (<author>, <files> files, +<add>/−<del>, draft|ready)
One or two sentences: what it does and where it fits in Borrow'd.
```

- **Author mode**: add a thread count (open, resolved, bot-opened).
- **Reviewer mode**: add `**Since your last review**`, one to three sentences
  based on the commits after `baseline_review`: whether they address the open
  threads and whether the scope grew. Add `Touches (new): ...` only for areas
  touched since that review, for example "new: migration".
