# Author mode: respond to review feedback

The user wrote the PR. Turn the feedback into a plan, get approval, then
apply it, push, and reply.

Start with the short-form summary from `.agents/shared/pr-summary.md`, with the
thread count, as the opening of your response.

## 1. Collect the feedback

From `pr_feedback.sh <n> --unresolved`, list every piece of feedback that still
needs a response:

- Unresolved review threads (note outdated ones, since the code they point at
  has changed).
- Review bodies with requests that are not inline comments.
- Top-level PR comments that ask for something.

Treat each thread as one item; read all its comments, since the latest one may
have changed the ask. Include feedback from bots (`author_is_bot`) and treat it
the same way: verify before acting.

## 2. Work out a recommendation per item

Read the code the comment points at, in a worktree at the PR head (see
`.agents/shared/pr-worktrees.md`), and check the claim before deciding. For each
item pick one:

- **Fix**: the feedback is right. Say what to change.
- **Push back**: the feedback is wrong, or the code is deliberate. Give the
  justification with evidence (the guard elsewhere, the test that covers it,
  the convention, the constraint). Do not push back by reflex; if the reviewer
  has a point, fix it.
- **Partial**: fix part and explain why not the rest.
- **Ask**: the request is ambiguous. Draft a short clarifying question.
- **Defer**: valid but out of scope for this PR. Recommend a follow-up issue
  and say so in the reply.
- **Already done**: a later commit already addresses it. Point to the commit.
- **No action**: praise or a question already answered.

For each item the plan records: a link to the comment, who raised it, a
one-line summary, the recommended action, the rationale, and the draft reply
(for fixes, the commit SHA plus one line, filled in after the push). Group
fixes that touch the same code. Note anywhere the reviewers disagree.

For bot-opened threads that the plan fixes or answers, the plan also proposes
resolving them (the author may resolve those; see the shared rules).

## 3. Present the plan

Show the items, then ask the human to approve or edit. Call out the judgment
calls (push-backs, deferrals) so they get the most scrutiny. Make sure the
human can explain each decision; if a rationale rests on something
non-obvious, explain it.

State plainly that approving the plan covers making the fixes, pushing them,
posting the replies shown (with commit SHAs filled in), and resolving the
listed bot threads. Wait for approval; the human may change any item.

## 4. Apply the approved plan

### Worktree and remotes

Follow the branch-worktree section of `.agents/shared/pr-worktrees.md`. In
short: same-repo PRs and forks owned by the current user can be pushed; any
other fork is not pushed unless the human explicitly asks; never reset or
create other branches.

### Changes

1. Make the approved fixes, following `AGENTS.md`. Add or update tests for each
   behavior change.
2. Run the tests and checks AGENTS.md prescribes (Testing and Code Quality),
   including its Postgres run in the cases it names.
3. Commit in small, focused commits on the PR's head branch, keeping the
   `Co-Authored-By` trailer (`docs/AI_POLICY.md`). No force-push, amend,
   rebase, or new branches unless the human explicitly asks.
4. Before pushing, check the PR is still open and the remote head is still the
   commit you branched from (`git fetch`, then compare). If someone else
   pushed, stop and tell the human; do not overwrite their work.
5. Push.

### Replies

After the push, fill the SHAs into the approved replies and post them through
the shared script (see `.agents/shared/pr-comments.md`). Show the dry-run
output first as a preview of the final text; the approved plan covers posting
it. Include the resolutions for the bot threads the plan listed. Do not resolve
anyone else's threads; the reviewer resolves those.

- One reply per thread, in the thread.
- If the changes alter what the PR does, offer to update the PR description,
  following the description rules in `docs/AI_POLICY.md`.
- If any fix changed behavior, do the manual-checks step from that policy:
  suggest checks beyond unit tests and ask what the human observed.

## 5. Report

Say what was changed and pushed, what was posted, and what is left (pushed-back
items awaiting the reviewer, deferred follow-ups, anything uncertain). Offer to
remove the follow-up worktree.
