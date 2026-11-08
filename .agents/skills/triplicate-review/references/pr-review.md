# Reviewing a pull request

## Resolve the PR

Accept a number or URL. Gather the state with the shared script:

```bash
.agents/shared/pr_feedback.sh <n>
```

Stop and tell the human if the PR is not open. Note `headRefOid` (the review is
posted against that commit), `baseRefName`, whether the PR is a draft, and
whether the current user is the author (`is_author`). Keep the existing
unresolved threads and reviews in mind: you use them when adjudicating, below.

## When `gh` is unavailable

If `gh` is missing, unauthenticated, or blocked (for example in a sandbox), do
not stop. Review the checked-out branch against its merge-base with the base
branch (`git diff $(git merge-base HEAD <base>)...HEAD`) in the current
checkout, with all three reviewers reading it directly. Skip the worktrees and
the existing-feedback check, and tell the human that existing threads and
reviews were not considered. Print the full draft review (verdict, overview,
inline comments with file and line) and do not post.

## Summary

After the size check, print the full-form PR summary from
`.agents/shared/pr-summary.md` as its own message, before any further tool
call (this section comes before worktrees and reviewer launches for that
reason). Do not post it.

## Worktrees

Create three read-only worktrees at the PR head and fetch the base, as
described in `.agents/shared/pr-worktrees.md` (suffixes `a`, `b`, `c`). Each
reviewer gets its own path and diffs against the fetched base.

## Existing feedback

The reviewers do not see existing comments, so their findings stay
independent. When adjudicating, drop any finding that an open thread or earlier
review already raises, and mention it in the report instead of posting it
again.

## Draft the review

Build the review from confirmed findings, following the style and verdict rule
in `.agents/shared/pr-comments.md`:

- **Inline comments** for every `high` and `medium` finding, one per finding,
  each brief and plain: what is wrong, why it matters, and the fix if clear.
- **Overview comment**:
  1. One or two sentences saying what the PR does and the verdict.
  2. The main points, if the inline comments need framing.
  3. The collapsed list of nits and other low-value items.
  4. The final line: `Reviewed with AI assistance (three independent
     reviews, findings checked against the code).`
- **Event**: from the verdict rule. If the user is the PR author, it is
  `COMMENT`.

## Show, then post

Show the human the full draft: verdict, overview text, and each inline comment
with its file and line. Ask whether to post, and what to change. Only after an
explicit yes, post the draft as the `review` object with the shared script
(dry run, then `--post --expect-head`), as described in
`.agents/shared/pr-comments.md`. The overview text, including the `<details>`
list and footer, is the `body`.

## Cleanup

Offer to remove the three worktrees (see `.agents/shared/pr-worktrees.md`).
