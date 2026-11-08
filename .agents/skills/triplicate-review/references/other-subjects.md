# Reviewing something other than a PR

Examples: a design comment, an issue, a plan, a doc, a branch with no PR.

## Decide how to review

1. Identify what the subject is and what a good review of it means: for a
   design, soundness, gaps, risks, and fit with the existing architecture; for a
   plan, feasibility, ordering and missing steps; for a branch, the same as a PR
   diff against `main`.
2. Gather the subject's text and any context the reviewers need (linked issue,
   relevant code). Put it in the reviewer prompt so all three see the same
   material.
3. If the right approach is unclear, state your approach to the human in one or
   two sentences and proceed unless they object.
4. Reviewers need no worktrees unless they must read or run code; if so, give
   each its own, as in the PR reference.

Before launching the reviewers, print a summary of the subject in the form
from `.agents/shared/pr-summary.md`, replacing "PR" with the subject type and
dropping any part that does not apply (for example the diff stats). Print it as
its own message, before any further tool call.

Then run steps 1 to 3 of the main workflow. Use the findings format from the
reviewer prompt, adapting severity to the subject: `high` is a flaw that would
invalidate the subject, `medium` is a gap worth fixing, `nit` is polish.

## Choose the next step

Recommend whatever fits what was reviewed, and offer to do it:

- Design comment or issue: draft a reply comment (plain language, brief).
- Plan or doc: propose specific revisions, and offer to apply them.
- Branch without a PR: offer to fix the findings or open a PR.

Follow the same rule as PRs: nothing is posted anywhere until the human
confirms the final text.
