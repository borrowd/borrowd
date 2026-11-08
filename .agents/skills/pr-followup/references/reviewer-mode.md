# Reviewer mode: re-review after changes

The user is reviewing someone else's PR. Find what changed since their last
review, decide whether the PR is now approvable, and offer the right response.

Once you know what changed (step 1), print the short-form summary from
`.agents/shared/pr-summary.md`, with its "Since your last review" line, as its
own message before the thread checks and any further tool call.

## 1. Find what changed

From the `pr_feedback.sh` output:

- `baseline_review`: the user's last substantive review (approved, changes
  requested, or a comment review with a body or inline comments). Pending and
  dismissed reviews, and empty reviews created by thread replies, are skipped.
  If it is `null`, the user has not reviewed this PR yet: treat it as a first
  review and offer to run the `triplicate-review` skill instead.
- The commits after `baseline_review.commit`, and the diff from that commit to
  the current head (`pr.headRefOid`). Create a read-only worktree and fetch the
  base and head as described in `.agents/shared/pr-worktrees.md`, then:

  ```bash
  git cat-file -e <baseline-sha> || echo "baseline commit not available"
  git diff <baseline-sha>..HEAD
  git log --no-merges <baseline-sha>..HEAD
  ```

  If the baseline commit is not available (the branch was force-pushed or
  rebased), say so and review against the base branch instead, using each
  thread's current code to judge whether it was addressed. If the author merged
  the base into the branch since the baseline, ignore the merge's changes and
  look only at the PR's own commits.

## 2. Check each open thread

For every unresolved thread the user started (and any other unresolved thread
they ask about), read the current code and the author's replies, then classify:

- **Addressed**: the code now does what was asked, or the author's push-back is
  convincing. Verify against the code, not the author's description.
- **Not addressed**: the problem is still there.
- **Partly addressed**: say what remains.
- **Disagreement**: the author pushed back and you are not persuaded; say why in
  one sentence, or recommend conceding if their point holds.

Also read the new changes for fresh problems the update introduced, with the
same standards as a first review. For a large update, offer to run
`triplicate-review` on it.

## 3. Decide: is it approvable?

Use the verdict rule in `.agents/shared/pr-comments.md`. Classify everything
still outstanding as **blocking** (`high`: correctness, security, data
integrity, missing tests for changed behavior, a convention violation the user
cares about) or **non-blocking** (`medium` the user is willing to carry, and
nits).

- **Approve**: nothing blocking remains. If non-blocking items remain, still
  approve and restate them in the review body "for future iterations", briefly,
  so they are not lost. Do not hold the PR for them.
- **Comment or request changes**: something blocking remains, or the update
  introduced a new problem.
- Also report `pr.checks` (CI) and `pr.reviewDecision`, and whether the PR is a
  draft. A red CI or a draft is worth saying out loud; both are the human's call.

## 4. Draft the response

- **Approve**: a short review body (what was addressed, plus any carried-over
  non-blocking items). By house style it carries no inline comments.
- **Not approvable**: one inline comment per new or remaining blocker, on a
  line that appears in the PR diff (anything that cannot be anchored goes in the
  body). The body is a short summary of what is done, what remains, and the
  verdict. Nits go in the collapsed list.
- **Threads to resolve**: only addressed threads the user started. Do not
  resolve threads others started (bots included) without asking, and do not
  resolve threads that are not addressed.
- Where a thread needs a short reply (for example "still open because ..."),
  draft it; skip it when resolving speaks for itself.

## 5. Present, then act

Show the human: the determination and why, the list of threads with their
classification, and the full draft (body, inline comments, replies, resolves).
Ask whether to post, and what to change. The human decides the verdict; offer a
recommendation, not a decision.

On an explicit yes, write the actions file, run the dry run, show it, and post
with `--post --expect-head`, as described in `.agents/shared/pr-comments.md`. If
the head moved, redo the check against the new changes.

Offer to remove the follow-up worktree afterward.
