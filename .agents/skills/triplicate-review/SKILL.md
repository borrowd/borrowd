---
name: triplicate-review
description: Review a pull request (or other artifact such as a design comment) with three independent reviewers running the same prompt, keep what they converge on, adjudicate one-off findings, and recommend approve, comment, or request changes. Use when asked for a triplicate review, a thorough or multi-reviewer review, or to review a PR by number or link.
compatibility: Requires git and jq; run from the repo root. Posting and existing-feedback checks need an authenticated gh CLI; without it, reviews a local branch and prints the draft.
---

# Triplicate review

Three independent reviewers get the identical prompt. Findings that several of
them reach independently are trusted; findings only one reached are checked
before they are believed. The result is a plain-language recommendation and,
for PRs, a drafted GitHub review you can post after the human approves it.

## Inputs

- **Subject**: a PR number or URL, or something else (design comment, issue,
  plan, document, branch).
- **Extra review guidance** (optional): any "how to review" text in the
  request. Pass it to the reviewers verbatim, after the default instructions.

## Rules

Run from the repo root. Read `.agents/shared/pr-comments.md` before drafting or
posting anything: it holds the safety rules, comment style, verdict rule and
the posting script. In short, nothing is posted without the human approving the
exact text.

Reviewers are read-only: they never edit files, commit, push, or post.

## Workflow

### 0. Classify the subject

- PR number or URL: follow the PR path in
  [references/pr-review.md](references/pr-review.md).
- Anything else: follow
  [references/other-subjects.md](references/other-subjects.md) to decide how
  to review it and what the next step is.

Before launching, check the subject's size. Three full reviews of a very large
diff are expensive and the PR may be too large to review well; if so, tell the
human and ask whether to continue or review part of it. Say so too if a PR is a
draft.

Then prepare the summary in the exact full form (template, labels and all)
from `.agents/shared/pr-summary.md`: gather what it needs (title, stats,
description, diff) now, but do not print it yet. See step 1 for when it is
shown.

### 1. Launch three reviewers

Build one reviewer prompt from
[references/reviewer-prompt.md](references/reviewer-prompt.md), filling in the
subject details and appending any extra review guidance. Launch three
subagents in parallel, all with exactly the same prompt, model and effort. For
a PR, each reviewer works in its own worktree; the prompt is identical except
for the worktree path.

Once the reviewers are launched in the background, print the summary as the
last message of the turn and make no tool call after it, then wait for the
reviewers' completion notifications and continue at step 2. Text written
between tool calls can be collapsed to a one-line recap by the terminal;
the last message of a turn is shown in full. The human reads it while the
reviewers work.

If the tool cannot run subagents in parallel, run three sequential passes, each
in a fresh context with the same prompt, and say that the passes were not
isolated from the main session. The turn cannot end after launching in that
case, so print the summary before the first pass and tell the human it may
appear collapsed. If it cannot run subagents at all, tell the
human, do one careful pass, and treat every finding as a singleton.

The reviewers are deliberately identical so that agreement between them counts
as independent confirmation. Review styles that vary the reviewers (personas,
multiple models) are separate skills, not options here.

Do not suggest likely findings to the reviewers or share one reviewer's output
with another.

### 2. Converge

Wait for all three to return. If one fails or times out, continue with the rest
and say so in the report; with fewer than three, use the adjustments in
[references/adjudication.md](references/adjudication.md). Then follow that file
to cluster findings and mark each as 3/3, 2/3, or singleton.

### 3. Adjudicate singletons

Verify each singleton yourself against the code (read the cited lines, run a
cheap test or repro). Mark each confirmed, rejected (keep a one-line reason),
or uncertain (ask the human).

### 4. Recommend and offer the next step

Write the recommendation in brief, plain language:

- For a PR: **approve**, **comment**, or **request changes**, with the reason.
  Draft the review as described in the PR reference. Show the human the full
  draft, then offer to post it.
- For anything else: recommend the next step suited to the subject and offer to
  do it.

Also report which findings were rejected and why, and offer to remove the
review worktrees.
